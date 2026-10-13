// Test fixtures for units and the review queue.
import { ApiError } from '#lib/api/index.js';
import { entry } from '#lib/ledger/fixtures.js';
import type { Entry } from '#lib/types/domain.js';
import type { QueueSection, ReviewQueue, Unit } from './types.js';

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
