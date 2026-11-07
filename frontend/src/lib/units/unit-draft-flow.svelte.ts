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
	BOOKING_FIXED,
	describeProblem,
	draftErrorText,
	differenceOf,
	problemSentence,
	suggestedSplitOf,
	type ProblemText
} from './problems.js';
import { proposedOffer } from './transfer.js';
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
	/** the kind of an account, for the words of a problem about a clearance account */
	accountKind?: (accountId: number) => string | undefined;
	/** the commit worked: move on (advance to the next unit, or close) */
	committed: (out: UnitCommit, anchorId: number) => void;
};

export type PreviewStatus = 'idle' | 'loading' | 'ready' | 'error';

/** A line the panel shows about what just happened, with the action that goes with it. */
export type FlowNotice = {
	kind: 'conflict' | 'error' | 'info';
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
	/** the unit was read again: the next preview's entries replace what is known of the partners */
	#reread = false;

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
			const stored = draft.knownEntry(id);
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
				counterCurrency: (entryId) => this.#counterCurrency(entryId),
				counterKind: (entryId) => this.#counterKind(entryId)
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
		this.receivedTexts = {};
		this.receivedErrors = {};
		this.lastAddedSplit = null;
		this.tagBusy = false;
		this.committing = false;
		this.#window = null;
		this.#feePending = false;
		this.#reread = false;
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
		if (next.dropped.length > 0) this.notice = this.#droppedNotice(next);
		this.commitProblems = [];
		this.#schedule(immediate);
	}

	/**
	 * Change what is drafted on the entry `id`. A partner that only a proposal (or settling) joins
	 * to the unit is first pinned as a pick, so that the draft may hold the change and the commit
	 * writes the pair as it would write the proposal accepted. A change the draft refuses pins nothing.
	 */
	#editEntry(id: number, change: (draft: Draft) => Draft, immediate = true): void {
		this.edit((draft) => {
			const pinned = this.#pinned(draft, id);
			const next = change(pinned);
			return next === pinned ? draft : next;
		}, immediate);
	}

	#pinned(draft: Draft, id: number): Draft {
		const preview = this.preview;
		if (!preview || id < 0 || draft.isMember(id)) return draft;
		const row = preview.rows.find((r) => r.id === id && r.in_unit);
		if (!row) return draft;
		// the leg of this source that a leg of the unit as loaded is paired with
		const partner = preview.rows.find(
			(r) =>
				r.in_unit &&
				r.source_transaction_id === row.source_transaction_id &&
				r.counterpart_entry_id !== null &&
				draft.isLoaded(r.counterpart_entry_id)
		);
		const legId = partner?.counterpart_entry_id;
		if (!partner || legId === null || legId === undefined) return draft;
		const leg = preview.rows.find((r) => r.id === legId);
		const proposal = leg?.transfer?.proposed_pick?.entry_id === partner.id;
		const exact = leg?.transfer ? (proposedOffer(leg.transfer)?.exact ?? false) : false;
		return draft.pinPick(legId, partner.id, { proposal, exact });
	}

	/** "Your changes to … were dropped": entries that left the unit take what was drafted on them along. */
	#droppedNotice(draft: Draft): FlowNotice {
		const labels = draft.dropped.map((id) => draft.knownEntry(id)?.display_text ?? `Entry ${id}`);
		const one = labels.length === 1;
		return {
			kind: 'info',
			text: `Your changes to ${labels.join(', ')} were dropped: ${one ? 'it is' : 'they are'} no longer part of this unit.`
		};
	}

	setField(id: number, field: FieldName, value: FieldValue, shown: ShownBasis | null = null): void {
		this.#editEntry(id, (d) => d.setField(id, field, value, shown));
	}

	/** The X of a field: no payee (the user's decision), or the passes propose again. */
	clearField(id: number, field: FieldName): void {
		this.#editEntry(id, (d) => d.clearField(id, field));
	}

	resetField(id: number, field: FieldName): void {
		this.#editEntry(id, (d) => d.resetField(id, field));
	}

	/** "Reset to proposal": the user's value is dropped, the stored one is shown again. */
	revertField(id: number, field: FieldName): void {
		this.#editEntry(id, (d) => d.revertField(id, field));
	}

	setText(id: number, key: 'description' | 'note', text: string): void {
		this.#editEntry(
			id,
			(d) => (key === 'description' ? d.setDescription(id, text) : d.setNote(id, text)),
			false
		);
	}

	/** The type buttons: the entry becomes what was clicked (a transfer's destination is chosen next). */
	setType(id: number, type: 'flow' | 'transfer'): void {
		this.#editEntry(id, (d) =>
			type === 'flow' ? d.convertToFlow(id) : d.convertToTransfer(id, null)
		);
	}

	/** `x`: a transfer becomes a flow, anything else (a flow, an entry with no type yet) a transfer. */
	convert(id: number, currentType: string | null): void {
		this.setType(id, currentType === 'transfer' ? 'flow' : 'transfer');
	}

	/** Put a tag on the entry or take it off (applied with the commit, like every other choice). */
	toggleTag(id: number, tagId: number): void {
		this.#editEntry(id, (d) => d.toggleTag(id, tagId));
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
		this.#editEntry(sourceEntryId, (d) => d.addSplit(sourceEntryId), false);
		// refused (the entry is not part of the unit): nothing was added
		if (!this.draft?.isNew(id)) return null;
		this.lastAddedSplit = id;
		return id;
	}

	removeSplit(id: number): void {
		this.#forgetAmount(id);
		this.#editEntry(id, (d) => d.removeSplit(id));
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
		const stored = this.draft?.knownEntry(split.source_entry_id);
		const negative = (row?.amount.amount ?? stored?.amount.amount ?? split.amount) < 0;
		const id = this.addSplit(split.source_entry_id);
		if (id === null) return;
		this.#editEntry(id, (d) => d.setSplitAmount(id, Math.abs(split.amount) * (negative ? -1 : 1)));
	}

	#storedOfSource(sourceId: number): Entry | undefined {
		return [...(this.draft?.knownEntries.values() ?? [])].find(
			(e) => e.source_transaction_id === sourceId
		);
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
		this.#editEntry(id, (d) => d.setSplitAmount(id, parsed.minor));
	}

	#parseAmount(id: number, text: string): ReturnType<typeof parseAllocation> | null {
		const draft = this.draft;
		if (!this.unit || !draft) return null;
		const split = draft.splits.find((s) => s.id === id);
		const source = draft.knownEntry(split ? split.sourceEntryId : id);
		if (!source) return null;
		return parseAllocation(text, source.amount.currency, this.#host.locale(), source.amount.amount);
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
				// the entries of the unit the preview holds: the draft knows them from now on
				if (this.draft) this.draft = this.draft.know(preview.entries, this.#reread);
				this.#reread = false;
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

	/** A pick the lists no longer hold: they are loaded again and the pick forgotten. */
	#afterPreview(preview: UnitPreview): void {
		const gone = preview.problems.filter((p) => p.code === 'stale_reference');
		if (gone.length === 0) {
			this.#suggestFee(preview);
			return;
		}
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

	/**
	 * The preview right after a pick: when it says the pair differs by a fee, the fee is split off
	 * as a draft split, once per pick (the pick's guard is spent whatever the answer says).
	 */
	#suggestFee(preview: UnitPreview): void {
		if (!this.#feePending) return;
		this.#feePending = false;
		const suggested = preview.problems.map(suggestedSplitOf).find((s) => s !== null);
		if (!suggested || this.committing) return;
		// the split is the app's own follow-up of the pick: a notice the pick raised stays
		const notice = this.notice;
		this.#applySplit(suggested);
		if (notice) this.notice = notice;
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
			case 'invalid_draft': {
				const code = (error.details as { code?: string } | null)?.code;
				this.notice = {
					kind: 'error',
					text:
						draftErrorText(code) ??
						(code === 'pairing_not_transfer'
							? 'Only a transfer leg has a partner. Take the partner pick back, or make the entry a transfer.'
							: code === 'invalid_pairing'
								? 'The partner you picked cannot be used. Pick another partner.'
								: code === 'booking_fixed'
									? BOOKING_FIXED
									: 'This change cannot be committed as it stands. Review the amounts and values.')
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
	async #moved(text: string): Promise<void> {
		const draft = this.draft;
		if (!draft) return;
		try {
			const unit = await getUnit(draft.anchorId);
			if (this.draft !== draft) return;
			this.unit = unit;
			this.draft = draft.rebase(unit);
			this.#reread = true;
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
		const details = (error.details ?? {}) as {
			field?: string;
			entity?: string;
			id?: number;
		};
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

	#counterKind(entryId: number | null): string | null {
		const row = this.preview?.rows.find((r) => r.id === entryId);
		const account = row?.fields.counter_account?.value;
		return typeof account === 'number' ? (this.#host.accountKind?.(account) ?? null) : null;
	}

	#currency(entryId: number | null): string {
		const row = this.preview?.rows.find((r) => r.id === entryId);
		return (
			row?.amount.currency ??
			(entryId === null ? undefined : this.draft?.knownEntry(entryId))?.amount.currency ??
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
