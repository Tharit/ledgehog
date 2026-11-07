// What the panel shows of a unit under a draft: one view per entry (the preview's row when there
// is one, else the entry as stored), the state the commit leads to in words, and the consequences
// grouped by effect (patterns §6). Pure: it reads what the server said and the draft's choices,
// and decides nothing.
import type { Entry, Money } from '#lib/types/domain.js';
import {
	Draft,
	FIELD_NAMES,
	type PairingEdit,
	type FieldEdit,
	type FieldName,
	type FieldValue,
	type ShownBasis
} from './draft.js';
import {
	asKey,
	describeKey,
	isPartnerBasis,
	isProposalPass,
	keyOf,
	type DerivationKey,
	type Evidence,
	type KeyContext,
	type RuleNames
} from './evidence.js';
import type {
	ConsequenceKind,
	PreviewRow,
	Unit,
	UnitConsequence,
	UnitPreview,
	UnitState,
	UnitTransfer
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
	/** "Reset to proposal" applies: the value shown (or its key) differs from the stored one, by an edit */
	canReset: boolean;
	/** the X applies: the value is the user's own decision (a payee, which may be empty: any value, X makes it empty) */
	clearable: boolean;
	/**
	 * The user's draft changes a value a RULE set (the stored key's pass is `rule`, the value
	 * shown is another and no rule says it): the offer to create a rule from the transaction
	 * (spec §6). Never for what history, the model, the user or the own-account pass set.
	 */
	changedFromRule: boolean;
};

/** The fields a rule can set that the offer to create a rule covers (spec §6). */
const RULE_FIELDS: readonly FieldName[] = ['type', 'payee', 'category'];

export type EntryView = {
	id: number;
	/** a row the draft creates (a temporary id) */
	isNew: boolean;
	/** the residual of its source: the original entry, whose amount is what the others leave */
	original: boolean;
	/** the source transaction the entry belongs to (of its source entry, for a new row) */
	sourceId: number | null;
	/** the stored entry whose source it belongs to: the entry itself, or for a new row the one it splits */
	fromEntryId: number;
	/** the source has more than one entry: a split */
	inSplit: boolean;
	stored: Entry | null;
	row: PreviewRow | null;
	accountId: number | null;
	/** null: a new split whose amount has not been entered */
	amount: Money | null;
	/** the amount the source transaction had: what the split divides */
	sourceAmount: Money | null;
	/** what the entry is, from its source (a booking's line text); never the user's to edit */
	sourceText: string | null;
	description: string | null;
	note: string | null;
	type: string | null;
	fields: Record<FieldName, FieldView>;
	/** the tags the entry will have: the preview's row when it is the draft's own, else the draft applied */
	tagIds: readonly number[];
	flags: readonly string[];
	/** a transfer leg's state, partner and offers as the preview left it (absent: not told) */
	transfer: UnitTransfer | null;
	/** how the pair was made, from the pair key ("matched automatically", "set by you"); null when there is none */
	pairEvidence: Evidence | null;
	/** the user has picked a partner for this leg, or the creation of its other side */
	picked: boolean;
	/** the draft's pairing edit of this leg, if any */
	pairing: PairingEdit | null;
	/**
	 * The row is the counter-leg a commit creates (a synthetic row with a negative id the draft's
	 * splits do not own): shown read-only as a ghost group.
	 */
	counterLeg: boolean;
	/**
	 * The row is a booking (spec §5.8): the entry a document booked, or the counter-leg booked from a
	 * charge on a clearance account. Its type, amount and split are its source's: no convert, no
	 * split, no partner pick; payee, category, description, note and tags stay open.
	 */
	booking: { kind: 'document' | 'transfer'; id: number } | null;
	/**
	 * The row is the booking settling would make for the charge it names (a ghost: read-only, shown on
	 * the clearance account, written by settling, not by the commit).
	 */
	bookingFor: number | null;
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

/**
 * The key a stored field shows. A counter-account with no key of its own shows the pair key
 * (`viaPair`): the leg's counter-account is its partner's, and the pair says how it was made.
 */
function storedKeyOf(
	entry: Entry,
	name: FieldName
): { key: DerivationKey | null; viaPair: boolean } {
	if (name === 'counter_account') {
		const own = keyOf(entry.derivation, 'counter_account');
		if (own) return { key: own, viaPair: false };
		const pair = keyOf(entry.derivation, 'counterpart');
		return { key: pair, viaPair: pair !== null };
	}
	return { key: keyOf(entry.derivation, name), viaPair: false };
}

function storedKey(entry: Entry, name: FieldName) {
	return storedKeyOf(entry, name).key;
}

/** A key as identity: the pass, and for a rule which rule (the basis of a proposal is not one). */
function keyId(key: { pass: string; basis?: unknown } | null): string {
	if (key === null) return '';
	const basis = key.basis as { rule_id?: unknown } | null | undefined;
	return key.pass === 'rule' ? `rule:${String(basis?.rule_id)}` : key.pass;
}

/**
 * Does the preview's row end in another value (or another key) for the field than the entry
 * stores? This, not the existence of a draft edit, is what a change is: an X that lets the rule
 * propose the stored category again changes nothing. null: it cannot be told (no row, no entry).
 */
export function effectiveChanged(
	name: FieldName,
	row: PreviewRow | null,
	stored: Entry | null
): boolean | null {
	const out = row?.fields[name];
	if (!out || !stored) return null;
	return (
		out.value !== STORED_VALUE[name](stored) ||
		keyId(asKey(out.key)) !== keyId(storedKey(stored, name))
	);
}

function fieldView(
	name: FieldName,
	draft: Draft,
	id: number,
	rules: RuleNames,
	locale: string,
	row: PreviewRow | null,
	stored: Entry | null,
	accountName: (id: number) => string | undefined,
	booking: KeyContext = {}
): FieldView {
	const edit = draft.fieldEdit(id, name);
	let value: FieldValue = null;
	let key: DerivationKey | null = null;
	let viaPair = false;
	let proposal = false;
	const out = row?.fields[name];
	if (out) {
		value = out.value;
		key = asKey(out.key);
		proposal = out.is_proposal;
	} else if (stored) {
		value = STORED_VALUE[name](stored);
		({ key, viaPair } = storedKeyOf(stored, name));
		proposal = key !== null && isProposalPass(key.pass);
	} else if (edit?.mode === 'fixed') {
		value = edit.value;
	}
	const changed = effectiveChanged(name, row, stored);
	const storedNone =
		stored !== null && stored.payee_id === null && storedKey(stored, 'payee')?.pass === 'user';
	// without a preview only a fixed value can be compared with what is stored
	const fallback =
		edit?.mode === 'fixed' &&
		(stored === null ||
			edit.value !== STORED_VALUE[name](stored) ||
			(name === 'payee' && edit.value === null && !storedNone));
	// the value the draft leaves: the preview's, else a fixed one (without a preview to say)
	const effective = out ? out.value : edit?.mode === 'fixed' ? edit.value : value;
	const changedFromRule =
		stored !== null &&
		edit !== undefined &&
		RULE_FIELDS.includes(name) &&
		storedKey(stored, name)?.pass === 'rule' &&
		effective !== STORED_VALUE[name](stored) &&
		(out === undefined || key?.pass !== 'rule');
	return {
		name,
		value,
		evidence: describeKey(
			key,
			rules,
			locale,
			viaPair
				? {
						...booking,
						field: 'counterpart',
						partnerAccount: stored?.partner ? accountName(stored.partner.account_id) : undefined
					}
				: { ...booking, field: name }
		),
		proposal,
		edit,
		shown:
			key && proposal && value !== null
				? { pass: key.pass, basis: (key.basis as Record<string, unknown>) ?? {} }
				: null,
		canReset: edit !== undefined && (changed ?? fallback),
		clearable:
			value !== null &&
			(name === 'payee' ||
				(key?.pass === 'user' && !viaPair && !isPartnerBasis(key)) ||
				edit?.mode === 'fixed'),
		changedFromRule
	};
}

/** The account of the charge a counter-leg booking is booked from, as far as the unit tells. */
function chargeAccountOf(
	booking: { id: number; account_id?: number | null },
	preview: UnitPreview | null,
	stored: ReadonlyMap<number, Entry>
): number | null {
	return (
		booking.account_id ??
		preview?.rows.find((r) => r.id === booking.id)?.account_id ??
		stored.get(booking.id)?.account_id ??
		null
	);
}

/** The entries to show: what the preview says is in the unit, else the unit as stored. */
export function entryViews(args: {
	unit: Unit;
	draft: Draft;
	preview: UnitPreview | null;
	rules: RuleNames;
	locale: string;
	/** the preview shown is not the draft's own yet: the draft's tags are the newer word */
	stale?: boolean;
	/** an account's name, for the evidence of a pair ("paired with Cash") */
	accountName?: (id: number) => string | undefined;
}): EntryView[] {
	const {
		unit,
		draft,
		preview,
		rules,
		locale,
		stale = false,
		accountName = () => undefined
	} = args;
	const stored = new Map(unit.entries.map((e) => [e.id, e]));
	const previewRows = new Map((preview?.rows ?? []).map((r) => [r.id, r]));
	// a source entry is known as stored, else by its own preview row (a picked partner is the latter)
	const sourceOf = (entryId: number) =>
		stored.get(entryId)?.source_transaction_id ??
		previewRows.get(entryId)?.source_transaction_id ??
		null;

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
		// the counter-leg a commit creates belongs to no source of the unit
		if (b.id < 0 && !split && b.row) return null;
		return b.row?.source_transaction_id ?? (split ? sourceOf(split.sourceEntryId) : sourceOf(b.id));
	});
	const counts = new Map<number, number>();
	for (const s of sourceIds) if (s !== null) counts.set(s, (counts.get(s) ?? 0) + 1);

	return base.map((b, i) => {
		const entry = stored.get(b.id) ?? null;
		const split = draft.splits.find((s) => s.id === b.id) ?? null;
		const counterLeg = b.id < 0 && split === null && b.row !== null;
		const isNew = b.id < 0 && !counterLeg;
		const sourceId = counterLeg ? null : sourceIds[i];
		const original = counterLeg
			? false
			: b.row
				? b.row.original
				: !isNew && sourceId !== null && lowest.get(sourceId) === b.id;
		const inSplit = sourceId !== null && (counts.get(sourceId) ?? 0) > 1;
		const edit = draft.edit(b.id);
		const sourceEntry = split ? (stored.get(split.sourceEntryId) ?? null) : entry;
		const sourceRow = split ? (previewRows.get(split.sourceEntryId) ?? null) : null;
		const accountId: number | null =
			b.row?.account_id ?? sourceEntry?.account_id ?? sourceRow?.account_id ?? null;
		const currency =
			b.row?.amount.currency ?? sourceEntry?.amount.currency ?? sourceRow?.amount.currency ?? 'EUR';
		const splitOut = preview?.splits.find(
			(s) => s.residual_entry_id === b.id || s.entry_ids.includes(b.id)
		);
		let amount: Money | null;
		if (b.row) amount = b.row.amount;
		else if (isNew) amount = edit.amount == null ? null : { amount: edit.amount, currency };
		else amount = entry?.amount ?? null;
		const bookingSource = b.row?.booking ?? entry?.source?.booking ?? null;
		// a counter-leg booking names its charge: the account of it, where the charge is in the unit
		const chargeAccountId: number | null =
			bookingSource?.kind === 'transfer' ? chargeAccountOf(bookingSource, preview, stored) : null;
		const pairKeyPass = keyOf(b.row?.derivation ?? entry?.derivation, 'counterpart')?.pass;
		const partnerAccountId = b.row?.transfer?.partner?.account_id ?? entry?.partner?.account_id;
		const bookingContext: KeyContext = {
			booking: bookingSource?.kind ?? null,
			chargeAccount: chargeAccountId === null ? undefined : accountName(chargeAccountId)
		};
		const fields = Object.fromEntries(
			FIELD_NAMES.map((name) => [
				name,
				fieldView(name, draft, b.id, rules, locale, b.row, entry, accountName, bookingContext)
			])
		) as Record<FieldName, FieldView>;
		const booking = bookingSource ? { kind: bookingSource.kind, id: bookingSource.id } : null;
		const view: EntryView = {
			id: b.id,
			isNew,
			original,
			sourceId,
			fromEntryId: split ? split.sourceEntryId : b.id,
			inSplit,
			stored: entry,
			row: b.row,
			accountId,
			amount,
			sourceAmount: splitOut?.source_amount ?? null,
			sourceText: b.row?.source_text ?? entry?.source_text ?? null,
			description:
				edit.description !== undefined
					? edit.description
					: (b.row?.description ?? entry?.description ?? null),
			note: edit.note !== undefined ? edit.note : (b.row?.note ?? entry?.note ?? null),
			type: fields.type.value === null ? null : String(fields.type.value),
			fields,
			tagIds: b.row && !stale ? b.row.tag_ids : draft.effectiveTagIds(b.id),
			flags: b.row?.review_flags ?? entry?.review_flags ?? [],
			transfer: b.row?.transfer ?? null,
			pairEvidence: describeKey(
				keyOf(b.row?.derivation ?? entry?.derivation, 'counterpart'),
				rules,
				locale,
				{
					...bookingContext,
					field: 'counterpart',
					// the partner's account words only a booking's pair key (the charge's: "counter-leg booked on")
					partnerAccount:
						partnerAccountId === undefined || pairKeyPass !== 'booking'
							? undefined
							: accountName(partnerAccountId)
				}
			),
			picked: edit.pairing?.mode === 'pick' || edit.pairing?.mode === 'counter_leg',
			pairing: edit.pairing ?? null,
			counterLeg,
			booking,
			bookingFor: b.row?.booking_for ?? null,
			amountEditable: !original && !counterLeg && booking === null,
			removable: !original && !counterLeg && booking === null
		};
		return view;
	});
}

/** The words for the state a commit leads to (patterns §6: "confirmed", "waits for its partner"…). */
export const RESULT_TEXT: Readonly<Record<UnitState['reasons'][number], string>> = {
	incomplete: 'Stays unclassified',
	unpaired_transfer: 'Waits for its partner',
	waiting_for_partner: 'Waits for its partner',
	unmatched_transfer: 'Stays without a partner',
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
		origin: base?.origin ?? (row.booking ? 'booking' : null),
		review_flags: row.review_flags as Entry['review_flags'],
		source_text: row.source_text ?? null,
		tag_ids: row.tag_ids
	};
}

/** The proposal to name as the basis when the user picks `value`: only when it is the value shown. */
export function shownFor(field: FieldView, value: FieldValue): ShownBasis | null {
	return value !== null && field.shown !== null && field.value === value ? field.shown : null;
}
