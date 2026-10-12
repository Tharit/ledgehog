// The "Tag all N…" flow (decisions C6/C7, B13–B15): choose a tag, PREVIEW what it would do for the
// list's filter, confirm with the previewed count. The filter is captured when the dialog opens,
// so the preview and the write always speak about the same selection. Page-scoped, like the
// ledger store; the host patches what comes back into the list.

import { ApiError, applyBody, applyTag, createTag, tagEntry } from '#lib/api/index.js';
import { formatCount } from '#lib/format/index.js';
import {
	describeTagError,
	distinctTagErrors,
	SETTLE_STALE,
	type TagErrorScope
} from '#lib/ledger/errors.js';
import type { LedgerFilterState } from '#lib/ledger/filter.js';
import {
	eligibleMarkedRows,
	partialReport,
	taggedNotice,
	taggedSummary
} from '#lib/ledger/tag-all.js';
import type { Entry, EntryTagIds, Tag, TagApplyOut } from '#lib/types/domain.js';

export type TagAllHost = {
	filter: () => LedgerFilterState;
	locale: () => string;
	/** a tag was created in the dialog */
	addTag: (tag: Tag) => void;
	/** the rows the user changed that the tag filter no longer matches (marked in the list) */
	markedRows: () => readonly Entry[];
	/** a write failed: refetch what moved (rows in place, the tag list), as its error calls for */
	recover: (error: ApiError, scope: TagErrorScope) => void | Promise<void>;
	/** patch these entries into the list, quietly (a write that left the dialog open) */
	patch: (updates: readonly EntryTagIds[]) => void;
	/** the write succeeded: patch these entries and say it */
	applied: (updates: readonly EntryTagIds[], notice: string) => void;
};

/** at most this many single-entry writes in flight at once */
const EXTRAS_CONCURRENCY = 4;

export type TagAllStatus = 'idle' | 'previewing' | 'applying' | 'creating';

function asApiError(error: unknown): ApiError {
	return error instanceof ApiError
		? error
		: new ApiError(0, 'network_error', 'The server could not be reached.');
}

export class TagAllFlow {
	readonly #host: TagAllHost;
	open = $state(false);
	tag = $state.raw<Tag | null>(null);
	preview = $state.raw<TagApplyOut | null>(null);
	status = $state<TagAllStatus>('idle');
	/** why the last step failed, in words */
	error = $state<string | null>(null);
	/** set when the result moved between preview and confirm */
	conflict = $state<string | null>(null);

	/** the opt-in: also tag the marked rows that are still shown */
	includeMarked = $state(false);
	/** what a write that left the dialog open did, in words (partial failure) */
	report = $state.raw<string[]>([]);

	/** Marked rows in the list now (explained in the dialog). */
	get marked(): readonly Entry[] {
		return this.#host.markedRows();
	}
	/** The marked rows the chosen tag would still change. */
	get extraRows(): Entry[] {
		return this.tag ? eligibleMarkedRows(this.marked, this.tag.id) : [];
	}
	/** How many marked rows the confirm would add: 0 unless opted in. */
	get extraCount(): number {
		return this.includeMarked ? this.extraRows.length : 0;
	}

	/** Confirm is possible only on a loaded preview that would tag something (or opted-in rows). */
	readonly canConfirm = $derived(
		this.status === 'idle' &&
			this.preview !== null &&
			(this.preview.newly_tagged > 0 || this.extraCount > 0)
	);

	#filter: LedgerFilterState | null = null;
	#generation = 0;

	constructor(host: TagAllHost) {
		this.#host = host;
	}

	/** Open the dialog on the filter the list shows now. */
	start(): void {
		this.#reset();
		this.#filter = this.#host.filter();
		this.open = true;
	}

	close(): void {
		this.#reset();
		this.open = false;
	}

	/** Back to the choice of tag. */
	back(): void {
		if (this.status === 'applying') return;
		this.#reset();
		this.#filter = this.#host.filter();
	}

	/** The tag is chosen: preview what it would do. */
	async choose(tag: Tag): Promise<void> {
		this.tag = tag;
		this.conflict = null;
		this.report = [];
		await this.#preview();
	}

	/** Create a tag in place, then choose it. */
	async create(name: string): Promise<void> {
		const generation = ++this.#generation;
		this.status = 'creating';
		this.error = null;
		let tag: Tag;
		try {
			tag = (await createTag(name)).tag;
		} catch (error) {
			if (generation !== this.#generation) return;
			const failure = asApiError(error);
			this.error = describeTagError(failure, 'bulk', name);
			this.status = 'idle';
			await this.#host.recover(failure, 'bulk');
			return;
		}
		this.#host.addTag(tag);
		if (generation !== this.#generation) return;
		await this.choose(tag);
	}

	/** Preview again after a failure. */
	async retry(): Promise<void> {
		await this.#preview();
	}

	/**
	 * Write it: the filter's entries first (with the previewed count as the guard), then, if opted
	 * in, the marked rows one by one. A moved result stops everything and previews again.
	 */
	async confirm(): Promise<void> {
		const { tag, preview } = this;
		const filter = this.#filter;
		if (!this.canConfirm || !tag || !preview || !filter) return;
		const locale = this.#host.locale();
		const expected = preview.newly_tagged;
		const extras = this.includeMarked ? this.extraRows : [];
		this.status = 'applying';
		this.error = null;
		this.conflict = null;
		this.report = [];
		const updates: EntryTagIds[] = [];
		let applied = 0;
		let stale = false;
		if (expected > 0) {
			try {
				const out = await applyTag(tag.id, applyBody(filter, { expectedCount: expected }));
				applied = out.newly_tagged;
				updates.push(...out.entries);
				stale = Boolean(out.settle?.error);
			} catch (error) {
				await this.#bulkFailed(asApiError(error), expected);
				return;
			}
		}
		if (extras.length === 0) {
			this.#host.applied(updates, taggedNotice(tag.name, applied, 0, stale, locale));
			this.close();
			return;
		}
		const failures: ApiError[] = [];
		const queue = [...extras];
		const worker = async () => {
			for (let row = queue.shift(); row; row = queue.shift()) {
				try {
					const out = await tagEntry(row.id, tag.id);
					updates.push({ id: row.id, tag_ids: out.entry.tag_ids });
					stale ||= Boolean(out.settle.error);
				} catch (error) {
					failures.push(asApiError(error));
				}
			}
		};
		await Promise.all(Array.from({ length: Math.min(EXTRAS_CONCURRENCY, extras.length) }, worker));
		if (failures.length === 0) {
			this.#host.applied(updates, taggedNotice(tag.name, applied, extras.length, stale, locale));
			this.close();
			return;
		}
		this.#host.patch(updates);
		const lines: string[] = [];
		if (applied > 0) lines.push(taggedSummary(tag.name, applied, 0, locale));
		const reasons = failures.map((f) => describeTagError(f, 'entry'));
		for (const f of distinctTagErrors(failures)) void this.#host.recover(f, 'entry');
		const tagged = extras.length - failures.length;
		lines.push(partialReport(tagged, extras.length, reasons, locale));
		if (stale) lines.push(SETTLE_STALE);
		this.includeMarked = false;
		await this.#preview();
		if (this.open) this.report = lines;
	}

	async #bulkFailed(failure: ApiError, expected: number): Promise<void> {
		const reason = (failure.details as { reason?: unknown } | null)?.reason;
		if (failure.code === 'conflict' && reason === 'filter_result_changed') {
			const details = failure.details as { expected?: unknown; actual?: unknown };
			await this.#preview();
			const now = typeof details.actual === 'number' ? details.actual : this.preview?.newly_tagged;
			const was = typeof details.expected === 'number' ? details.expected : expected;
			const locale = this.#host.locale();
			this.conflict =
				now === undefined
					? 'The result changed — please check and confirm again'
					: `The result changed (was ${formatCount(was, locale)}, now ${formatCount(now, locale)}) — please check and confirm again`;
			return;
		}
		await this.#failed(failure);
	}

	/** A failed step: say it by its code, refetch what moved; a vanished tag reopens the chooser. */
	async #failed(failure: ApiError): Promise<void> {
		const text = describeTagError(failure, 'bulk');
		const gone = failure.code === 'not_found';
		if (gone) {
			this.#reset();
			this.#filter = this.#host.filter();
		}
		this.error = text;
		this.status = 'idle';
		await this.#host.recover(failure, 'bulk');
	}

	async #preview(): Promise<void> {
		const { tag } = this;
		const filter = this.#filter;
		if (!tag || !filter) return;
		const generation = ++this.#generation;
		this.status = 'previewing';
		this.error = null;
		this.preview = null;
		try {
			const out = await applyTag(tag.id, applyBody(filter, { dryRun: true }));
			if (generation !== this.#generation) return;
			this.preview = out;
		} catch (error) {
			if (generation !== this.#generation) return;
			await this.#failed(asApiError(error));
			return;
		}
		this.status = 'idle';
	}

	#reset(): void {
		this.#generation++;
		this.#filter = null;
		this.tag = null;
		this.preview = null;
		this.status = 'idle';
		this.error = null;
		this.conflict = null;
		this.includeMarked = false;
		this.report = [];
	}
}
