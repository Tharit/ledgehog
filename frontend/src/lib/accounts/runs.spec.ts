import { describe, expect, it } from 'vitest';
import { statusLabel, summaryLine } from './runs.js';

describe('run row words', () => {
	it('names the statuses', () => {
		expect(statusLabel('ok')).toBe('Succeeded');
		expect(statusLabel('failed')).toBe('Failed');
		expect(statusLabel('reverted')).toBe('Reverted');
		expect(statusLabel('running')).toBe('Running');
	});

	it('says inserted, inserted as duplicates and skipped in one line', () => {
		expect(
			summaryLine({
				stats: {
					inserted: 12,
					skipped_by_identity: 40,
					inserted_as_duplicates: [{ id: 3, duplicate_of: 2 }]
				}
			})
		).toBe('12 inserted · 1 as duplicates · 40 skipped');
	});

	it('says nothing for a run that stored no statistics', () => {
		expect(summaryLine({ stats: {} })).toBe('');
	});
});
