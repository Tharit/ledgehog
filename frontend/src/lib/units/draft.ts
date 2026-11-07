// The client's draft of a unit (spec §6, architecture §4.1, §6.3): the user's choices laid over
// the unit as loaded. Pure and immutable: every operation returns the next draft. It decides
// nothing about what the choices imply (the server's preview does); it only remembers what the
// user chose and turns it into the request. A field is `keep` (untouched), `fixed` (the user's
// value) or `reresolve` (the passes decide again); a split row has a temporary (negative) id.
import { formatMoney, parseMoneyInput, type MoneyParseError } from '#lib/format/index.js';
import type { Entry } from '#lib/types/domain.js';
import { keyOf } from './evidence.js';
import type { DraftEntryRequest, FieldDraftRequest, Unit, UnitDraftRequest } from './types.js';

export const FIELD_NAMES = ['type', 'payee', 'category', 'counter_account'] as const;
export type FieldName = (typeof FIELD_NAMES)[number];
export type FieldValue = number | string | null;

/** The key of the proposal the user was shown when they chose the value it equals. */
export type ShownBasis = { pass: string; basis: Record<string, unknown> };

/**
 * A pick the client makes itself: the user edited a partner that only a proposal (or settling)
 * joins to the unit, so the pair is pinned as a pick, which a commit writes as it would write the
 * proposal accepted. It keeps the proposal's styling: what the preview showed when it was pinned.
 */
export type Pinned = {
	/** the pair was a proposal of the server's (else settling would have made it) */
	proposal: boolean;
	/** the proposal was an exact match */
	exact: boolean;
};

/** The partner of a transfer leg: the user's pick, or "pair it by the rules again". Absent: as it stands. */
export type PairingEdit =
	| { mode: 'pick'; partnerEntryId: number; pinned?: Pinned }
	| { mode: 'reresolve' }
	/**
	 * The other side is created by the commit (an unsynced counter-account): `tempId` is the
	 * client-issued negative id of the row the preview shows for it, stable for the draft's life;
	 * `receivedAmount` is what a cross-currency counter-leg receives (unsigned minor units).
	 */
	| { mode: 'counter_leg'; tempId: number; receivedAmount: number | null };

export type FieldEdit =
	{ mode: 'fixed'; value: FieldValue; shown: ShownBasis | null } | { mode: 'reresolve' };

/** What the user changed on one entry (a stored one, or a split row by its temporary id). */
export type EntryEdit = {
	fields: Partial<Record<FieldName, FieldEdit>>;
	/** absent: as stored; null or text: the draft's (raw as typed) */
	description?: string | null;
	note?: string | null;
	/** the entry's allocation; null: a new split whose amount has not been entered yet */
	amount?: number | null;
	/** the tag change, relative to the tags the entry had when loaded (a split row: inherited) */
	tags?: TagEdit;
	/** the partner of a transfer leg (a stored entry only) */
	pairing?: PairingEdit;
};

/** Tags the user added (the entry did not have them) and removed (it had). Never both, never empty. */
export type TagEdit = { add: readonly number[]; remove: readonly number[] };

/**
 * A row the draft creates: it splits the source of a stored entry. `tags` are the tags it starts
 * with (the stored ones of that entry: what the server copies); the row's tag change applies on
 * top, and starts as the difference to what the original showed when the row was added.
 */
export type NewSplit = {
	id: number;
	sourceEntryId: number;
	tags: readonly number[];
};

export type Base = {
	/** the source transaction the entry belongs to */
	sourceId: number | null;
	description: string | null;
	note: string | null;
	amount: number;
	/** the values the entry stores for the derived fields */
	fields: Readonly<Record<FieldName, FieldValue>>;
	/** the entry stores "no payee" as the user's decision (an empty payee with the `user` key) */
	noPayee: boolean;
	/** the tags the entry stores */
	tags: readonly number[];
};

/** An entry the draft knows: as stored (what the unit loaded, or a preview told of its unit). */
type Known = { entry: Entry; base: Base };

type State = {
	anchorId: number;
	versions: Readonly<Record<number, number>>;
	/** the entries of the unit as loaded: the side the panel was opened on */
	loaded: ReadonlySet<number>;
	/** every entry known so far (the loaded ones, then those previews told of), by id */
	known: ReadonlyMap<number, Known>;
	/** the ids of the entries the last operation dropped from the draft (they left the unit) */
	dropped: readonly number[];
	edits: ReadonlyMap<number, EntryEdit>;
	splits: readonly NewSplit[];
	removed: readonly number[];
	reresolveAll: boolean;
};

const EMPTY: EntryEdit = { fields: {} };

/** What the draft compares an edit with: the entry as stored, normalised. One place for every source. */
function baseOf(e: Entry): Base {
	return {
		sourceId: e.source_transaction_id ?? null,
		description: e.description,
		note: e.note,
		amount: e.amount.amount,
		fields: {
			type: e.type,
			payee: e.payee_id,
			category: e.category_id,
			counter_account: e.counter_account_id
		},
		noPayee: e.payee_id === null && keyOf(e.derivation, 'payee')?.pass === 'user',
		tags: [...e.tag_ids]
	};
}

function knownOf(e: Entry): Known {
	return { entry: e, base: baseOf(e) };
}

function versionsOf(unit: Pick<Unit, 'entries'>): Record<number, number> {
	return Object.fromEntries(unit.entries.map((e) => [e.id, e.version]));
}

/** Text as the server stores it: surrounding space trimmed, nothing at all is null. */
export function normaliseText(text: string | null): string | null {
	const trimmed = (text ?? '').trim();
	return trimmed === '' ? null : trimmed;
}

function without<T extends object, K extends keyof T>(object: T, key: K): Omit<T, K> {
	const copy = { ...object };
	delete copy[key];
	return copy;
}

function isEmpty(edit: EntryEdit): boolean {
	return (
		Object.keys(edit.fields).length === 0 &&
		edit.description === undefined &&
		edit.note === undefined &&
		edit.amount === undefined &&
		edit.tags === undefined &&
		edit.pairing === undefined
	);
}

/** The pick the client made itself (pinned) is no choice of the user's. */
function isPinned(edit: EntryEdit): boolean {
	return edit.pairing?.mode === 'pick' && edit.pairing.pinned !== undefined;
}

/** What the user chose on an entry: its edit without the pick the client pinned. */
function chosen(edit: EntryEdit): EntryEdit {
	return isPinned(edit) ? without(edit, 'pairing') : edit;
}

function samePairing(a: PairingEdit | undefined, b: PairingEdit | undefined): boolean {
	if (a === undefined || b === undefined) return a === b;
	if (a.mode !== b.mode) return false;
	return a.mode === 'pick' ? a.partnerEntryId === (b as typeof a).partnerEntryId : true;
}

/** A change of the type or the counter-account is the user's word over a pick: the pick goes. */
function unpaired(edit: EntryEdit, field: FieldName): EntryEdit {
	return (field === 'type' || field === 'counter_account') && edit.pairing !== undefined
		? without(edit, 'pairing')
		: edit;
}

/** The tag change in its normal form: sorted, and absent when it changes nothing. */
function tagEdit(add: readonly number[], remove: readonly number[]): TagEdit | undefined {
	if (add.length === 0 && remove.length === 0) return undefined;
	return { add: [...add].sort((a, b) => a - b), remove: [...remove].sort((a, b) => a - b) };
}

/**
 * Is `value` what the entry stores for the field? An empty payee is two stored states: undecided
 * and "no payee" (the user's decision); `null` equals only the one the entry is in.
 */
function isStored(stored: Base, field: FieldName, value: FieldValue): boolean {
	if (stored.fields[field] !== value) return false;
	return field !== 'payee' || value !== null || stored.noPayee;
}

/** `edit` with the field's value in place, or without it when that is the very value stored. */
function withField(
	fields: EntryEdit['fields'],
	stored: Base | undefined,
	field: FieldName,
	value: FieldValue,
	shown: ShownBasis | null
): EntryEdit['fields'] {
	// the stored value is no edit, unless it confirms a proposal the user was shown (`shown`)
	if (stored !== undefined && shown === null && isStored(stored, field, value)) {
		return without(fields, field);
	}
	return { ...fields, [field]: { mode: 'fixed', value, shown } };
}

/**
 * An edit measured against what the entry stores (now): a tag someone else has put on or taken off
 * meanwhile, a value someone else has stored meanwhile, is no longer a change. `start` is what the
 * entry's tags start from (a split row: what it inherits).
 */
function normalisedEdit(
	edit: EntryEdit,
	was: Base | undefined,
	start: readonly number[] | undefined
): EntryEdit {
	const next = { ...edit };
	if (start && next.tags) {
		const tags = tagEdit(
			next.tags.add.filter((t) => !start.includes(t)),
			next.tags.remove.filter((t) => start.includes(t))
		);
		if (tags) next.tags = tags;
		else delete next.tags;
	}
	if (was) {
		if (next.description !== undefined && normaliseText(next.description) === was.description) {
			delete next.description;
		}
		if (next.note !== undefined && normaliseText(next.note) === was.note) delete next.note;
		if (next.amount === was.amount) delete next.amount;
		next.fields = Object.fromEntries(
			Object.entries(next.fields).filter(
				([name, f]) =>
					!(f.mode === 'fixed' && f.shown === null && isStored(was, name as FieldName, f.value))
			)
		) as EntryEdit['fields'];
	}
	return next;
}

export class Draft {
	readonly #s: State;

	private constructor(state: State) {
		this.#s = state;
	}

	/** The empty draft over a unit as loaded. */
	static of(unit: Pick<Unit, 'anchor_entry_id' | 'entries'>): Draft {
		return new Draft({
			anchorId: unit.anchor_entry_id,
			versions: versionsOf(unit),
			loaded: new Set(unit.entries.map((e) => e.id)),
			known: new Map(unit.entries.map((e) => [e.id, knownOf(e)])),
			dropped: [],
			edits: new Map(),
			splits: [],
			removed: [],
			reresolveAll: false
		});
	}

	#with(change: Partial<State>): Draft {
		return new Draft({ ...this.#s, dropped: [], ...change });
	}

	// ---- what the draft knows, and what is part of its unit ------------------------------------

	/**
	 * Tell the draft of entries a preview named (the partners a proposal or settling joined, the
	 * ones a pick brought in). Only ids not yet known are added, so what is known is stable while
	 * previews are in flight; `replace` re-reads those that are not loaded (the unit was read
	 * again), and an edit that has become the stored value is no edit.
	 */
	know(entries: readonly Entry[], replace = false): Draft {
		const known = new Map(this.#s.known);
		let changed = false;
		for (const e of entries) {
			if (!known.has(e.id) || (replace && !this.#s.loaded.has(e.id))) {
				known.set(e.id, knownOf(e));
				changed = true;
			}
		}
		if (!changed) return this;
		return this.#renormalised({ ...this.#s, known });
	}

	/** The entry as stored, when the draft knows it (loaded, or told by a preview). */
	knownEntry(id: number): Entry | null {
		return this.#s.known.get(id)?.entry ?? null;
	}

	/** Every entry the draft knows. */
	get knownEntries(): ReadonlyMap<number, Entry> {
		return new Map([...this.#s.known].map(([id, k]) => [id, k.entry]));
	}

	/** Is the entry of the unit as loaded: the side the panel was opened on? */
	isLoaded(id: number): boolean {
		return this.#s.loaded.has(id);
	}

	/**
	 * The entries the draft can say anything about: the unit as loaded, and every entry of each
	 * source transaction a pick pairs with (the partner's side). The server loads exactly these.
	 */
	get members(): ReadonlySet<number> {
		const partnerSources = new Set<number>();
		for (const edit of this.#s.edits.values()) {
			if (edit.pairing?.mode !== 'pick') continue;
			const source = this.#s.known.get(edit.pairing.partnerEntryId)?.base.sourceId;
			if (source !== undefined && source !== null) partnerSources.add(source);
		}
		const members = new Set(this.#s.loaded);
		for (const [id, k] of this.#s.known) {
			if (k.base.sourceId !== null && partnerSources.has(k.base.sourceId)) members.add(id);
		}
		return members;
	}

	/** Can the draft hold a change of this entry (or split row)? */
	isMember(id: number): boolean {
		return id < 0 ? this.isNew(id) : this.members.has(id);
	}

	/** The ids of the entries (stored ones: a split row counts as the entry it splits) the last operation dropped. */
	get dropped(): readonly number[] {
		return this.#s.dropped;
	}

	/** Is this entry on the partner's side: part of the unit, but not of the unit as loaded? */
	isJoined(id: number): boolean {
		return id > 0 && !this.#s.loaded.has(id);
	}

	/** The tags the original of the source of `entryId` stores: what a split row inherits. */
	#originalTags(entryId: number): readonly number[] {
		return this.#s.known.get(this.#originalOf(entryId))?.base.tags ?? [];
	}

	/**
	 * What no longer belongs to the unit goes: the edits, splits and removals of entries that left it
	 * (a partner a pick replaced). The ids of the stored entries concerned are `dropped`. An entry of
	 * the unit as loaded stays whatever its pair does: it is committed with its drafts.
	 */
	#pruned(): Draft {
		const members = this.members;
		const edits = new Map<number, EntryEdit>();
		const dropped = new Set<number>();
		const splitIds = new Set(this.#s.splits.map((s) => s.id));
		const staying = this.#s.splits.filter((s) => members.has(s.sourceEntryId));
		const stays = new Set(staying.map((s) => s.id));
		for (const split of this.#s.splits) if (!stays.has(split.id)) dropped.add(split.sourceEntryId);
		for (const [id, edit] of this.#s.edits) {
			if (id < 0 ? splitIds.has(id) && !stays.has(id) : !members.has(id)) {
				if (id > 0 && !isEmpty(chosen(edit))) dropped.add(id);
				continue;
			}
			edits.set(id, edit);
		}
		const removed = this.#s.removed.filter((id) => members.has(id));
		for (const id of this.#s.removed) if (!members.has(id)) dropped.add(id);
		const changed = dropped.size > 0 || staying.length !== this.#s.splits.length;
		const next = changed
			? new Draft({ ...this.#s, edits, splits: staying, removed, dropped: [...dropped] })
			: this;
		return next.#unpinned();
	}

	/**
	 * A pinned pick whose partner has nothing drafted on it any more is no longer needed: the
	 * proposal does the same, as the commit accepts it.
	 */
	#unpinned(): Draft {
		let edits: Map<number, EntryEdit> | null = null;
		for (const [id, edit] of this.#s.edits) {
			if (!isPinned(edit) || edit.pairing?.mode !== 'pick') continue;
			const source = this.#s.known.get(edit.pairing.partnerEntryId)?.base.sourceId;
			if (source === undefined || source === null || this.#hasDraftOn(source)) continue;
			edits ??= new Map(this.#s.edits);
			const rest = without(edit, 'pairing');
			if (isEmpty(rest)) edits.delete(id);
			else edits.set(id, rest);
		}
		return edits ? new Draft({ ...this.#s, edits }) : this;
	}

	/** Is anything drafted on the entries of this source (an edit, a split, a removal)? */
	#hasDraftOn(sourceId: number): boolean {
		const inSource = (id: number) => this.#s.known.get(id)?.base.sourceId === sourceId;
		return (
			this.#s.removed.some(inSource) ||
			this.#s.splits.some((s) => inSource(s.sourceEntryId)) ||
			[...this.#s.edits].some(([id, edit]) => id > 0 && inSource(id) && !isEmpty(chosen(edit)))
		);
	}

	/**
	 * Pin the pick of a proposal (or of settling's pair) so that its partner can be edited: the
	 * leg `legId` of the unit as loaded pairs with `partnerEntryId`, which only the preview joins.
	 * Only while the leg has no pairing edit of its own.
	 */
	pinPick(legId: number, partnerEntryId: number, how: Pinned): Draft {
		if (!this.#s.loaded.has(legId) || this.edit(legId).pairing !== undefined) return this;
		if (!this.#s.known.has(partnerEntryId)) return this;
		const edits = new Map(this.#s.edits);
		edits.set(legId, {
			...this.edit(legId),
			pairing: { mode: 'pick', partnerEntryId, pinned: how }
		});
		return this.#with({ edits });
	}

	/** The edits and splits of `state`, with each edit measured against what is stored now. */
	#renormalised(state: State): Draft {
		const edits = new Map<number, EntryEdit>();
		const splits = state.splits.map((s) => ({
			...s,
			tags: new Draft(state).#originalTags(s.sourceEntryId)
		}));
		for (const [id, edit] of state.edits) {
			const start =
				state.known.get(id)?.base.tags ?? splits.find((s) => s.id === id)?.tags ?? undefined;
			const next = normalisedEdit(edit, state.known.get(id)?.base, start);
			if (!isEmpty(next)) edits.set(id, next);
		}
		return new Draft({ ...state, edits, splits, dropped: [] }).#unpinned();
	}

	get anchorId(): number {
		return this.#s.anchorId;
	}
	get versions(): Readonly<Record<number, number>> {
		return this.#s.versions;
	}
	get splits(): readonly NewSplit[] {
		return this.#s.splits;
	}
	get removed(): readonly number[] {
		return this.#s.removed;
	}
	get reresolveAll(): boolean {
		return this.#s.reresolveAll;
	}

	/** Has the user edited anything? A draft that has not is still committable (it accepts). */
	get isDirty(): boolean {
		return (
			this.hasOtherChanges || [...this.#s.edits.values()].some((edit) => !isEmpty(chosen(edit)))
		);
	}

	/**
	 * Has the user changed anything but the derived fields? Whether a field edit changes anything
	 * is for the preview to say (`effectiveChanged`, view.ts): an edit can end in the stored value.
	 */
	get hasOtherChanges(): boolean {
		if (this.#s.reresolveAll || this.#s.removed.length > 0 || this.#s.splits.length > 0) {
			return true;
		}
		for (const edit of this.#s.edits.values()) {
			if (
				edit.description !== undefined ||
				edit.note !== undefined ||
				edit.amount !== undefined ||
				edit.tags !== undefined ||
				(edit.pairing !== undefined && !isPinned(edit))
			) {
				return true;
			}
		}
		return false;
	}

	/** Every derived-field edit the draft holds. */
	fieldEdits(): { id: number; field: FieldName; edit: FieldEdit }[] {
		return [...this.#s.edits].flatMap(([id, e]) =>
			FIELD_NAMES.flatMap((field) => {
				const edit = e.fields[field];
				return edit ? [{ id, field, edit }] : [];
			})
		);
	}

	/** New splits whose amount has not been entered: the preview and the commit leave them out. */
	get pendingSplits(): readonly NewSplit[] {
		return this.#s.splits.filter((s) => this.#s.edits.get(s.id)?.amount == null);
	}

	edit(id: number): EntryEdit {
		return this.#s.edits.get(id) ?? EMPTY;
	}

	fieldEdit(id: number, field: FieldName): FieldEdit | undefined {
		return this.edit(id).fields[field];
	}

	isRemoved(id: number): boolean {
		return this.#s.removed.includes(id);
	}

	isNew(id: number): boolean {
		return this.#s.splits.some((s) => s.id === id);
	}

	/** The temporary id the next split (or counter-leg) gets: below every one in use. */
	get nextTempId(): number {
		const legs = [...this.#s.edits.values()].flatMap((e) =>
			e.pairing?.mode === 'counter_leg' ? [e.pairing.tempId] : []
		);
		return Math.min(0, ...this.#s.splits.map((s) => s.id), ...legs) - 1;
	}

	/**
	 * A change of one entry's edit. Only an entry of the unit can be changed (`members`); a change of
	 * its pick takes with it what was drafted on a partner that leaves.
	 */
	#edited(id: number, change: (edit: EntryEdit) => EntryEdit): Draft {
		if (!this.isMember(id)) return this;
		const before = this.edit(id);
		const next = change(before);
		if (isEmpty(next) && !this.#s.edits.has(id)) return this;
		const edits = new Map(this.#s.edits);
		if (isEmpty(next)) edits.delete(id);
		else edits.set(id, next);
		const out = this.#with({ edits });
		return samePairing(before.pairing, next.pairing) ? out.#unpinned() : out.#pruned();
	}

	/** The pair's type and counter-account are the pair's: not edited on the partner's side. */
	#pairFixed(id: number, field: FieldName): boolean {
		return (field === 'type' || field === 'counter_account') && this.isJoined(id);
	}

	/**
	 * The user's value for a field. `shown` is the key of the proposal the user was shown for this
	 * very value (the server writes it as the basis of the confirmed value, spec §5.9).
	 */
	setField(
		id: number,
		field: FieldName,
		value: FieldValue,
		shown: ShownBasis | null = null
	): Draft {
		if (this.#pairFixed(id, field)) return this;
		const stored = this.#s.known.get(id)?.base;
		return this.#edited(id, (e) => ({
			...unpaired(e, field),
			fields: withField(e.fields, stored, field, value, shown)
		}));
	}

	/** "Reset to proposal": the passes decide this field again, a decided value included. */
	resetField(id: number, field: FieldName): Draft {
		if (this.#pairFixed(id, field)) return this;
		return this.#edited(id, (e) => ({
			...unpaired(e, field),
			fields: { ...e.fields, [field]: { mode: 'reresolve' } }
		}));
	}

	/** The partner the user chose for a transfer leg (the offers list, spec §5.7). */
	pickPartner(id: number, partnerEntryId: number): Draft {
		if (!this.#s.loaded.has(id)) return this;
		return this.#edited(id, (e) => ({ ...e, pairing: { mode: 'pick', partnerEntryId } }));
	}

	/**
	 * The other side of a leg is created by the commit (spec §5.7). The temporary id is issued once
	 * and kept while the pick stands; picking again keeps it (and the amount received, unless one is given).
	 */
	pickCounterLeg(id: number, options: { receivedAmount?: number | null } = {}): Draft {
		if (!this.#s.loaded.has(id)) return this;
		const held = this.edit(id).pairing;
		const kept = held?.mode === 'counter_leg' ? held : null;
		const tempId = kept?.tempId ?? this.nextTempId;
		const receivedAmount =
			options.receivedAmount !== undefined
				? options.receivedAmount
				: (kept?.receivedAmount ?? null);
		return this.#edited(id, (e) => ({
			...e,
			pairing: { mode: 'counter_leg', tempId, receivedAmount }
		}));
	}

	/** The amount a counter-leg receives, unsigned minor units in the counter-account's currency. */
	setReceivedAmount(id: number, minor: number | null): Draft {
		const held = this.edit(id).pairing;
		if (held?.mode !== 'counter_leg' || held.receivedAmount === minor) return this;
		return this.#edited(id, (e) => ({ ...e, pairing: { ...held, receivedAmount: minor } }));
	}

	/** Pair the leg by the rules again, a standing pair included. */
	reresolvePairing(id: number): Draft {
		if (!this.#s.loaded.has(id)) return this;
		return this.#edited(id, (e) => ({ ...e, pairing: { mode: 'reresolve' } }));
	}

	/** Take a pairing edit back: the leg is as it stands. */
	clearPairing(id: number): Draft {
		if (!this.#s.loaded.has(id)) return this;
		return this.#edited(id, (e) => without(e, 'pairing'));
	}

	pairingEdit(id: number): PairingEdit | undefined {
		return this.edit(id).pairing;
	}

	/** Does any leg hold a picked counter-leg? */
	get hasCounterLeg(): boolean {
		return [...this.#s.edits.values()].some((e) => e.pairing?.mode === 'counter_leg');
	}

	/** Does any leg hold a partner the user picked? (not one the client pinned) */
	get hasPick(): boolean {
		return [...this.#s.edits.values()].some((e) => e.pairing?.mode === 'pick' && !isPinned(e));
	}

	/**
	 * The X of a field: the user takes their choice back. A payee is then empty by the user's
	 * decision ("no payee": fixed null, a standing value that no pass proposes over), unless the
	 * entry already stores that. Any other field has no empty decision: the passes propose again
	 * (reresolve). Whether that ends in the stored value is the preview's to say, so the edit is
	 * kept and the panel's dirtiness and "Reset to proposal" ask `effectiveChanged`.
	 */
	clearField(id: number, field: FieldName): Draft {
		if (field !== 'payee') return this.resetField(id, field);
		const stored = this.#s.known.get(id)?.base;
		if (stored?.noPayee) return this.revertField(id, field);
		return this.#edited(id, (e) => ({
			...e,
			fields: { ...e.fields, payee: { mode: 'fixed', value: null, shown: null } }
		}));
	}

	/** Undo the user's edit of a field: it is untouched again. */
	revertField(id: number, field: FieldName): Draft {
		return this.#edited(id, (e) => ({ ...e, fields: without(e.fields, field) }));
	}

	#setText(id: number, key: 'description' | 'note', text: string | null): Draft {
		const base = this.#s.known.get(id)?.base;
		// the very text that is stored is no edit; text that only differs by space is, so that a
		// space typed at the end is not eaten while the user goes on typing
		const same = base !== undefined && (text ?? '') === (base[key] ?? '');
		return this.#edited(id, (e) => {
			if (same) return without(e, key);
			return key === 'description' ? { ...e, description: text } : { ...e, note: text };
		});
	}

	setDescription(id: number, text: string | null): Draft {
		return this.#setText(id, 'description', text);
	}

	setNote(id: number, text: string | null): Draft {
		return this.#setText(id, 'note', text);
	}

	/** The allocation of a split row or of a stored entry of a split (never its residual). */
	setSplitAmount(id: number, minor: number | null): Draft {
		const base = this.#s.known.get(id)?.base;
		if (base !== undefined && minor === base.amount) {
			return this.#edited(id, (e) => without(e, 'amount'));
		}
		return this.#edited(id, (e) => ({ ...e, amount: minor }));
	}

	/** A new row splitting the source of `sourceEntryId` (a stored entry); its amount is entered next. */
	addSplit(sourceEntryId: number): Draft {
		if (!this.isMember(sourceEntryId)) return this;
		const id = this.nextTempId;
		// a new row starts with the tags the ORIGINAL of the source stores (what the server copies)
		const tags = this.#originalTags(sourceEntryId);
		// the row shows what the original shows now (its draft tags); the server copies the stored
		// ones, so the difference goes into the row's own change. After this the row is independent.
		const original = this.#originalOf(sourceEntryId);
		const shown = this.effectiveTagIds(original);
		const change = tagEdit(
			shown.filter((t) => !tags.includes(t)),
			tags.filter((t) => !shown.includes(t))
		);
		return this.#with({
			splits: [...this.#s.splits, { id, sourceEntryId, tags }],
			edits: new Map(this.#s.edits).set(id, {
				fields: {},
				amount: null,
				...(change ? { tags: change } : {})
			})
		});
	}

	/** The original of a source: its lowest stored id among the entries known. */
	#originalOf(entryId: number): number {
		const source = this.#s.known.get(entryId)?.base.sourceId ?? null;
		if (source === null) return entryId;
		let lowest = entryId;
		for (const [id, k] of this.#s.known) if (k.base.sourceId === source && id < lowest) lowest = id;
		return lowest;
	}

	/** The tags an entry starts from: what it stores, or for a split row what it inherits. */
	#startTags(id: number): readonly number[] {
		return this.#s.known.get(id)?.base.tags ?? this.#s.splits.find((s) => s.id === id)?.tags ?? [];
	}

	/** The tag edit of an entry (undefined: untouched). */
	tagEdit(id: number): TagEdit | undefined {
		return this.edit(id).tags;
	}

	/** The tags the entry has with the draft applied: the ones it starts from, then the change. */
	effectiveTagIds(id: number): number[] {
		const change = this.tagEdit(id);
		const start = this.#startTags(id);
		if (!change) return [...start];
		return [...start.filter((t) => !change.remove.includes(t)), ...change.add];
	}

	/**
	 * Put a tag on the entry or take it off, whichever it is not now. The edit is kept relative to
	 * the tags the entry starts from: toggling a tag back leaves no edit.
	 */
	toggleTag(id: number, tagId: number): Draft {
		// an entry that is gone (a split row removed meanwhile) takes no change
		if (!this.isMember(id)) return this;
		const start = this.#startTags(id);
		const has = this.effectiveTagIds(id).includes(tagId);
		const stored = start.includes(tagId);
		return this.#edited(id, (e) => {
			let add = [...(e.tags?.add ?? [])];
			let remove = [...(e.tags?.remove ?? [])];
			if (has) {
				if (stored) remove = [...remove, tagId];
				else add = add.filter((t) => t !== tagId);
			} else if (stored) remove = remove.filter((t) => t !== tagId);
			else add = [...add, tagId];
			const next = tagEdit(add, remove);
			return next ? { ...e, tags: next } : without(e, 'tags');
		});
	}

	/** Forget a tag that no longer exists, wherever the draft names it. */
	dropTag(tagId: number): Draft {
		const edits = new Map<number, EntryEdit>();
		let changed = false;
		for (const [id, edit] of this.#s.edits) {
			const change = edit.tags;
			if (!change || !(change.add.includes(tagId) || change.remove.includes(tagId))) {
				edits.set(id, edit);
				continue;
			}
			changed = true;
			const next = tagEdit(
				change.add.filter((t) => t !== tagId),
				change.remove.filter((t) => t !== tagId)
			);
			const copy = next ? { ...edit, tags: next } : without(edit, 'tags');
			if (!isEmpty(copy)) edits.set(id, copy);
		}
		return changed ? this.#with({ edits }).#unpinned() : this;
	}

	/** Remove a split row (its amount returns to the residual) or a stored entry of a split. */
	removeSplit(id: number): Draft {
		if (!this.isMember(id)) return this;
		const edits = new Map(this.#s.edits);
		edits.delete(id);
		if (id < 0) {
			return this.#with({ splits: this.#s.splits.filter((s) => s.id !== id), edits }).#unpinned();
		}
		if (id === this.#s.anchorId || this.#s.removed.includes(id)) return this;
		return this.#with({ removed: [...this.#s.removed, id], edits });
	}

	/** Keep a stored entry that was marked for removal. */
	restoreSplit(id: number): Draft {
		return this.#with({ removed: this.#s.removed.filter((r) => r !== id) }).#unpinned();
	}

	/** Turn a flow into a transfer; `counterAccountId` null leaves the destination to be chosen. */
	convertToTransfer(id: number, counterAccountId: number | null): Draft {
		if (this.#pairFixed(id, 'type')) return this;
		const stored = this.#s.known.get(id)?.base;
		return this.#edited(id, (e) => {
			let fields = withField(
				without(without(e.fields, 'payee'), 'category'),
				stored,
				'type',
				'transfer',
				null
			);
			if (counterAccountId !== null) {
				fields = withField(fields, stored, 'counter_account', counterAccountId, null);
			}
			return { ...unpaired(e, 'type'), fields };
		});
	}

	/** Turn a transfer into a flow; the category and payee are proposed afresh. */
	convertToFlow(id: number): Draft {
		if (this.#pairFixed(id, 'type')) return this;
		const stored = this.#s.known.get(id)?.base;
		return this.#edited(id, (e) => ({
			...unpaired(e, 'type'),
			fields: withField(without(e.fields, 'counter_account'), stored, 'type', 'flow', null)
		}));
	}

	/**
	 * Resolve the whole unit afresh (spec §5.9). It applies to pending changes too: the derived
	 * values the user chose (type, payee, category, counter account) are dropped, the passes decide
	 * them again. Splits, their amounts, removals, descriptions and notes are kept. "Reset"
	 * (`UnitDraftFlow.discard`) is what undoes it.
	 */
	reresolve(on = true): Draft {
		if (!on) return on === this.#s.reresolveAll ? this : this.#with({ reresolveAll: false });
		let changed = !this.#s.reresolveAll;
		const edits = new Map<number, EntryEdit>();
		for (const [id, edit] of this.#s.edits) {
			if (Object.keys(edit.fields).length > 0 || edit.pairing !== undefined) changed = true;
			// a pick would outlive the re-resolve: the pairing is decided afresh too
			const next = without({ ...edit, fields: {} }, 'pairing');
			if (!isEmpty(next)) edits.set(id, next);
		}
		return changed ? this.#with({ reresolveAll: true, edits }).#pruned() : this;
	}

	/** Forget a pick whose category, payee or account no longer exists. */
	dropReference(field: Exclude<FieldName, 'type'>, id: number): Draft {
		return [...this.#s.edits].reduce<Draft>((draft, [entryId, edit]) => {
			const fieldEdit = edit.fields[field];
			return fieldEdit?.mode === 'fixed' && fieldEdit.value === id
				? draft.revertField(entryId, field)
				: draft;
		}, this);
	}

	/**
	 * The same choices over the unit as it is now: what no longer applies (an entry that is gone,
	 * a split of a source that left) is dropped; the versions are the ones just read. What is
	 * drafted on a partner the draft joined stays while the partner is still part of the unit.
	 */
	rebase(unit: Pick<Unit, 'anchor_entry_id' | 'entries'>): Draft {
		const ids = new Set(unit.entries.map((e) => e.id));
		const known = new Map(this.#s.known);
		for (const e of unit.entries) known.set(e.id, knownOf(e));
		// an entry that was part of the unit as loaded and is not any more is no longer known by this unit
		for (const id of this.#s.loaded) if (!ids.has(id)) known.delete(id);
		const edits = new Map([...this.#s.edits].filter(([id]) => id < 0 || known.has(id)));
		const draft = this.#renormalised({
			...this.#s,
			anchorId: ids.has(this.#s.anchorId) ? this.#s.anchorId : unit.anchor_entry_id,
			versions: versionsOf(unit),
			loaded: ids,
			known,
			edits,
			splits: this.#s.splits.filter((s) => known.has(s.sourceEntryId)),
			removed: this.#s.removed.filter((id) => known.has(id) && id !== unit.anchor_entry_id)
		});
		// the unit's membership is measured now: what left it takes its drafts along
		return draft.#pruned();
	}

	/**
	 * The request body. Splits whose amount has not been entered are left out. `versions` default to
	 * the ones the unit was loaded with; a commit passes what the last preview named.
	 */
	toRequest(versions: Readonly<Record<number, number>> = this.#s.versions): UnitDraftRequest {
		const entries: DraftEntryRequest[] = [];
		const splitOf = new Map(this.#s.splits.map((s) => [s.id, s]));
		const ids = [...this.#s.edits.keys()].filter((id) => id > 0).sort((a, b) => a - b);
		for (const id of ids) entries.push(this.#entryRequest(id, null));
		for (const split of this.#s.splits) {
			if (this.#s.edits.get(split.id)?.amount == null) continue;
			entries.push(this.#entryRequest(split.id, splitOf.get(split.id)!.sourceEntryId));
		}
		return {
			anchor_entry_id: this.#s.anchorId,
			entries,
			removed_entry_ids: [...this.#s.removed],
			reresolve_all: this.#s.reresolveAll,
			versions: { ...versions }
		};
	}

	#entryRequest(id: number, sourceEntryId: number | null): DraftEntryRequest {
		const edit = this.edit(id);
		const body: DraftEntryRequest = { id };
		if (sourceEntryId !== null) body.source_entry_id = sourceEntryId;
		if (edit.amount != null) body.amount = edit.amount;
		if (edit.description !== undefined) body.description = normaliseText(edit.description);
		if (edit.note !== undefined) body.note = normaliseText(edit.note);
		if (edit.tags) body.tags = { add: [...edit.tags.add], remove: [...edit.tags.remove] };
		if (edit.pairing) {
			const pairing = edit.pairing;
			body.pairing =
				pairing.mode === 'pick'
					? { mode: 'pick', partner_entry_id: pairing.partnerEntryId }
					: pairing.mode === 'counter_leg'
						? {
								mode: 'counter_leg',
								counter_leg: { temp_id: pairing.tempId, received_amount: pairing.receivedAmount }
							}
						: { mode: 'reresolve', partner_entry_id: null };
		}
		for (const name of FIELD_NAMES) {
			const field = edit.fields[name];
			if (field) body[name] = fieldRequest(field);
		}
		return body;
	}
}

function fieldRequest(edit: FieldEdit): FieldDraftRequest {
	if (edit.mode === 'reresolve') return { mode: 'reresolve' };
	return {
		mode: 'fixed',
		value: edit.value,
		...(edit.shown ? { shown_basis: { pass: edit.shown.pass, basis: edit.shown.basis } } : {})
	};
}

// ---- the amounts of a split ---------------------------------------------------------------

export type AllocationError = MoneyParseError | 'zero';

export type Allocation = { ok: true; minor: number } | { ok: false; error: AllocationError };

/**
 * What the user typed as the amount of a split row. It is entered unsigned and takes the sign of
 * the entry it splits (a split of an expense is an expense); a typed sign is not honoured.
 */
export function parseAllocation(
	text: string,
	currency: string,
	locale: string,
	sourceAmount: number
): Allocation {
	const parsed = parseMoneyInput(text, currency, locale);
	if (!parsed.ok) return parsed;
	if (parsed.minor === 0) return { ok: false, error: 'zero' };
	return { ok: true, minor: Math.abs(parsed.minor) * (sourceAmount < 0 ? -1 : 1) };
}

/** The allocation as the user types it: its magnitude, no sign. */
export function allocationText(minor: number, currency: string, locale: string): string {
	return formatMoney(Math.abs(minor), currency, { locale, showPlus: false });
}

/**
 * What the user typed as the amount a counter-leg receives: unsigned (the server gives it the
 * sign), in the counter-account's currency. Zero is no amount.
 */
export function parseReceivedAmount(text: string, currency: string, locale: string): Allocation {
	const parsed = parseMoneyInput(text, currency, locale);
	if (!parsed.ok) return parsed;
	if (parsed.minor === 0) return { ok: false, error: 'zero' };
	return { ok: true, minor: Math.abs(parsed.minor) };
}

const ALLOCATION_MESSAGES: Readonly<Record<AllocationError, string>> = {
	empty: 'Enter an amount.',
	invalid: 'This is not an amount.',
	ambiguous: 'Write the decimals out: this could be a thousands group or a decimal.',
	too_many_decimals: 'Too many decimals for this currency.',
	too_large: 'This amount is too large.',
	zero: 'An entry is never for nothing.'
};

export function allocationMessage(error: AllocationError): string {
	return ALLOCATION_MESSAGES[error];
}
