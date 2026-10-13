// What the panel shows of a unit under a draft: one view per entry (the preview's row when there
// is one, else the entry as stored), the state the commit leads to in words, and the consequences
// grouped by effect (patterns §6). Pure: it reads what the server said and the draft's choices,
// and decides nothing.
import type { Entry, Money } from '#lib/types/domain.js';
import {
	Draft,
	FIELD_NAMES,
	type FieldEdit,
	type FieldName,
	type FieldValue,
	type ShownBasis
} from './draft.js';
import {
	asKey,
	describeKey,
	isProposalPass,
	keyOf,
	type Evidence,
	type RuleNames
} from './evidence.js';
import type {
	ConsequenceKind,
	PreviewRow,
	Unit,
	UnitConsequence,
	UnitPreview,
	UnitState
} from './types.js';

export type FieldView = {
	name: FieldName;
	value: FieldValue;
	evidence: Evidence | null;
	/** the value is a proposal (italic, patterns §4.3) */
	proposal: boolean;
	edit: FieldEdit | undefined;
	/** the key of the proposal shown for this value: named when the user picks that very value */
	shown: ShownBasis | null;
	/** "Reset to proposal" applies: the value is decided and not already reset */
	canReset: boolean;
};

export type EntryView = {
	id: number;
	/** a row the draft creates (a temporary id) */
	isNew: boolean;
	/** the residual of its source: the original entry, whose amount is what the others leave */
	original: boolean;
	/** the source transaction the entry belongs to (of its source entry, for a new row) */
	sourceId: number | null;
	/** the source has more than one entry: a split */
	inSplit: boolean;
	stored: Entry | null;
	row: PreviewRow | null;
	accountId: number;
	/** null: a new split whose amount has not been entered */
	amount: Money | null;
	/** the amount the source transaction had: what the split divides */
	sourceAmount: Money | null;
	description: string | null;
	note: string | null;
	type: string | null;
	fields: Record<FieldName, FieldView>;
	flags: readonly string[];
	/** its amount is an allocation the user sets: a split row or a stored entry of a split */
	amountEditable: boolean;
	removable: boolean;
};

const STORED_VALUE: Record<FieldName, (e: Entry) => FieldValue> = {
	type: (e) => e.type,
	payee: (e) => e.payee_id,
	category: (e) => e.category_id,
	counter_account: (e) => e.counter_account_id
};

function storedKey(entry: Entry, name: FieldName) {
	return name === 'counter_account'
		? (keyOf(entry.derivation, 'counter_account') ?? keyOf(entry.derivation, 'counterpart'))
		: keyOf(entry.derivation, name);
}

function fieldView(
	name: FieldName,
	draft: Draft,
	id: number,
	rules: RuleNames,
	locale: string,
	row: PreviewRow | null,
	stored: Entry | null
): FieldView {
	const edit = draft.fieldEdit(id, name);
	let value: FieldValue = null;
	let key = null;
	let proposal = false;
	const out = row?.fields[name];
	if (out) {
		value = out.value;
		key = asKey(out.key);
		proposal = out.is_proposal;
	} else if (stored) {
		value = STORED_VALUE[name](stored);
		key = storedKey(stored, name);
		proposal = key !== null && isProposalPass(key.pass);
	} else if (edit?.mode === 'fixed') {
		value = edit.value;
	}
	return {
		name,
		value,
		evidence: describeKey(key, rules, locale),
		proposal,
		edit,
		shown:
			key && proposal
				? { pass: key.pass, basis: (key.basis as Record<string, unknown>) ?? {} }
				: null,
		canReset: value !== null && !proposal && edit?.mode !== 'reresolve'
	};
}

/** The entries to show: what the preview says is in the unit, else the unit as stored. */
export function entryViews(args: {
	unit: Unit;
	draft: Draft;
	preview: UnitPreview | null;
	rules: RuleNames;
	locale: string;
}): EntryView[] {
	const { unit, draft, preview, rules, locale } = args;
	const stored = new Map(unit.entries.map((e) => [e.id, e]));
	const sourceOf = (entryId: number) => stored.get(entryId)?.source_transaction_id ?? null;

	// the rows in the server's order, or the entries as stored (an untouched first look)
	type Base = { id: number; row: PreviewRow | null };
	let base: Base[];
	if (preview) {
		base = preview.rows.filter((r) => r.in_unit).map((r) => ({ id: r.id, row: r }));
	} else {
		base = unit.entries.map((e) => ({ id: e.id, row: null }));
	}
	base = base.filter((b) => !draft.isRemoved(b.id));
	const shown = new Set(base.map((b) => b.id));
	for (const split of draft.splits)
		if (!shown.has(split.id)) base.push({ id: split.id, row: null });

	// the original of a source: the preview says, else the lowest stored id of the source
	const lowest = new Map<number, number>();
	for (const e of unit.entries) {
		if (e.source_transaction_id === null) continue;
		lowest.set(
			e.source_transaction_id,
			Math.min(lowest.get(e.source_transaction_id) ?? e.id, e.id)
		);
	}
	const sourceIds = base.map((b) => {
		const split = draft.splits.find((s) => s.id === b.id);
		return b.row?.source_transaction_id ?? (split ? sourceOf(split.sourceEntryId) : sourceOf(b.id));
	});
	const counts = new Map<number, number>();
	for (const s of sourceIds) if (s !== null) counts.set(s, (counts.get(s) ?? 0) + 1);

	return base.map((b, i) => {
		const entry = stored.get(b.id) ?? null;
		const split = draft.splits.find((s) => s.id === b.id) ?? null;
		const isNew = b.id < 0;
		const sourceId = sourceIds[i];
		const original = b.row
			? b.row.original
			: !isNew && sourceId !== null && lowest.get(sourceId) === b.id;
		const inSplit = sourceId !== null && (counts.get(sourceId) ?? 0) > 1;
		const edit = draft.edit(b.id);
		const sourceEntry = split ? (stored.get(split.sourceEntryId) ?? null) : entry;
		const currency = b.row?.amount.currency ?? sourceEntry?.amount.currency ?? 'EUR';
		const splitOut = preview?.splits.find(
			(s) => s.residual_entry_id === b.id || s.entry_ids.includes(b.id)
		);
		let amount: Money | null;
		if (b.row) amount = b.row.amount;
		else if (isNew) amount = edit.amount == null ? null : { amount: edit.amount, currency };
		else amount = entry?.amount ?? null;
		const fields = Object.fromEntries(
			FIELD_NAMES.map((name) => [name, fieldView(name, draft, b.id, rules, locale, b.row, entry)])
		) as Record<FieldName, FieldView>;
		const view: EntryView = {
			id: b.id,
			isNew,
			original,
			sourceId,
			inSplit,
			stored: entry,
			row: b.row,
			accountId: b.row?.account_id ?? sourceEntry?.account_id ?? 0,
			amount,
			sourceAmount: splitOut?.source_amount ?? null,
			description:
				edit.description !== undefined
					? edit.description
					: (b.row?.description ?? entry?.description ?? null),
			note: edit.note !== undefined ? edit.note : (b.row?.note ?? entry?.note ?? null),
			type: fields.type.value === null ? null : String(fields.type.value),
			fields,
			flags: b.row?.review_flags ?? entry?.review_flags ?? [],
			amountEditable: !original,
			removable: !original
		};
		return view;
	});
}

/** The words for the state a commit leads to (patterns §6: "confirmed", "waits for its partner"…). */
export const RESULT_TEXT: Readonly<Record<UnitState['reasons'][number], string>> = {
	incomplete: 'Stays unclassified',
	unpaired_transfer: 'Waits for its partner',
	non_standing_keys: 'Proposals to check'
};

export function resultText(state: UnitState): string {
	if (state.confirmed) return 'Confirmed';
	const words = state.reasons.map((r) => RESULT_TEXT[r] ?? r);
	return words.length > 0 ? words.join(' · ') : 'Stays in review';
}

export const CONSEQUENCE_ORDER: readonly ConsequenceKind[] = [
	'created',
	'changed',
	'returns_to_review',
	'deleted',
	'left_behind',
	'unpaired'
];

export const CONSEQUENCE_TITLE: Readonly<Record<ConsequenceKind, string>> = {
	created: 'Created',
	changed: 'Changed',
	returns_to_review: 'Returns to review',
	deleted: 'Deleted',
	left_behind: 'Left behind',
	unpaired: 'Unpaired'
};

export type ConsequenceGroup = {
	kind: ConsequenceKind;
	title: string;
	items: UnitConsequence[];
};

/** The consequences by effect, in the order of patterns §6, empty groups left out. */
export function consequenceGroups(preview: UnitPreview | null): ConsequenceGroup[] {
	if (!preview) return [];
	return CONSEQUENCE_ORDER.flatMap((kind) => {
		const items = preview.consequences.filter((c) => c.kind === kind);
		return items.length > 0 ? [{ kind, title: CONSEQUENCE_TITLE[kind], items }] : [];
	});
}

/**
 * A preview row as an entry, so the compact row of the ledger can draw it. The text of an entry
 * the unit holds is its own; one outside the unit has none beyond its description.
 */
export function previewRowEntry(row: PreviewRow, base: Entry | null = null): Entry {
	const value = (name: FieldName) => row.fields[name]?.value ?? null;
	const type = value('type');
	return {
		id: row.id,
		version: row.version ?? 0,
		account_id: row.account_id,
		booked_on: row.booked_on,
		value_on: row.value_on,
		amount: row.amount,
		type: type === 'flow' || type === 'transfer' ? type : null,
		description: row.description,
		note: row.note,
		display_text: base?.display_text ?? row.description,
		payee_id: typeof value('payee') === 'number' ? (value('payee') as number) : null,
		category_id: typeof value('category') === 'number' ? (value('category') as number) : null,
		counter_account_id:
			typeof value('counter_account') === 'number' ? (value('counter_account') as number) : null,
		counterpart_entry_id: row.counterpart_entry_id,
		source_transaction_id: row.source_transaction_id,
		source: base?.source ?? null,
		authored: base?.authored ?? false,
		derivation: row.derivation,
		unit_key: row.unit_key,
		partner: base?.partner ?? null,
		document_id: base?.document_id ?? null,
		review_flags: row.review_flags as Entry['review_flags'],
		tag_ids: row.tag_ids
	};
}

/** The proposal to name as the basis when the user picks `value`: only when it is the value shown. */
export function shownFor(field: FieldView, value: FieldValue): ShownBasis | null {
	return value !== null && field.shown !== null && field.value === value ? field.shown : null;
}
