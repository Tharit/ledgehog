import { describe, expect, it } from 'vitest';
import type { TaskItem } from './events.js';
import { itemRun, itemSummary } from './progress.js';

const item = (stats: Record<string, unknown> | null): TaskItem => ({
	accountId: 7,
	kind: 'transactions',
	state: 'done',
	runId: 10,
	since: '2026-10-08',
	stats,
	failure: null
});

describe('itemSummary', () => {
	it('says what the run inserted and skipped', () => {
		expect(itemSummary(item({ inserted: 12, skipped_by_identity: 31 }))).toBe(
			'12 inserted · 31 skipped'
		);
	});

	it('adds the duplicates where there are some', () => {
		expect(
			itemSummary(
				item({
					inserted: 12,
					skipped_by_identity: 31,
					inserted_as_duplicates: [
						{ id: 1, duplicate_of: 2 },
						{ id: 3, duplicate_of: 4 }
					]
				})
			)
		).toBe('12 inserted · 31 skipped · 2 as duplicates');
	});

	it('counts what a run without statistics did as nothing', () => {
		expect(itemSummary(item(null))).toBe('0 inserted · 0 skipped');
	});
});

describe('itemRun', () => {
	it('is an ok run of the account, with the statistics of the event and no coverage', () => {
		const run = itemRun(3, item({ inserted: 1 }));
		expect(run).toMatchObject({
			account_id: 7,
			instance_id: 3,
			status: 'ok',
			covered_from: null,
			covered_through: null,
			stats: { inserted: 1 }
		});
	});
});
