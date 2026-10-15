// Test fixtures for units and the review queue.
import { ApiError } from '#lib/api/index.js';
import { entry } from '#lib/ledger/fixtures.js';
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
	UnitPreview,
	UnitProblem
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
	return { kind, total: units.length, units, next_cursor: null, ...over };
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
		snapshot: 'snap-1',
		...over
	};
}

/** An error answer, for tests of components (which never import the API themselves). */
export function apiError(status: number, code: string): ApiError {
	return new ApiError(status, code, 'x');
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
	return { code, entry_id: null, field: null, detail: {}, ...over };
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
