// The client's draft of a unit (spec §6, architecture §4.1, §6.3): the user's choices laid over
// the unit as loaded. Pure and immutable: every operation returns the next draft. It decides
// nothing about what the choices imply (the server's preview does); it only remembers what the
// user chose and turns it into the request. A field is `keep` (untouched), `fixed` (the user's
// value) or `reresolve` (the passes decide again); a split row has a temporary (negative) id.
import { formatMoney, parseMoneyInput, type MoneyParseError } from '#lib/format/index.js';
import { keyOf } from './evidence.js';
import type {
	DocumentDraftRequest,
	DraftEntryRequest,
	FieldDraftRequest,
	Unit,
	UnitDraftRequest
} from './types.js';

export const FIELD_NAMES = ['type', 'payee', 'category', 'counter_account'] as const;
export type FieldName = (typeof FIELD_NAMES)[number];
export type FieldValue = number | string | null;

/** The key of the proposal the user was shown when they chose the value it equals. */
export type ShownBasis = { pass: string; basis: Record<string, unknown> };

/** The partner of a transfer leg: the user's pick, or "pair it by the rules again". Absent: as it stands. */
export type PairingEdit =
	| { mode: 'pick'; partnerEntryId: number }
	| { mode: 'reresolve' }
	/**
	 * The other side is created by the commit (an unsynced counter-account): `tempId` is the
	 * client-issued negative id of the row the preview shows for it, stable for the draft's life;
	 * `receivedAmount` is what a cross-currency counter-leg receives (unsigned minor units).
	 */
	| { mode: 'counter_leg'; tempId: number; receivedAmount: number | null };

/**
 * What the draft says of the transaction's document, on its original entry (spec §5.8, §6). Absent:
 * `keep`, the link as it stands. A pick and a split name the version the user saw.
 */
export type DocumentEdit =
	| { mode: 'pick'; documentId: number; version: number }
	| { mode: 'none' }
	| { mode: 'reresolve' }
	| { mode: 'split_along_lines'; documentId: number; version: number };

/** The line of a document a new row was made from. */
export type DocumentLineRef = { documentId: number; lineNo: number };

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
	/** the document decision (the original entry of a transaction only) */
	document?: DocumentEdit;
	/** the proposed split along the lines of the linked document is refused */
	declineSplit?: boolean;
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
	/** the row is a line of the transaction's document (the split along the lines) */
	documentLine?: DocumentLineRef;
	/** the amount the row was taken over with from the preview's proposal; absent: the user's own row */
	adopted?: number;
};

type Base = {
	description: string | null;
	note: string | null;
	amount: number;
	/** the values the entry stores for the derived fields */
	fields: Readonly<Record<FieldName, FieldValue>>;
	/** the entry stores "no payee" as the user's decision (an empty payee with the `user` key) */
	noPayee: boolean;
	/** the tags the entry stores */
	tags: readonly number[];
	sourceId: number | null;
};

type State = {
	anchorId: number;
	versions: Readonly<Record<number, number>>;
	base: ReadonlyMap<number, Base>;
	edits: ReadonlyMap<number, EntryEdit>;
	splits: readonly NewSplit[];
	removed: readonly number[];
	reresolveAll: boolean;
	/** how many rows of the split along the lines were taken over from the proposal */
	adoptedCount: number;
};

const EMPTY: EntryEdit = { fields: {} };

function baseOf(unit: Pick<Unit, 'entries'>): Map<number, Base> {
	return new Map(
		unit.entries.map((e) => [
			e.id,
			{
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
				tags: [...e.tag_ids],
				sourceId: e.source_transaction_id
			}
		])
	);
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
		edit.pairing === undefined &&
		edit.document === undefined &&
		edit.declineSplit === undefined
	);
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
			base: baseOf(unit),
			edits: new Map(),
			splits: [],
			removed: [],
			reresolveAll: false,
			adoptedCount: 0
		});
	}

	#with(change: Partial<State>): Draft {
		return new Draft({ ...this.#s, ...change });
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

	/**
	 * A row taken over from the proposed split along the lines that the user has not touched: it is
	 * the proposal, not an edit.
	 */
	#pristine(id: number): boolean {
		const split = this.#s.splits.find((s) => s.id === id);
		if (split?.adopted === undefined) return false;
		const edit = this.edit(id);
		return (
			edit.amount === split.adopted &&
			Object.keys(edit.fields).length === 0 &&
			edit.description === undefined &&
			edit.note === undefined &&
			edit.tags === undefined
		);
	}

	/** Rows of the split along the lines were removed or added since the proposal was taken over. */
	get #lineRowsChanged(): boolean {
		const adopted = this.#s.splits.filter((s) => s.adopted !== undefined).length;
		const lines = this.#s.splits.filter((s) => s.documentLine !== undefined).length;
		return adopted !== this.#s.adoptedCount || lines !== adopted;
	}

	/** Has the user edited anything? A draft that has not is still committable (it accepts). */
	get isDirty(): boolean {
		if (this.hasOtherChanges) return true;
		return [...this.#s.edits.keys()].some((id) => !this.#pristine(id));
	}

	/**
	 * Has the user changed anything but the derived fields? Whether a field edit changes anything
	 * is for the preview to say (`effectiveChanged`, view.ts): an edit can end in the stored value.
	 */
	get hasOtherChanges(): boolean {
		if (this.#s.reresolveAll || this.#s.removed.length > 0) return true;
		if (this.#s.splits.some((s) => !this.#pristine(s.id)) || this.#lineRowsChanged) return true;
		for (const [id, edit] of this.#s.edits) {
			if (this.#pristine(id)) continue;
			if (
				edit.description !== undefined ||
				edit.note !== undefined ||
				edit.amount !== undefined ||
				edit.tags !== undefined ||
				edit.pairing !== undefined ||
				edit.document !== undefined ||
				edit.declineSplit !== undefined
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

	#edited(id: number, change: (edit: EntryEdit) => EntryEdit): Draft {
		const next = change(this.edit(id));
		if (isEmpty(next) && !this.#s.edits.has(id)) return this;
		const edits = new Map(this.#s.edits);
		if (isEmpty(next)) edits.delete(id);
		else edits.set(id, next);
		return this.#with({ edits });
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
		const stored = this.#s.base.get(id);
		return this.#edited(id, (e) => ({
			...unpaired(e, field),
			fields: withField(e.fields, stored, field, value, shown)
		}));
	}

	/** "Reset to proposal": the passes decide this field again, a decided value included. */
	resetField(id: number, field: FieldName): Draft {
		return this.#edited(id, (e) => ({
			...unpaired(e, field),
			fields: { ...e.fields, [field]: { mode: 'reresolve' } }
		}));
	}

	/** The partner the user chose for a transfer leg (the offers list, spec §5.7). */
	pickPartner(id: number, partnerEntryId: number): Draft {
		if (!this.#s.base.has(id)) return this;
		return this.#edited(id, (e) => ({ ...e, pairing: { mode: 'pick', partnerEntryId } }));
	}

	/**
	 * The other side of a leg is created by the commit (spec §5.7). The temporary id is issued once
	 * and kept while the pick stands; picking again keeps it (and the amount received, unless one is given).
	 */
	pickCounterLeg(id: number, options: { receivedAmount?: number | null } = {}): Draft {
		if (!this.#s.base.has(id)) return this;
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
		if (!this.#s.base.has(id)) return this;
		return this.#edited(id, (e) => ({ ...e, pairing: { mode: 'reresolve' } }));
	}

	/** Take a pairing edit back: the leg is as it stands. */
	clearPairing(id: number): Draft {
		return this.#edited(id, (e) => without(e, 'pairing'));
	}

	pairingEdit(id: number): PairingEdit | undefined {
		return this.edit(id).pairing;
	}

	/** Does any leg hold a picked counter-leg? */
	get hasCounterLeg(): boolean {
		return [...this.#s.edits.values()].some((e) => e.pairing?.mode === 'counter_leg');
	}

	/** Does any leg hold a picked partner? */
	get hasPick(): boolean {
		return [...this.#s.edits.values()].some((e) => e.pairing?.mode === 'pick');
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
		const stored = this.#s.base.get(id);
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
		const base = this.#s.base.get(id);
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
		const base = this.#s.base.get(id);
		if (base !== undefined && minor === base.amount) {
			return this.#edited(id, (e) => without(e, 'amount'));
		}
		return this.#edited(id, (e) => ({ ...e, amount: minor }));
	}

	/** A new row splitting the source of `sourceEntryId` (a stored entry); its amount is entered next. */
	addSplit(sourceEntryId: number): Draft {
		const id = this.nextTempId;
		const tags = this.#s.base.get(sourceEntryId)?.tags ?? [];
		// the row shows what the original shows now (its draft tags); the server copies the stored
		// ones, so the difference goes into the row's own change. After this the row is independent.
		const shown = this.effectiveTagIds(sourceEntryId);
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

	/** The tags an entry starts from: what it stores, or for a split row what it inherits. */
	#startTags(id: number): readonly number[] {
		return this.#s.base.get(id)?.tags ?? this.#s.splits.find((s) => s.id === id)?.tags ?? [];
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
		if (!this.#s.base.has(id) && !this.isNew(id)) return this;
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
		return changed ? this.#with({ edits }) : this;
	}

	/** Remove a split row (its amount returns to the residual) or a stored entry of a split. */
	removeSplit(id: number): Draft {
		const edits = new Map(this.#s.edits);
		edits.delete(id);
		if (id < 0) {
			const gone = this.#s.splits.find((s) => s.id === id);
			const splits = this.#s.splits.filter((s) => s.id !== id);
			const next = this.#with({ splits, edits });
			// the last row of the split along the lines: nothing left to echo, so the server would
			// propose it again: the user's word is "one entry"
			if (gone?.documentLine && !splits.some((s) => s.documentLine)) {
				return next.declineSplit(gone.sourceEntryId);
			}
			return next;
		}
		if (id === this.#s.anchorId || this.#s.removed.includes(id)) return this;
		return this.#with({ removed: [...this.#s.removed, id], edits });
	}

	/** Keep a stored entry that was marked for removal. */
	restoreSplit(id: number): Draft {
		return this.#with({ removed: this.#s.removed.filter((r) => r !== id) });
	}

	/** Turn a flow into a transfer; `counterAccountId` null leaves the destination to be chosen. */
	convertToTransfer(id: number, counterAccountId: number | null): Draft {
		const stored = this.#s.base.get(id);
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
		const stored = this.#s.base.get(id);
		return this.#edited(id, (e) => ({
			...unpaired(e, 'type'),
			fields: withField(without(e.fields, 'counter_account'), stored, 'type', 'flow', null)
		}));
	}

	// ---- the document of the transaction (spec §5.8, §6) --------------------------------------

	documentEdit(id: number): DocumentEdit | undefined {
		return this.edit(id).document;
	}

	/** The proposed split along the lines is refused for this original entry. */
	declinesSplit(id: number): boolean {
		return this.edit(id).declineSplit === true;
	}

	/** The rows made from a line of a document (the split along the lines). */
	get lineRows(): readonly NewSplit[] {
		return this.#s.splits.filter((s) => s.documentLine !== undefined);
	}

	/** Has the user changed the rows of the split along the lines, or removed one? */
	get lineRowsEdited(): boolean {
		return (
			this.lineRows.some((s) => !this.#pristine(s.id)) ||
			(this.lineRows.length > 0 && this.#lineRowsChanged)
		);
	}

	/** The draft without the rows of the split along the lines (they belong to a document no longer in play). */
	#withoutLineRows(): { splits: NewSplit[]; edits: Map<number, EntryEdit> } {
		const gone = new Set(this.lineRows.map((s) => s.id));
		const edits = new Map(this.#s.edits);
		for (const id of gone) edits.delete(id);
		return { splits: this.#s.splits.filter((s) => !gone.has(s.id)), edits };
	}

	/** Set (or with `undefined` take away) the document decision of an original entry; the line rows go. */
	#decide(id: number, change: Partial<Pick<EntryEdit, 'document' | 'declineSplit'>>): Draft {
		if (!this.#s.base.has(id)) return this;
		const lines = this.#withoutLineRows();
		const base = this.#with({ splits: lines.splits, edits: lines.edits, adoptedCount: 0 });
		return base.#edited(id, (e) => {
			const next = { ...e, ...change };
			if (next.document === undefined) delete next.document;
			if (next.declineSplit !== true) delete next.declineSplit;
			return next;
		});
	}

	/** The user picked this document for the transaction (the version is the one they saw). */
	pickDocument(id: number, documentId: number, version: number): Draft {
		return this.#decide(id, {
			document: { mode: 'pick', documentId, version },
			declineSplit: false
		});
	}

	/** "None of these", "Commit without a document": the user's decision that there is no document. */
	noDocument(id: number): Draft {
		return this.#decide(id, { document: { mode: 'none' }, declineSplit: false });
	}

	/** Drop the decision and the link: matching decides afresh. */
	reresolveDocument(id: number): Draft {
		return this.#decide(id, { document: { mode: 'reresolve' }, declineSplit: false });
	}

	/** Back to what the server proposes: no decision, the proposed split proposed again. */
	resetDocument(id: number): Draft {
		return this.#decide(id, { document: undefined, declineSplit: false });
	}

	/** The rows of the split along the lines go back to what the server proposes (the decision stays). */
	resetSplit(id: number): Draft {
		return this.#decide(id, { document: this.edit(id).document, declineSplit: false });
	}

	/**
	 * Split the transaction along the lines of this document, replacing an existing split: the
	 * client's own rows for the transaction go, and so do removals of its entries (the server
	 * deletes the others).
	 */
	splitAlongLines(id: number, documentId: number, version: number): Draft {
		const stored = this.#s.base.get(id);
		if (!stored) return this;
		const sameSource = (entryId: number) => {
			const source = this.#s.base.get(entryId)?.sourceId ?? null;
			return source !== null && source === stored.sourceId;
		};
		const dropped = this.#s.splits.filter((s) => sameSource(s.sourceEntryId));
		const edits = new Map(this.#s.edits);
		for (const s of dropped) edits.delete(s.id);
		const cleared = this.#with({
			splits: this.#s.splits.filter((s) => !dropped.includes(s)),
			edits,
			removed: this.#s.removed.filter((r) => !sameSource(r))
		});
		return cleared.#decide(id, {
			document: { mode: 'split_along_lines', documentId, version },
			declineSplit: false
		});
	}

	/**
	 * "Keep one entry": the proposed split is refused. A split the user chose along the lines goes
	 * back to the plain pick of that document.
	 */
	declineSplit(id: number): Draft {
		const held = this.edit(id).document;
		const document: DocumentEdit | undefined =
			held?.mode === 'split_along_lines'
				? { mode: 'pick', documentId: held.documentId, version: held.version }
				: held;
		return this.#decide(id, { document, declineSplit: true });
	}

	/** Forget a pick of a document that no longer exists, changed or was taken (any pick: no id). */
	dropDocument(documentId?: number): Draft {
		return [...this.#s.edits].reduce<Draft>((draft, [id, edit]) => {
			const held = edit.document;
			const names =
				(held?.mode === 'pick' || held?.mode === 'split_along_lines') &&
				(documentId === undefined || held.documentId === documentId);
			return names ? draft.#decide(id, { document: undefined }) : draft;
		}, this);
	}

	/**
	 * Take the rows of the preview that are made from a line of the document into the draft, and
	 * drop the draft's rows the server no longer has (their document is no longer the
	 * transaction's). Once the draft holds a row of the split it echoes all of them: the split is
	 * the client's. `rows` are the preview's new rows with a `document_line`.
	 */
	syncLineRows(
		rows: readonly {
			id: number;
			sourceEntryId: number;
			amount: number;
			documentLine: DocumentLineRef;
		}[]
	): Draft {
		const present = new Set(rows.map((r) => r.id));
		const held = new Set(this.#s.splits.map((s) => s.id));
		// only what the server dropped: a row the client left out of the request (no amount) is its own
		const missing = this.lineRows.filter(
			(s) => !present.has(s.id) && this.#s.edits.get(s.id)?.amount != null
		);
		const fresh = rows.filter((r) => !held.has(r.id));
		if (missing.length === 0 && fresh.length === 0) return this;
		const gone = new Set(missing.map((s) => s.id));
		const edits = new Map(this.#s.edits);
		for (const id of gone) edits.delete(id);
		const splits = this.#s.splits.filter((s) => !gone.has(s.id));
		for (const row of fresh) {
			splits.push({
				id: row.id,
				sourceEntryId: row.sourceEntryId,
				tags: this.#s.base.get(row.sourceEntryId)?.tags ?? [],
				documentLine: row.documentLine,
				adopted: row.amount
			});
			edits.set(row.id, { fields: {}, amount: row.amount });
		}
		const lines = splits.filter((s) => s.adopted !== undefined).length;
		return this.#with({
			splits,
			edits,
			adoptedCount: fresh.length > 0 ? lines : Math.max(0, Math.min(this.#s.adoptedCount, lines))
		});
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
		return changed ? this.#with({ reresolveAll: true, edits }) : this;
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
	 * a split of a source that left) is dropped; the versions are the ones just read.
	 */
	rebase(unit: Pick<Unit, 'anchor_entry_id' | 'entries'>): Draft {
		const ids = new Set(unit.entries.map((e) => e.id));
		const base = baseOf(unit);
		// a new row inherits what its source stores now
		const splits = this.#s.splits
			.filter((s) => ids.has(s.sourceEntryId))
			.map((s) => ({ ...s, tags: base.get(s.sourceEntryId)?.tags ?? s.tags }));
		const keep = new Set([...ids, ...splits.map((s) => s.id)]);
		const edits = new Map<number, EntryEdit>();
		for (const [id, edit] of this.#s.edits) {
			if (!keep.has(id)) continue;
			const next = { ...edit };
			const was = base.get(id);
			const start = was?.tags ?? splits.find((s) => s.id === id)?.tags;
			if (start && next.tags) {
				// a tag someone else has put on or taken off meanwhile is no longer a change
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
				// a value someone else has stored meanwhile is no longer a change
				next.fields = Object.fromEntries(
					Object.entries(next.fields).filter(
						([name, f]) =>
							!(f.mode === 'fixed' && f.shown === null && isStored(was, name as FieldName, f.value))
					)
				) as EntryEdit['fields'];
			}
			if (!isEmpty(next)) edits.set(id, next);
		}
		return new Draft({
			anchorId: ids.has(this.#s.anchorId) ? this.#s.anchorId : unit.anchor_entry_id,
			versions: versionsOf(unit),
			base,
			edits,
			splits,
			removed: this.#s.removed.filter((id) => ids.has(id) && id !== unit.anchor_entry_id),
			reresolveAll: this.#s.reresolveAll,
			adoptedCount: this.#s.adoptedCount
		});
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
		// a split along the lines deletes the other entries of a split: the anchor is never deleted,
		// so the draft is anchored on the original entry it splits
		const splitting = ids.find((id) => this.edit(id).document?.mode === 'split_along_lines');
		return {
			anchor_entry_id: splitting ?? this.#s.anchorId,
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
		const line = this.#s.splits.find((s) => s.id === id)?.documentLine;
		if (line) body.document_line = { document_id: line.documentId, line_no: line.lineNo };
		const document = documentRequest(edit);
		if (document) body.document = document;
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

function documentRequest(edit: EntryEdit): DocumentDraftRequest | undefined {
	const held = edit.document;
	if (!held && !edit.declineSplit) return undefined;
	const body: DocumentDraftRequest = {
		mode: held?.mode ?? 'keep',
		decline_split: edit.declineSplit === true
	};
	if (held?.mode === 'pick' || held?.mode === 'split_along_lines') {
		body.document_id = held.documentId;
		body.document_version = held.version;
	}
	return body;
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
