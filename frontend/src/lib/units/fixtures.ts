// Test fixtures for units and the review queue.
import { ApiError } from '#lib/api/index.js';
import { entry } from '#lib/ledger/fixtures.js';
import { source } from '#lib/rules/fixtures.js';
import type { Entry } from '#lib/types/domain.js';
import { isProposalPass } from './evidence.js';
import type {
	PreviewField,
	PreviewRow,
	QueueSection,
	ReviewQueue,
	Unit,
	UnitCommit,
	UnitConsequence,
	UnitDraftRequest,
	UnitOffer,
	UnitPreview,
	UnitProblem,
	UnitTransfer
} from './types.js';

/** A one-entry unit (a flow proposed by history) unless told otherwise. */
export function unit(over: Partial<Unit> & { entries?: Entry[] } = {}): Unit {
	const entries = over.entries ?? [
		entry({
			id: over.anchor_entry_id ?? 1,
			unit_key: over.unit_key ?? over.anchor_entry_id ?? 1,
			category_id: 10,
			payee_id: 20,
			review_flags: ['unconfirmed'],
			derivation: {
				category: { pass: 'history', basis: { agree: 3, of: 4, since: '2026-03-14' } },
				payee: { pass: 'rule', basis: { rule_id: 3 } }
			}
		})
	];
	const anchor = over.anchor_entry_id ?? Math.min(...entries.map((e) => e.id));
	return {
		anchor_entry_id: anchor,
		unit_key: over.unit_key ?? anchor,
		state: { confirmed: false, reasons: ['non_standing_keys'] },
		...over,
		entries
	};
}

export function section(
	kind: QueueSection['kind'],
	units: Unit[],
	over: Partial<QueueSection> = {}
): QueueSection {
	return {
		kind,
		total: units.length,
		units,
		groups: [],
		account_groups: [],
		next_cursor: null,
		...over
	};
}

export function queue(
	sections: Partial<Record<QueueSection['kind'], Unit[]>> = {},
	over: Partial<ReviewQueue> = {}
): ReviewQueue {
	const kinds = ['pending_review', 'needs_account', 'waiting'] as const;
	const built = kinds.map((kind) => section(kind, sections[kind] ?? []));
	return {
		sections: built,
		total: built.reduce((sum, s) => sum + s.total, 0),
		...over
	};
}

/** An error answer, for tests of components (which never import the API themselves). */
export function apiError(status: number, code: string, details: unknown = null): ApiError {
	return new ApiError(status, code, 'x', details);
}

/** One derived field of a preview row; a proposal when its key is a proposal pass. */
export function fieldOut(
	value: PreviewField['value'],
	key: { pass: string; basis?: Record<string, unknown> } | null = null,
	over: Partial<PreviewField> = {}
): PreviewField {
	const full = key ? { pass: key.pass, basis: key.basis ?? {} } : null;
	return {
		value,
		key: full,
		is_proposal: full !== null && isProposalPass(full.pass),
		commit_key: full ? { pass: 'user', basis: {} } : null,
		stored: { value, key: full },
		...over
	};
}

/** The preview row of a stored entry, as the draft leaves it when untouched. */
export function previewRowOf(e: Entry, over: Partial<PreviewRow> = {}): PreviewRow {
	const derivation = e.derivation as Record<
		string,
		{ pass: string; basis?: Record<string, unknown> }
	>;
	return {
		id: e.id,
		version: e.version,
		source_transaction_id: e.source_transaction_id ?? e.id,
		unit_key: e.unit_key ?? e.id,
		in_unit: true,
		original: true,
		account_id: e.account_id,
		booked_on: e.booked_on,
		value_on: e.value_on,
		amount: e.amount,
		description: e.description,
		note: e.note,
		source_text: e.source_text,
		tag_ids: e.tag_ids,
		counterpart_entry_id: e.counterpart_entry_id,
		fields: {
			type: fieldOut(e.type, derivation.type ?? null),
			payee: fieldOut(e.payee_id, derivation.payee ?? null),
			category: fieldOut(e.category_id, derivation.category ?? null),
			counter_account: fieldOut(
				e.counter_account_id,
				derivation.counter_account ?? derivation.counterpart ?? null
			)
		},
		review_flags: [...e.review_flags],
		derivation: e.derivation,
		stored: { amount: e.amount, description: e.description, note: e.note },
		...over
	};
}

/** The preview of the untouched unit: its rows as stored, its state, no problem, no consequence. */
export function preview(u: Unit, over: Partial<UnitPreview> = {}): UnitPreview {
	const firstOf = new Map<number, number>();
	for (const e of u.entries) {
		const source = e.source_transaction_id ?? e.id;
		firstOf.set(source, Math.min(firstOf.get(source) ?? e.id, e.id));
	}
	return {
		state: u.state,
		units: [
			{
				anchor_entry_id: u.anchor_entry_id,
				unit_key: u.unit_key,
				entry_ids: u.entries.map((e) => e.id),
				state: u.state
			}
		],
		rows: u.entries.map((e) =>
			previewRowOf(e, { original: firstOf.get(e.source_transaction_id ?? e.id) === e.id })
		),
		splits: [],
		problems: [],
		consequences: [],
		versions: Object.fromEntries(u.entries.map((e) => [e.id, e.version])),
		entries: u.entries,
		...over
	};
}

/**
 * The preview of a request, as the server answers it: the user's fixed values laid over the
 * unit (each with the `user` key); a re-resolve leaves the stored state in the row.
 */
export function previewFor(u: Unit, request: UnitDraftRequest): UnitPreview {
	const answer = preview(u);
	for (const edit of request.entries ?? []) {
		const row = answer.rows.find((r) => r.id === edit.id);
		if (!row) continue;
		for (const name of ['type', 'payee', 'category', 'counter_account'] as const) {
			const field = edit[name];
			if (field?.mode === 'fixed')
				row.fields[name] = fieldOut(field.value ?? null, { pass: 'user' });
		}
		// the row shows the tags with the change applied
		if (edit.tags) {
			const { add = [], remove = [] } = edit.tags;
			row.tag_ids = [...row.tag_ids.filter((t) => !remove.includes(t)), ...add];
		}
	}
	return answer;
}

export function problem(code: string, over: Partial<UnitProblem> = {}): UnitProblem {
	return { code, entry_id: null, field: null, detail: {}, suggested_split: null, ...over };
}

export function consequence(
	kind: UnitConsequence['kind'],
	row: PreviewRow,
	over: Partial<UnitConsequence> = {}
): UnitConsequence {
	return { entry_id: row.id, kind, version: row.version, row, ...over };
}

/** What a commit of the unit answers: the unit's rows, confirmed, nothing created or removed. */
export function committed(u: Unit, over: Partial<UnitCommit> = {}): UnitCommit {
	return {
		created: {},
		removed_entry_ids: [],
		entries: u.entries,
		other_entry_ids: [],
		truncated: false,
		units: [
			{
				anchor_entry_id: u.anchor_entry_id,
				entry_ids: u.entries.map((e) => e.id),
				state: { confirmed: true, reasons: [] }
			}
		],
		consequences: [],
		settle: { error: null, touched_entry_ids: [] },
		...over
	};
}

/** An offer of the partner list: an open leg of another account, exact, unless told otherwise. */
export function offerOut(over: Partial<UnitOffer> = {}): UnitOffer {
	return {
		kind: 'open_leg',
		entry_id: 2,
		account_id: 2,
		booked_on: '2026-10-09',
		amount: { amount: 5000, currency: 'EUR' },
		description: 'Transfer in',
		exact: true,
		proposed: false,
		paired_with: null,
		counter_leg: null,
		effect: { types_as_transfer: false, fee: null, breaks_pair_with: [] },
		...over
	};
}

/** What a preview row says of a transfer leg: unpaired with no offers, unless told otherwise. */
export function transferOut(over: Partial<UnitTransfer> = {}): UnitTransfer {
	return {
		state: 'unmatched',
		waiting_for: null,
		needs_account: null,
		partner: null,
		offers: [],
		proposal: null,
		proposed_pick: null,
		proposed_counter_leg: false,
		has_more: false,
		...over
	};
}

const EUR = (amount: number) => ({ amount, currency: 'EUR' });

/**
 * A leg (1) of the unit as loaded, and a partner (2, with a split sibling 3 of its source 6) that the
 * preview joins to it: by the proposal of the server (`proposal`), or by settling's pair. Another
 * candidate (4, source 8) is there to be picked instead.
 */
export function joinedScene(proposal = true) {
	const leg = entry({
		id: 1,
		version: 3,
		unit_key: 1,
		type: 'transfer',
		account_id: 1,
		counter_account_id: 2,
		amount: EUR(-4900),
		booked_on: '2026-10-10',
		source_transaction_id: 5,
		source: source({ amount: EUR(-4900) }),
		review_flags: ['unconfirmed'],
		display_text: 'The leg',
		derivation: {}
	});
	const partner = entry({
		id: 2,
		version: 7,
		unit_key: 2,
		type: 'transfer',
		account_id: 2,
		counter_account_id: 1,
		amount: EUR(4900),
		booked_on: '2026-10-09',
		source_transaction_id: 6,
		source: source({ amount: EUR(5000) }),
		description: 'Incoming',
		display_text: 'The partner',
		tag_ids: [7],
		derivation: { payee: { pass: 'rule', basis: { rule_id: 3 } } }
	});
	const sibling = entry({
		id: 3,
		version: 8,
		unit_key: 2,
		type: 'flow',
		account_id: 2,
		amount: EUR(100),
		booked_on: '2026-10-09',
		source_transaction_id: 6,
		source: source({ amount: EUR(5000) }),
		display_text: 'The sibling',
		derivation: {}
	});
	const other = entry({
		id: 4,
		version: 2,
		unit_key: 4,
		type: 'transfer',
		account_id: 2,
		amount: EUR(4900),
		booked_on: '2026-10-08',
		source_transaction_id: 8,
		display_text: 'The other',
		derivation: {}
	});
	const loaded = unit({ anchor_entry_id: 1, entries: [leg] });
	const view = (e: Entry) => ({
		entry_id: e.id,
		account_id: e.account_id,
		booked_on: e.booked_on,
		amount: e.amount,
		description: e.description
	});
	/** The preview of the loaded unit with the partner joined (rows 1, 2, 3; entries and versions of all). */
	const joinedPreview = (over: Partial<UnitPreview> = {}): UnitPreview => {
		const answer = preview(loaded, over);
		answer.rows[0].counterpart_entry_id = 2;
		answer.rows[0].transfer = transferOut({
			state: 'paired',
			partner: view(partner),
			proposed_pick: proposal ? { entry_id: 2 } : null,
			offers: [
				offerOut({ entry_id: 2, exact: true, proposed: proposal }),
				offerOut({ entry_id: 4, exact: true })
			]
		});
		answer.rows.push(
			previewRowOf(partner, {
				original: true,
				counterpart_entry_id: 1,
				transfer: transferOut({ state: 'paired', partner: view(leg) })
			}),
			previewRowOf(sibling, { original: false })
		);
		answer.versions = { 1: 3, 2: 7, 3: 8 };
		answer.entries = [leg, partner, sibling];
		return { ...answer, ...over };
	};
	return { leg, partner, sibling, other, loaded, joinedPreview };
}
