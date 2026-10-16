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
	parseReceivedAmount,
	type FieldName,
	type FieldValue,
	type ShownBasis
} from './draft.js';
import {
	describeProblem,
	differenceOf,
	problemSentence,
	suggestedSplitOf,
	type ProblemText
} from './problems.js';
import { effectiveChanged } from './view.js';
import type {
	Affected,
	SuggestedSplit,
	Unit,
	UnitCommit,
	UnitPreview,
	UnitProblem
} from './types.js';

/** The windows "Load more candidates" steps through (days), after the matching window of the server. */
export const WINDOW_STEPS = [30, 90] as const;

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
	/** an account's currency (the problem texts name the counter-leg's) */
	accountCurrency?: (accountId: number) => string | undefined;
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

const DOCUMENT_TAKEN_TEXT =
	'The document you picked is now carried by another transaction. It is no longer picked: choose another.';
const DOCUMENT_CHANGED_TEXT =
	'The document you picked changed after you saw it. It is no longer picked: pick it again.';

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

/** Does a stale reference name a document (its entity, or the field `document_id`)? */
function isDocumentReference(entity: string | undefined, field: string | undefined): boolean {
	return entity === 'document' || field === 'document_id' || field === 'document';
}

/** The document a problem or a refusal names: `document_id`, else `id`; null when it names none. */
function documentIdOf(detail: Readonly<Record<string, unknown>> | null | undefined): number | null {
	const named = detail?.document_id ?? detail?.id;
	return typeof named === 'number' ? named : null;
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
	/** what the user typed as the amount a counter-leg receives (by the leg's entry id), and why it is not one */
	receivedTexts = $state.raw<Readonly<Record<number, string>>>({});
	receivedErrors = $state.raw<Readonly<Record<number, string>>>({});
	/** the split row added last: the panel puts focus in its amount */
	lastAddedSplit = $state<number | null>(null);
	/** a tag is being created for the picker: it offers nothing meanwhile */
	tagBusy = $state(false);
	/** the window (days) the offers of the preview shown were listed for; null: the server's own */
	previewWindow = $state<number | null>(null);

	#timer: ReturnType<typeof setTimeout> | null = null;
	#generation = 0;
	/** counts the units begun and the panels closed: what an answer is still for */
	#epoch = 0;
	#controller: AbortController | null = null;
	/**
	 * The widened window of the next preview. It applies to the next request only, except while the
	 * draft holds a pick: the server validates the pick against the window, so a pick made from a
	 * widened list keeps the window it was offered in.
	 */
	#window: number | null = null;
	/** the pick just made: its preview may suggest the fee split (applied once, never again) */
	#feePending = false;

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
				windowDays: this.previewWindow,
				currency: (entryId) => this.#currency(entryId),
				counterCurrency: (entryId) => this.#counterCurrency(entryId)
			})
		}));
	}

	/** Why Commit cannot be pressed, or null when it can. A commit with no change is valid. */
	get commitReason(): string | null {
		if (!this.unit || !this.draft) return 'The unit is still loading.';
		if (this.committing) return 'The commit is under way.';
		if (Object.keys(this.amountErrors).length > 0 || Object.keys(this.receivedErrors).length > 0)
			return 'An amount is not valid.';
		if (this.draft.pendingSplits.length > 0) return 'Enter the amount of the new split.';
		if (this.previewStatus === 'error') return 'The preview could not be loaded.';
		if (this.stale || this.previewStatus !== 'ready') return 'Checking what would change…';
		const problems = this.problemTexts;
		if (problems.length === 1) return problemSentence(problems[0].text);
		if (problems.length > 1) return `${problems.length} problems to resolve.`;
		return null;
	}

	/**
	 * A unit was loaded: an empty draft over it, previewed at once (proposals are fresh on open).
	 * `document` is a document already picked in the draft (opened from the Documents pages): it is
	 * the pick of the transaction of `entryId`.
	 */
	begin(unit: Unit, document?: { entryId: number; id: number; version: number }): void {
		this.#stop();
		this.#epoch++;
		this.unit = unit;
		const empty = Draft.of(unit);
		this.draft = document
			? empty.pickDocument(originalOf(unit, document.entryId), document.id, document.version)
			: empty;
		this.preview = null;
		this.previewError = null;
		this.notice = null;
		this.commitProblems = [];
		this.amountTexts = {};
		this.amountErrors = {};
		this.receivedTexts = {};
		this.receivedErrors = {};
		this.lastAddedSplit = null;
		this.tagBusy = false;
		this.committing = false;
		this.#window = null;
		this.#feePending = false;
		this.previewWindow = null;
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
		this.receivedTexts = {};
		this.receivedErrors = {};
		this.lastAddedSplit = null;
		this.tagBusy = false;
		this.#window = null;
		this.#feePending = false;
		this.previewWindow = null;
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
		this.#pruneReceived(next);
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

	// ---- the document of a transaction (spec §5.8, §6) -------------------------------------

	/** Pick a document for the transaction whose original entry is `id` (the version is the one seen). */
	pickDocument(id: number, document: { id: number; version: number }): void {
		this.edit((d) => d.pickDocument(id, document.id, document.version));
	}

	/** "None of these", "Commit without a document": the user decides there is no document. */
	noDocument(id: number): void {
		this.edit((d) => d.noDocument(id));
	}

	/** Drop the decision and the link: matching decides afresh. */
	reresolveDocument(id: number): void {
		this.edit((d) => d.reresolveDocument(id));
	}

	/** Back to what the server proposes for the document. */
	resetDocument(id: number): void {
		this.edit((d) => d.resetDocument(id));
	}

	/** The rows of the split along the lines are the proposal again. */
	resetSplit(id: number): void {
		this.#forgetAmounts(this.draft?.lineRows.map((s) => s.id) ?? []);
		this.edit((d) => d.resetSplit(id));
	}

	/** Split the transaction along the lines of a document (replacing an existing split). */
	splitAlongLines(id: number, document: { id: number; version: number }): void {
		this.#forgetAmounts(this.draft?.lineRows.map((s) => s.id) ?? []);
		this.edit((d) => d.splitAlongLines(id, document.id, document.version));
	}

	/** "Keep one entry": the proposed split along the lines is refused. */
	declineSplit(id: number): void {
		this.#forgetAmounts(this.draft?.lineRows.map((s) => s.id) ?? []);
		this.edit((d) => d.declineSplit(id));
	}

	// ---- the partner of a transfer leg (spec §5.7) ----------------------------------------

	/**
	 * Pick a partner for a transfer leg. The pick is a draft edit like any other: the preview says
	 * what it does. A pick from a widened list keeps that window; a fee the picked pair differs by
	 * is split off once, from the preview that follows.
	 */
	pickPartner(id: number, partnerEntryId: number): void {
		if (!this.draft || this.committing) return;
		this.#window = this.previewWindow;
		this.#feePending = true;
		this.edit((d) => d.pickPartner(id, partnerEntryId));
	}

	/**
	 * The other side of a leg is created by the commit (an unsynced counter-account): a draft edit
	 * with a client-issued temporary id, stable while the pick stands. A cross-currency leg gets
	 * its amount received next (`setReceivedAmountText`).
	 */
	pickCounterLeg(id: number): void {
		if (!this.draft || this.committing) return;
		this.edit((d) => d.pickCounterLeg(id));
	}

	/**
	 * What the user typed as the amount received: unsigned, in the counter-account's `currency`.
	 * Empty is no amount yet (the preview says it is required); anything else that is no amount is
	 * said at the field and blocks the commit.
	 */
	setReceivedAmountText(id: number, text: string, currency: string): void {
		const draft = this.draft;
		if (!draft || draft.pairingEdit(id)?.mode !== 'counter_leg') return;
		this.receivedTexts = { ...this.receivedTexts, [id]: text };
		const parsed = parseReceivedAmount(text, currency, this.#host.locale());
		if (parsed.ok) {
			this.receivedErrors = omitKey(this.receivedErrors, id);
			this.edit((d) => d.setReceivedAmount(id, parsed.minor), false);
			return;
		}
		this.receivedErrors =
			parsed.error === 'empty'
				? omitKey(this.receivedErrors, id)
				: { ...this.receivedErrors, [id]: allocationMessage(parsed.error) };
		this.edit((d) => d.setReceivedAmount(id, null), false);
	}

	/** What the typed amounts of a leg no longer stand for is forgotten with the pick. */
	#pruneReceived(draft: Draft): void {
		const gone = (id: string) => draft.pairingEdit(Number(id))?.mode !== 'counter_leg';
		const texts = Object.keys(this.receivedTexts).filter(gone);
		const errors = Object.keys(this.receivedErrors).filter(gone);
		if (texts.length > 0) {
			const copy = { ...this.receivedTexts };
			for (const id of texts) delete copy[Number(id)];
			this.receivedTexts = copy;
		}
		if (errors.length > 0) {
			const copy = { ...this.receivedErrors };
			for (const id of errors) delete copy[Number(id)];
			this.receivedErrors = copy;
		}
	}

	/** Pair the leg by the rules again. */
	reresolvePairing(id: number): void {
		this.edit((d) => d.reresolvePairing(id));
	}

	clearPairing(id: number): void {
		this.edit((d) => d.clearPairing(id));
	}

	/** The window "Load more candidates" asks for next, or null when it is as wide as it gets. */
	get nextWindow(): number | null {
		const current = this.previewWindow ?? 0;
		return WINDOW_STEPS.find((days) => days > current) ?? null;
	}

	/** Show the offers of a wider window (the next preview only, unless a pick keeps it). */
	widenWindow(): void {
		const days = this.nextWindow;
		if (days === null || !this.draft || this.committing) return;
		this.#window = days;
		this.#schedule(true);
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

	/**
	 * The remedy of an unequal pair (spec §5.7): split the difference off the larger leg: the leg
	 * the server suggests, else the one this draft finds.
	 */
	splitOffDifference(problem: UnitProblem): void {
		const suggested = suggestedSplitOf(problem);
		if (suggested) {
			this.#applySplit(suggested);
			return;
		}
		const difference = differenceOf(problem);
		const preview = this.preview;
		if (difference === null || !preview || problem.entry_id === null) return;
		const partner = problem.detail.partner;
		const legs = preview.rows.filter((r) => r.id === problem.entry_id || r.id === partner);
		if (legs.length !== 2) return;
		const larger = legs.reduce((a, b) =>
			Math.abs(b.amount.amount) > Math.abs(a.amount.amount) ? b : a
		);
		const sourceId =
			this.#storedOfSource(larger.source_transaction_id)?.id ??
			// the leg of a partner picked from outside the unit is no stored entry of it
			preview.rows.find(
				(r) => r.source_transaction_id === larger.source_transaction_id && r.original && r.id > 0
			)?.id;
		if (sourceId === undefined) return;
		this.#applySplit({ source_entry_id: sourceId, amount: difference });
	}

	/** A split of `amount` (its magnitude) off a stored entry; it takes the sign of that entry. */
	#applySplit(split: SuggestedSplit): void {
		const row = this.preview?.rows.find((r) => r.id === split.source_entry_id);
		const stored = this.unit?.entries.find((e) => e.id === split.source_entry_id);
		const negative = (row?.amount.amount ?? stored?.amount.amount ?? split.amount) < 0;
		const id = this.addSplit(split.source_entry_id);
		if (id === null) return;
		this.edit((d) => d.setSplitAmount(id, Math.abs(split.amount) * (negative ? -1 : 1)));
	}

	#storedOfSource(sourceId: number): Entry | undefined {
		return this.unit?.entries.find((e) => e.source_transaction_id === sourceId);
	}

	/**
	 * What the user is typing as the amount of a row: kept as text, and said at the field when it is
	 * no amount. The draft is not touched: it takes the amount when the field is left
	 * (`applyAmountText`), so a row never moves or goes while its amount is being typed.
	 */
	setAmountText(id: number, text: string): void {
		const parsed = this.#parseAmount(id, text);
		if (!parsed) return;
		this.amountTexts = { ...this.amountTexts, [id]: text };
		// a new split with nothing typed is only waiting for its amount; anything else is wrong
		const waiting =
			parsed.ok === false &&
			parsed.error === 'empty' &&
			(this.draft?.splits.some((s) => s.id === id) ?? false) &&
			this.draft?.edit(id).amount == null;
		this.amountErrors =
			parsed.ok || waiting
				? omitKey(this.amountErrors, id)
				: { ...this.amountErrors, [id]: allocationMessage(parsed.error) };
	}

	/**
	 * The field was left, or Enter pressed: a valid amount is taken into the draft and previewed.
	 * An amount that is none changes nothing in the draft: the row keeps its place and its last
	 * amount, and the field says what is wrong (`amountErrors`, which holds the commit back).
	 */
	applyAmountText(id: number): void {
		const text = this.amountTexts[id];
		if (text === undefined || this.committing) return;
		const parsed = this.#parseAmount(id, text);
		if (!parsed?.ok || this.draft?.edit(id).amount === parsed.minor) return;
		this.edit((d) => d.setSplitAmount(id, parsed.minor));
	}

	#parseAmount(id: number, text: string): ReturnType<typeof parseAllocation> | null {
		const unit = this.unit;
		const draft = this.draft;
		if (!unit || !draft) return null;
		const split = draft.splits.find((s) => s.id === id);
		const source = unit.entries.find((e) => e.id === (split ? split.sourceEntryId : id));
		if (!source) return null;
		return parseAllocation(text, source.amount.currency, this.#host.locale(), source.amount.amount);
	}

	#forgetAmounts(ids: readonly number[]): void {
		for (const id of ids) this.#forgetAmount(id);
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
		const windowDays = this.#window;
		// a widened window serves one request, unless a pick stands that was offered in it
		if (!draft.hasPick) this.#window = null;
		previewUnit(draft.toRequest(), controller.signal, windowDays).then(
			(preview) => {
				if (generation !== this.#generation) return; // a newer request owns the screen
				this.preview = preview;
				this.previewWindow = windowDays;
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

	/**
	 * The rows of the preview made from a line of the document (the proposed split along the lines)
	 * become the draft's own: from now on it echoes them, and the split is the client's (spec §6).
	 * Rows the server dropped (their document is no longer the transaction's) leave the draft. The
	 * preview shown already says what the draft will say, so nothing is previewed again.
	 */
	#takeOverSplit(preview: UnitPreview): void {
		const draft = this.draft;
		if (!draft || this.committing) return;
		const rows = preview.rows.flatMap((row) => {
			if (row.id >= 0 || !row.document_line) return [];
			const original = preview.rows.find(
				(r) => r.id > 0 && r.original && r.source_transaction_id === row.source_transaction_id
			);
			if (!original) return [];
			return [
				{
					id: row.id,
					sourceEntryId: original.id,
					amount: row.amount.amount,
					documentLine: {
						documentId: row.document_line.document_id,
						lineNo: row.document_line.line_no
					}
				}
			];
		});
		const next = draft.syncLineRows(rows);
		if (next !== draft) this.draft = next;
	}

	/**
	 * A pick the lists no longer hold: they are loaded again and the pick forgotten. A document
	 * that changed or was taken since the user saw it is no longer picked either.
	 */
	#afterPreview(preview: UnitPreview): void {
		this.#takeOverSplit(preview);
		const gone = preview.problems.filter((p) => p.code === 'stale_reference');
		const moved = preview.problems.filter(
			(p) => p.code === 'document_changed' || p.code === 'document_taken'
		);
		if (gone.length === 0 && moved.length === 0) {
			this.#suggestFee(preview);
			return;
		}
		if (gone.length > 0) void this.#host.reloadLookups();
		let next = this.draft;
		let notice: string | null = null;
		for (const problem of gone) {
			const field = problem.field ? STALE_FIELD[problem.field] : undefined;
			const id = problem.detail.id;
			if (isDocumentReference(undefined, problem.field ?? undefined)) {
				if (next) next = next.dropDocument(documentIdOf(problem.detail) ?? undefined);
				notice = 'The document you chose no longer exists. Choose again.';
			} else if (next && typeof id === 'number') {
				if (isTagReference(undefined, problem.field ?? undefined)) next = next.dropTag(id);
				else if (field) next = next.dropReference(field, id);
			}
		}
		for (const problem of moved) {
			if (next) next = next.dropDocument(documentIdOf(problem.detail) ?? undefined);
			notice = problem.code === 'document_taken' ? DOCUMENT_TAKEN_TEXT : DOCUMENT_CHANGED_TEXT;
		}
		if (next && next !== this.draft) {
			this.draft = next;
			this.notice = {
				kind: 'conflict',
				text:
					notice ?? 'Something you chose no longer exists. The lists were reloaded: choose again.'
			};
			this.#schedule(true);
		}
	}

	/**
	 * The preview right after a pick: when it says the pair differs by a fee, the fee is split off
	 * as a draft split, once per pick (the pick's guard is spent whatever the answer says).
	 */
	#suggestFee(preview: UnitPreview): void {
		if (!this.#feePending) return;
		this.#feePending = false;
		const suggested = preview.problems.map(suggestedSplitOf).find((s) => s !== null);
		if (!suggested || this.committing) return;
		this.#applySplit(suggested);
		// the amount is what the server suggested: nothing to type next
		this.lastAddedSplit = null;
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
			out = await commitUnit(request, undefined, this.previewWindow);
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
			case 'unit_moved': {
				const details = error.details as { reason?: string; document_id?: number } | null;
				// the document the user picked was taken, or changed: the unit is read again and the
				// pick is gone (a document is decided on what the user saw)
				if (details?.reason === 'taken' || details?.reason === 'version') {
					await this.#moved(
						details.reason === 'taken' ? DOCUMENT_TAKEN_TEXT : DOCUMENT_CHANGED_TEXT,
						{ dropDocument: details.document_id ?? null }
					);
					return;
				}
				await this.#moved(
					'This unit changed shape while you were editing. Your changes are kept where they still apply.'
				);
				return;
			}
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
			case 'invalid_draft': {
				const code = (error.details as { code?: string } | null)?.code;
				this.notice = {
					kind: 'error',
					text:
						code === 'pairing_not_transfer'
							? 'Only a transfer leg has a partner. Take the partner pick back, or make the entry a transfer.'
							: code === 'invalid_pairing'
								? 'The partner you picked cannot be used. Pick another partner.'
								: code === 'document_not_original'
									? 'A document belongs to the original entry of a transaction, not to a split entry.'
									: code === 'invalid_document'
										? 'The document you chose cannot be used as it stands. Choose again.'
										: 'This change cannot be committed as it stands. Review the amounts and values.'
				};
				return;
			}
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
	async #moved(text: string, options: { dropDocument?: number | null } = {}): Promise<void> {
		const draft = this.draft;
		if (!draft) return;
		try {
			const unit = await getUnit(draft.anchorId);
			if (this.draft !== draft) return;
			this.unit = unit;
			const rebased = draft.rebase(unit);
			this.draft =
				options.dropDocument === undefined
					? rebased
					: rebased.dropDocument(options.dropDocument ?? undefined);
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
						: { label: 'Try again', run: () => void this.#moved(text, options) }
			};
		}
	}

	#staleReference(error: ApiError): void {
		const details = (error.details ?? {}) as {
			field?: string;
			entity?: string;
			id?: number;
			document_id?: number;
		};
		if (isDocumentReference(details.entity, details.field)) {
			void this.#host.reloadLookups();
			if (this.draft) this.draft = this.draft.dropDocument(documentIdOf(details) ?? undefined);
			this.notice = {
				kind: 'conflict',
				text: 'The document you chose no longer exists. The unit is previewed again: choose again.'
			};
			this.#schedule(true);
			return;
		}
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

	/** The currency of the account a leg's other side would be created in. */
	#counterCurrency(entryId: number | null): string | null {
		const transfer = this.preview?.rows.find((r) => r.id === entryId)?.transfer;
		const offer = transfer?.offers.find((o) => o.kind === 'counter_leg');
		if (!offer) return null;
		return (
			this.#host.accountCurrency?.(offer.account_id) ??
			offer.counter_leg?.amount?.currency ??
			offer.amount?.currency ??
			null
		);
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

/** The original entry of the transaction `entryId` belongs to: the lowest stored id of its source. */
export function originalOf(unit: Pick<Unit, 'entries'>, entryId: number): number {
	const source = unit.entries.find((e) => e.id === entryId)?.source_transaction_id ?? null;
	if (source === null) return entryId;
	return Math.min(
		...unit.entries.filter((e) => e.source_transaction_id === source).map((e) => e.id)
	);
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
