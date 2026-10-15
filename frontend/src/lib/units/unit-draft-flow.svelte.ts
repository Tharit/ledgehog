// The editing of one unit in the work panel: the draft, its live preview and its commit
// (patterns §5, §6, §8; architecture §4.1, §6.3). The client holds the draft; the server says what
// it implies. A preview is requested after every change (debounced for typing, at once for a
// pick), the latest one wins and a stale answer is discarded; a commit is possible only on a
// preview that matches the draft and lists no problem. Every failure is routed by its code, and a
// draft is never thrown away by one. Page-independent: the panel hands over what a commit's
// outcome needs (patching the list, moving on) as a host.

import { ApiError, commitUnit, createTag, getUnit, previewUnit } from '#lib/api/index.js';
import { describeTagError } from '#lib/ledger/errors.js';
import type { Entry, Tag } from '#lib/types/domain.js';
import {
	allocationMessage,
	Draft,
	parseAllocation,
	type FieldName,
	type FieldValue,
	type ShownBasis
} from './draft.js';
import { describeProblem, differenceOf, problemSentence, type ProblemText } from './problems.js';
import { effectiveChanged } from './view.js';
import type { Affected, Unit, UnitCommit, UnitPreview, UnitProblem } from './types.js';

/** how long typing rests before the preview is asked for */
export const PREVIEW_DELAY_MS = 250;

export type FlowHost = {
	locale: () => string;
	/** the unit was read again (after something moved): show this one */
	unitChanged: (unit: Unit) => void;
	/** what a write touched: patch the list the panel was opened from */
	patch: (affected: Affected) => void;
	/** a category, payee or account vanished: the shared lists are loaded again */
	reloadLookups: () => Promise<void>;
	/** a tag was created from the panel: it joins the shared lists */
	addTag: (tag: Tag) => void;
	/** a preview arrived (the panel loads what it names, like the rules' names) */
	previewed?: (preview: UnitPreview) => void;
	/** the commit worked: move on (advance to the next unit, or close) */
	committed: (out: UnitCommit, anchorId: number) => void;
};

export type PreviewStatus = 'idle' | 'loading' | 'ready' | 'error';

/** A line the panel shows about what just happened, with the action that goes with it. */
export type FlowNotice = {
	kind: 'conflict' | 'error';
	text: string;
	action?: { label: string; run: () => void };
};

function asApiError(error: unknown): ApiError {
	return error instanceof ApiError
		? error
		: new ApiError(0, 'network_error', 'The server could not be reached.');
}

/** The commit's outcome as what the lists patch (patterns §7). */
export function affectedOf(out: UnitCommit, anchorId: number): Affected {
	// every unit of the response was committed (muted); only a confirmed one also gets the check
	const resolved = out.units.flatMap((u) => u.entry_ids);
	const confirmed = out.units.filter((u) => u.state.confirmed).flatMap((u) => u.entry_ids);
	const returned = out.consequences
		.filter(
			(c) => c.kind === 'returns_to_review' || c.kind === 'left_behind' || c.kind === 'unpaired'
		)
		.map((c) => c.entry_id);
	return {
		entries: out.entries,
		resolved,
		confirmed,
		returned_to_review: returned,
		removed_entry_ids: out.removed_entry_ids,
		created: Object.values(out.created),
		anchor_entry_id: anchorId
	};
}

const STALE_FIELD: Readonly<Record<string, Exclude<FieldName, 'type'>>> = {
	category_id: 'category',
	payee_id: 'payee',
	counter_account_id: 'counter_account',
	category: 'category',
	payee: 'payee',
	counter_account: 'counter_account'
};

/** Does a stale reference name a tag (its entity, or a field like `entries[0].tags.add`)? */
function isTagReference(entity: string | undefined, field: string | undefined): boolean {
	return entity === 'tag' || /(^|\.)tags(\.|$)|^tag_id$/.test(field ?? '');
}

const STALE_WORD: Readonly<Record<string, string>> = {
	category: 'category',
	payee: 'payee',
	counter_account: 'account'
};

export class UnitDraftFlow {
	readonly #host: FlowHost;

	unit = $state.raw<Unit | null>(null);
	draft = $state.raw<Draft | null>(null);
	preview = $state.raw<UnitPreview | null>(null);
	previewStatus = $state<PreviewStatus>('idle');
	previewError = $state.raw<ApiError | null>(null);
	/** the draft changed and the preview shown is not its own yet */
	stale = $state(false);
	committing = $state(false);
	notice = $state.raw<FlowNotice | null>(null);
	/** the problems a refused commit named (until the next preview) */
	commitProblems = $state.raw<readonly UnitProblem[]>([]);
	/** what the user typed as the amount of each split row, and why it is not an amount */
	amountTexts = $state.raw<Readonly<Record<number, string>>>({});
	amountErrors = $state.raw<Readonly<Record<number, string>>>({});
	/** the split row added last: the panel puts focus in its amount */
	lastAddedSplit = $state<number | null>(null);
	/** a tag is being created for the picker: it offers nothing meanwhile */
	tagBusy = $state(false);

	#timer: ReturnType<typeof setTimeout> | null = null;
	#generation = 0;
	/** counts the units begun and the panels closed: what an answer is still for */
	#epoch = 0;
	#controller: AbortController | null = null;

	constructor(host: FlowHost) {
		this.#host = host;
	}

	/**
	 * Does the draft change anything? A field edit counts only when the preview says it ends in
	 * another value than the stored one (an X that lets a rule propose the stored category again is
	 * no change); while the preview is not the draft's own, an edit counts.
	 */
	get isDirty(): boolean {
		const draft = this.draft;
		if (!draft) return false;
		if (draft.hasOtherChanges) return true;
		const preview = !this.stale ? this.preview : null;
		return draft.fieldEdits().some(({ id, field }) => {
			const row = preview?.rows.find((r) => r.id === id && r.in_unit) ?? null;
			const stored = this.unit?.entries.find((e) => e.id === id) ?? null;
			return effectiveChanged(field, row, stored) !== false;
		});
	}

	/** The problems that would refuse the commit: a refused commit's, else the last preview's. */
	get problems(): readonly UnitProblem[] {
		return this.commitProblems.length > 0 ? this.commitProblems : (this.preview?.problems ?? []);
	}

	/** Each problem in words. */
	get problemTexts(): { problem: UnitProblem; text: ProblemText }[] {
		return this.problems.map((problem) => ({
			problem,
			text: describeProblem(problem, {
				locale: this.#host.locale(),
				currency: (entryId) => this.#currency(entryId)
			})
		}));
	}

	/** Why Commit cannot be pressed, or null when it can. A commit with no change is valid. */
	get commitReason(): string | null {
		if (!this.unit || !this.draft) return 'The unit is still loading.';
		if (this.committing) return 'The commit is under way.';
		if (Object.keys(this.amountErrors).length > 0) return 'An amount is not valid.';
		if (this.draft.pendingSplits.length > 0) return 'Enter the amount of the new split.';
		if (this.previewStatus === 'error') return 'The preview could not be loaded.';
		if (this.stale || this.previewStatus !== 'ready') return 'Checking what would change…';
		const problems = this.problemTexts;
		if (problems.length === 1) return problemSentence(problems[0].text);
		if (problems.length > 1) return `${problems.length} problems to resolve.`;
		return null;
	}

	/** A unit was loaded: an empty draft over it, previewed at once (proposals are fresh on open). */
	begin(unit: Unit): void {
		this.#stop();
		this.#epoch++;
		this.unit = unit;
		this.draft = Draft.of(unit);
		this.preview = null;
		this.previewError = null;
		this.notice = null;
		this.commitProblems = [];
		this.amountTexts = {};
		this.amountErrors = {};
		this.lastAddedSplit = null;
		this.tagBusy = false;
		this.committing = false;
		this.#request();
	}

	/** The panel closed or moved on: nothing may land here any more. */
	reset(): void {
		this.#stop();
		this.#epoch++;
		this.unit = null;
		this.draft = null;
		this.preview = null;
		this.previewStatus = 'idle';
		this.previewError = null;
		this.stale = false;
		this.committing = false;
		this.notice = null;
		this.commitProblems = [];
		this.amountTexts = {};
		this.amountErrors = {};
		this.lastAddedSplit = null;
		this.tagBusy = false;
	}

	/** Reset: throw every change away (the panel stays open): the unit as stored, previewed again. */
	discard(): void {
		if (this.unit) this.begin(this.unit);
	}

	#stop(): void {
		if (this.#timer !== null) clearTimeout(this.#timer);
		this.#timer = null;
		this.#generation++;
		this.#controller?.abort();
		this.#controller = null;
	}

	// ---- editing -------------------------------------------------------------------------

	/** Change the draft; the preview follows (`immediate` for a pick, debounced for typing). */
	edit(change: (draft: Draft) => Draft, immediate = true): void {
		const draft = this.draft;
		if (!draft || this.committing) return;
		const next = change(draft);
		if (next === draft) return;
		this.draft = next;
		this.notice = this.notice?.kind === 'conflict' ? this.notice : null;
		this.commitProblems = [];
		this.#schedule(immediate);
	}

	setField(id: number, field: FieldName, value: FieldValue, shown: ShownBasis | null = null): void {
		this.edit((d) => d.setField(id, field, value, shown));
	}

	/** The X of a field: no payee (the user's decision), or the passes propose again. */
	clearField(id: number, field: FieldName): void {
		this.edit((d) => d.clearField(id, field));
	}

	resetField(id: number, field: FieldName): void {
		this.edit((d) => d.resetField(id, field));
	}

	/** "Reset to proposal": the user's value is dropped, the stored one is shown again. */
	revertField(id: number, field: FieldName): void {
		this.edit((d) => d.revertField(id, field));
	}

	setText(id: number, key: 'description' | 'note', text: string): void {
		this.edit(
			(d) => (key === 'description' ? d.setDescription(id, text) : d.setNote(id, text)),
			false
		);
	}

	/** The type buttons: the entry becomes what was clicked (a transfer's destination is chosen next). */
	setType(id: number, type: 'flow' | 'transfer'): void {
		this.edit((d) => (type === 'flow' ? d.convertToFlow(id) : d.convertToTransfer(id, null)));
	}

	/** `x`: a transfer becomes a flow, anything else (a flow, an entry with no type yet) a transfer. */
	convert(id: number, currentType: string | null): void {
		this.setType(id, currentType === 'transfer' ? 'flow' : 'transfer');
	}

	/** Put a tag on the entry or take it off (applied with the commit, like every other choice). */
	toggleTag(id: number, tagId: number): void {
		this.edit((d) => d.toggleTag(id, tagId));
	}

	/**
	 * Create a tag from the picker at once (a tag is no part of the draft; cancelling leaves it)
	 * and put it on the entry. True when both worked.
	 */
	async createTag(id: number, name: string): Promise<boolean> {
		const draft = this.draft;
		if (!draft || this.committing || this.tagBusy) return false;
		const epoch = this.#epoch;
		this.tagBusy = true;
		this.notice = null;
		let tag: Tag;
		try {
			tag = (await createTag(name)).tag;
		} catch (error) {
			if (epoch !== this.#epoch) return false;
			this.tagBusy = false;
			const failure = asApiError(error);
			// a name that is taken: the list the picker shows was out of date
			if (failure.code === 'conflict') void this.#host.reloadLookups();
			this.notice = { kind: 'error', text: describeTagError(failure, 'entry', name) };
			return false;
		}
		this.#host.addTag(tag);
		if (epoch !== this.#epoch) return false; // the panel moved on; the tag stays
		this.tagBusy = false;
		this.toggleTag(id, tag.id);
		return true;
	}

	reresolve(on = true): void {
		this.edit((d) => d.reresolve(on));
	}

	/** Add a split row to the source of a stored entry; its amount is typed next. */
	addSplit(sourceEntryId: number): number | null {
		const draft = this.draft;
		if (!draft || this.committing) return null;
		const id = draft.nextTempId;
		this.edit((d) => d.addSplit(sourceEntryId), false);
		this.lastAddedSplit = id;
		return id;
	}

	removeSplit(id: number): void {
		this.#forgetAmount(id);
		this.edit((d) => d.removeSplit(id));
	}

	restoreSplit(id: number): void {
		this.edit((d) => d.restoreSplit(id));
	}

	/** The remedy of an unequal pair (spec §5.7): split the difference off the larger leg. */
	splitOffDifference(problem: UnitProblem): void {
		const difference = differenceOf(problem);
		const preview = this.preview;
		if (difference === null || !preview || problem.entry_id === null) return;
		const partner = problem.detail.partner;
		const legs = preview.rows.filter((r) => r.id === problem.entry_id || r.id === partner);
		if (legs.length !== 2) return;
		const larger = legs.reduce((a, b) =>
			Math.abs(b.amount.amount) > Math.abs(a.amount.amount) ? b : a
		);
		const sourceEntry = this.#storedOfSource(larger.source_transaction_id);
		if (!sourceEntry) return;
		const id = this.addSplit(sourceEntry.id);
		if (id === null) return;
		const minor = difference * (larger.amount.amount < 0 ? -1 : 1);
		this.edit((d) => d.setSplitAmount(id, minor));
	}

	#storedOfSource(sourceId: number): Entry | undefined {
		return this.unit?.entries.find((e) => e.source_transaction_id === sourceId);
	}

	/** What the user typed as the amount of a row, parsed: the sign is the split entry's own. */
	setAmountText(id: number, text: string): void {
		const unit = this.unit;
		const draft = this.draft;
		if (!unit || !draft) return;
		const split = draft.splits.find((s) => s.id === id);
		const source = unit.entries.find((e) => e.id === (split ? split.sourceEntryId : id));
		if (!source) return;
		this.amountTexts = { ...this.amountTexts, [id]: text };
		const parsed = parseAllocation(
			text,
			source.amount.currency,
			this.#host.locale(),
			source.amount.amount
		);
		if (parsed.ok) {
			this.amountErrors = omitKey(this.amountErrors, id);
			this.edit((d) => d.setSplitAmount(id, parsed.minor), false);
			return;
		}
		// a new split with nothing typed is only waiting for its amount; anything else is wrong
		this.amountErrors =
			parsed.error === 'empty' && split
				? omitKey(this.amountErrors, id)
				: { ...this.amountErrors, [id]: allocationMessage(parsed.error) };
		if (split) this.edit((d) => d.setSplitAmount(id, null), false);
	}

	#forgetAmount(id: number): void {
		this.amountTexts = omitKey(this.amountTexts, id);
		this.amountErrors = omitKey(this.amountErrors, id);
	}

	// ---- the preview ---------------------------------------------------------------------

	#schedule(immediate: boolean): void {
		this.stale = true;
		this.previewStatus = 'loading';
		this.#generation++;
		this.#controller?.abort();
		if (this.#timer !== null) clearTimeout(this.#timer);
		this.#timer = null;
		if (immediate) this.#request();
		else this.#timer = setTimeout(() => this.#request(), PREVIEW_DELAY_MS);
	}

	/** Ask for the preview of the draft as it is now; the latest request wins. */
	#request(): void {
		const draft = this.draft;
		if (!draft) return;
		if (this.#timer !== null) clearTimeout(this.#timer);
		this.#timer = null;
		this.#controller?.abort();
		const controller = new AbortController();
		this.#controller = controller;
		const generation = ++this.#generation;
		this.previewStatus = 'loading';
		this.stale = true;
		previewUnit(draft.toRequest(), controller.signal).then(
			(preview) => {
				if (generation !== this.#generation) return; // a newer request owns the screen
				this.preview = preview;
				this.previewStatus = 'ready';
				this.previewError = null;
				this.stale = false;
				this.commitProblems = [];
				this.#host.previewed?.(preview);
				this.#afterPreview(preview);
			},
			(error) => {
				if (generation !== this.#generation) return;
				this.previewError = asApiError(error);
				this.previewStatus = 'error';
			}
		);
	}

	/** Retry a preview that failed. */
	retryPreview(): void {
		this.#schedule(true);
	}

	/** A pick the lists no longer hold: they are loaded again and the pick forgotten. */
	#afterPreview(preview: UnitPreview): void {
		const gone = preview.problems.filter((p) => p.code === 'stale_reference');
		if (gone.length === 0) return;
		void this.#host.reloadLookups();
		let next = this.draft;
		for (const problem of gone) {
			const field = problem.field ? STALE_FIELD[problem.field] : undefined;
			const id = problem.detail.id;
			if (next && typeof id === 'number') {
				if (isTagReference(undefined, problem.field ?? undefined)) next = next.dropTag(id);
				else if (field) next = next.dropReference(field, id);
			}
		}
		if (next && next !== this.draft) {
			this.draft = next;
			this.notice = {
				kind: 'conflict',
				text: 'Something you chose no longer exists. The lists were reloaded: choose again.'
			};
			this.#schedule(true);
		}
	}

	// ---- the commit ----------------------------------------------------------------------

	async commit(): Promise<void> {
		const draft = this.draft;
		const preview = this.preview;
		if (!draft || !preview || this.commitReason !== null) return;
		const request = draft.toRequest(preview.versions);
		this.committing = true;
		this.notice = null;
		let out: UnitCommit;
		try {
			out = await commitUnit(request);
		} catch (error) {
			this.committing = false;
			await this.#failed(asApiError(error));
			return;
		}
		// still "committing" until the panel moves on (begin or reset): the unit is spoken for
		const anchorId = request.anchor_entry_id;
		this.#stop();
		this.#host.patch(affectedOf(out, anchorId));
		this.#host.committed(out, anchorId);
	}

	async #failed(error: ApiError): Promise<void> {
		switch (error.code) {
			case 'conflict':
				await this.#moved(
					'Someone changed this unit while you were editing. Your changes are kept: the preview shows what a commit does now.'
				);
				return;
			case 'unit_moved':
				await this.#moved(
					'This unit changed shape while you were editing. Your changes are kept where they still apply.'
				);
				return;
			case 'stale_reference':
				this.#staleReference(error);
				return;
			case 'try_again':
				this.notice = {
					kind: 'error',
					text: 'The commit was interrupted before it wrote anything. Your changes are kept.',
					action: { label: 'Try again', run: () => void this.commit() }
				};
				return;
			case 'not_found':
				this.notice = { kind: 'error', text: 'This unit no longer exists.' };
				return;
			case 'invalid_draft':
				this.notice = {
					kind: 'error',
					text: 'This change cannot be committed as it stands. Review the amounts and values.'
				};
				return;
			default: {
				const problems = problemsOf(error);
				if (error.status === 422 && problems.length > 0) {
					this.commitProblems = problems;
					this.#schedule(true);
					return;
				}
				this.notice = {
					kind: 'error',
					text: 'The commit did not go through. Nothing was written; your changes are kept.',
					action: { label: 'Try again', run: () => void this.commit() }
				};
			}
		}
	}

	/** The unit moved under the draft: read it again, keep what still applies, preview anew. */
	async #moved(text: string): Promise<void> {
		const draft = this.draft;
		if (!draft) return;
		try {
			const unit = await getUnit(draft.anchorId);
			if (this.draft !== draft) return;
			this.unit = unit;
			this.draft = draft.rebase(unit);
			this.#host.unitChanged(unit);
			this.#host.patch({ entries: unit.entries });
			this.notice = {
				kind: 'conflict',
				text,
				action: { label: 'Reload', run: () => this.discard() }
			};
			this.#schedule(true);
		} catch (error) {
			const failure = asApiError(error);
			this.notice = {
				kind: 'error',
				text:
					failure.code === 'not_found'
						? 'This unit no longer exists.'
						: 'The unit could not be read again. Try again in a moment.',
				action:
					failure.code === 'not_found'
						? undefined
						: { label: 'Try again', run: () => void this.#moved(text) }
			};
		}
	}

	#staleReference(error: ApiError): void {
		const details = (error.details ?? {}) as { field?: string; entity?: string; id?: number };
		const tag = isTagReference(details.entity, details.field);
		const field = STALE_FIELD[details.entity ?? ''] ?? STALE_FIELD[details.field ?? ''];
		void this.#host.reloadLookups();
		if ((tag || field) && typeof details.id === 'number' && this.draft) {
			const next = tag
				? this.draft.dropTag(details.id)
				: this.draft.dropReference(field!, details.id);
			if (next !== this.draft) this.draft = next;
		}
		const word = tag ? 'tag' : field ? STALE_WORD[field] : 'value';
		this.notice = {
			kind: 'conflict',
			text: `The ${word} you chose no longer exists. The lists were reloaded: choose again.`
		};
		this.#schedule(true);
	}

	#currency(entryId: number | null): string {
		const row = this.preview?.rows.find((r) => r.id === entryId);
		return (
			row?.amount.currency ??
			this.unit?.entries.find((e) => e.id === entryId)?.amount.currency ??
			this.unit?.entries[0]?.amount.currency ??
			'EUR'
		);
	}
}

function omitKey<V>(record: Readonly<Record<number, V>>, id: number): Record<number, V> {
	const copy = { ...record };
	delete copy[id];
	return copy;
}

function problemsOf(error: ApiError): UnitProblem[] {
	const details = error.details as { problems?: unknown } | null;
	return Array.isArray(details?.problems) ? (details.problems as UnitProblem[]) : [];
}
