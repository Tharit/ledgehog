// The client's draft of a unit (spec §6, architecture §4.1, §6.3): the user's choices laid over
// the unit as loaded. Pure and immutable: every operation returns the next draft. It decides
// nothing about what the choices imply (the server's preview does); it only remembers what the
// user chose and turns it into the request. A field is `keep` (untouched), `fixed` (the user's
// value) or `reresolve` (the passes decide again); a split row has a temporary (negative) id.
import { formatMoney, parseMoneyInput, type MoneyParseError } from '#lib/format/index.js';
import type { DraftEntryRequest, FieldDraftRequest, Unit, UnitDraftRequest } from './types.js';

export const FIELD_NAMES = ['type', 'payee', 'category', 'counter_account'] as const;
export type FieldName = (typeof FIELD_NAMES)[number];
export type FieldValue = number | string | null;

/** The key of the proposal the user was shown when they chose the value it equals. */
export type ShownBasis = { pass: string; basis: Record<string, unknown> };

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
};

/** A row the draft creates: it splits the source of a stored entry. */
export type NewSplit = { id: number; sourceEntryId: number };

type Base = { description: string | null; note: string | null; amount: number };

type State = {
	anchorId: number;
	versions: Readonly<Record<number, number>>;
	base: ReadonlyMap<number, Base>;
	edits: ReadonlyMap<number, EntryEdit>;
	splits: readonly NewSplit[];
	removed: readonly number[];
	reresolveAll: boolean;
};

const EMPTY: EntryEdit = { fields: {} };

function baseOf(unit: Pick<Unit, 'entries'>): Map<number, Base> {
	return new Map(
		unit.entries.map((e) => [
			e.id,
			{ description: e.description, note: e.note, amount: e.amount.amount }
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
		edit.amount === undefined
	);
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
			reresolveAll: false
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

	/** Has the user changed anything? A draft that has not is still committable (it accepts). */
	get isDirty(): boolean {
		return (
			this.#s.reresolveAll ||
			this.#s.splits.length > 0 ||
			this.#s.removed.length > 0 ||
			this.#s.edits.size > 0
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

	/** The temporary id the next split gets. */
	get nextTempId(): number {
		return Math.min(0, ...this.#s.splits.map((s) => s.id)) - 1;
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
		return this.#edited(id, (e) => ({
			...e,
			fields: { ...e.fields, [field]: { mode: 'fixed', value, shown } }
		}));
	}

	/** "Reset to proposal": the passes decide this field again, a decided value included. */
	resetField(id: number, field: FieldName): Draft {
		return this.#edited(id, (e) => ({
			...e,
			fields: { ...e.fields, [field]: { mode: 'reresolve' } }
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
		return this.#with({
			splits: [...this.#s.splits, { id, sourceEntryId }],
			edits: new Map(this.#s.edits).set(id, { fields: {}, amount: null })
		});
	}

	/** Remove a split row (its amount returns to the residual) or a stored entry of a split. */
	removeSplit(id: number): Draft {
		const edits = new Map(this.#s.edits);
		edits.delete(id);
		if (id < 0) {
			return this.#with({ splits: this.#s.splits.filter((s) => s.id !== id), edits });
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
		return this.#edited(id, (e) => ({
			...e,
			fields: {
				...without(without(e.fields, 'payee'), 'category'),
				type: { mode: 'fixed', value: 'transfer', shown: null },
				...(counterAccountId === null
					? {}
					: { counter_account: { mode: 'fixed', value: counterAccountId, shown: null } })
			}
		}));
	}

	/** Turn a transfer into a flow; the category and payee are proposed afresh. */
	convertToFlow(id: number): Draft {
		return this.#edited(id, (e) => ({
			...e,
			fields: {
				...without(e.fields, 'counter_account'),
				type: { mode: 'fixed', value: 'flow', shown: null }
			}
		}));
	}

	/** Resolve the whole unit afresh (spec §5.9); Cancel undoes it. */
	reresolve(on = true): Draft {
		if (on === this.#s.reresolveAll) return this;
		return this.#with({ reresolveAll: on });
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
		const splits = this.#s.splits.filter((s) => ids.has(s.sourceEntryId));
		const keep = new Set([...ids, ...splits.map((s) => s.id)]);
		const edits = new Map<number, EntryEdit>();
		for (const [id, edit] of this.#s.edits) {
			if (!keep.has(id)) continue;
			const next = { ...edit };
			const was = base.get(id);
			if (was) {
				if (next.description !== undefined && normaliseText(next.description) === was.description) {
					delete next.description;
				}
				if (next.note !== undefined && normaliseText(next.note) === was.note) delete next.note;
				if (next.amount === was.amount) delete next.amount;
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
			reresolveAll: this.#s.reresolveAll
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
