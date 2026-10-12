// The "Tag all N…" flow (decisions C6/C7, B13–B15): choose a tag, PREVIEW what it would do for the
// list's filter, confirm with the previewed count. The filter is captured when the dialog opens,
// so the preview and the write always speak about the same selection. Page-scoped, like the
// ledger store; the host patches what comes back into the list.

import { ApiError, applyBody, applyTag, createTag } from '#lib/api/index.js';
import { formatCount } from '#lib/format/index.js';
import { describeTagError, SETTLE_STALE } from '#lib/ledger/errors.js';
import type { LedgerFilterState } from '#lib/ledger/filter.js';
import type { EntryTagIds, Tag, TagApplyOut } from '#lib/types/domain.js';

export type TagAllHost = {
	filter: () => LedgerFilterState;
	locale: () => string;
	/** a tag was created in the dialog */
	addTag: (tag: Tag) => void;
	/** the write succeeded: patch these entries and say it */
	applied: (updates: readonly EntryTagIds[], notice: string) => void;
};

export type TagAllStatus = 'idle' | 'previewing' | 'applying' | 'creating';

function asApiError(error: unknown): ApiError {
	return error instanceof ApiError
		? error
		: new ApiError(0, 'network_error', 'The server could not be reached.');
}

export class TagAllFlow {
	open = $state(false);
	tag = $state.raw<Tag | null>(null);
	preview = $state.raw<TagApplyOut | null>(null);
	status = $state<TagAllStatus>('idle');
	/** why the last step failed, in words */
	error = $state<string | null>(null);
	/** set when the result moved between preview and confirm */
	conflict = $state<string | null>(null);

	/** Confirm is possible only on a loaded preview that would tag something. */
	readonly canConfirm = $derived(
		this.status === 'idle' && this.preview !== null && this.preview.newly_tagged > 0
	);

	readonly #host: TagAllHost;
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
			this.error = describeTagError(asApiError(error));
			this.status = 'idle';
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

	/** Write it, with the previewed count as the guard. */
	async confirm(): Promise<void> {
		const { tag, preview } = this;
		const filter = this.#filter;
		if (!this.canConfirm || !tag || !preview || !filter) return;
		const expected = preview.newly_tagged;
		this.status = 'applying';
		this.error = null;
		this.conflict = null;
		try {
			const out = await applyTag(tag.id, applyBody(filter, { expectedCount: expected }));
			const n = out.newly_tagged;
			const stale = out.settle?.error ? ` ${SETTLE_STALE}` : '';
			this.#host.applied(
				out.entries,
				`Tagged ${formatCount(n, this.#host.locale())} ${n === 1 ? 'entry' : 'entries'} with "${tag.name}"${stale ? `.${stale}` : ''}`
			);
			this.close();
		} catch (error) {
			const failure = asApiError(error);
			const reason = (failure.details as { reason?: unknown } | null)?.reason;
			if (failure.code === 'conflict' && reason === 'filter_result_changed') {
				const details = failure.details as { expected?: unknown; actual?: unknown };
				await this.#preview();
				const now =
					typeof details.actual === 'number' ? details.actual : this.preview?.newly_tagged;
				const was = typeof details.expected === 'number' ? details.expected : expected;
				this.conflict =
					now === undefined
						? 'The result changed — please check and confirm again'
						: `The result changed (was ${formatCount(was, this.#host.locale())}, now ${formatCount(now, this.#host.locale())}) — please check and confirm again`;
				return;
			}
			this.error = describeTagError(failure);
			this.status = 'idle';
		}
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
			this.error = describeTagError(asApiError(error));
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
	}
}
