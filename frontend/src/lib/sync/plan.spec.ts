import { describe, expect, it } from 'vitest';
import { planInstance } from './fixtures.js';
import {
	narrowPlan,
	narrowedPlanUrl,
	narrowingOf,
	planItems,
	sinceSourceText,
	startable
} from './plan.js';

const account = (id: number, over: Record<string, unknown> = {}) => ({
	account_id: id,
	external_ref: `ref-${id}`,
	since: '2026-10-08',
	since_source: 'coverage' as const,
	editable: false,
	...over
});

describe('planItems', () => {
	it('sends one item per account and one for documents, with no since by default', () => {
		const plan = [
			planInstance({
				accounts: [account(7), account(8, { editable: true, since: '2026-01-01' })],
				documents_since: '2026-03-01'
			})
		];
		expect(planItems(plan)).toEqual([
			{ instance_id: 1, account_id: 7 },
			{ instance_id: 1, account_id: 8 },
			{ instance_id: 1, kind: 'documents' }
		]);
	});

	it('carries a since only where an editable start was changed', () => {
		const plan = [
			planInstance({
				accounts: [
					account(7),
					account(8, { editable: true, since: '2026-01-01' }),
					account(9, { editable: true, since: '2026-01-01' })
				]
			})
		];
		const items = planItems(plan, { 7: '2026-02-02', 8: '2026-05-05', 9: '2026-01-01' });
		expect(items).toEqual([
			{ instance_id: 1, account_id: 7 },
			{ instance_id: 1, account_id: 8, since: '2026-05-05' },
			{ instance_id: 1, account_id: 9 }
		]);
	});

	it('leaves a busy login out', () => {
		const plan = [
			planInstance({ instance_id: 1 }),
			planInstance({ instance_id: 2, busy: true, label: 'Card login' })
		];
		expect(planItems(plan).map((i) => i.instance_id)).toEqual([1]);
		expect(startable(plan).map((i) => i.instance_id)).toEqual([1]);
	});

	it('has no items for an empty plan', () => {
		expect(planItems([])).toEqual([]);
	});
});

describe('narrowing', () => {
	const plan = [
		planInstance({
			instance_id: 1,
			accounts: [account(7), account(8)],
			documents_since: '2026-03-01'
		}),
		planInstance({ instance_id: 2, accounts: [account(9)] })
	];

	it('reads the address', () => {
		expect(narrowingOf('')).toEqual({ instanceId: null, accountId: null });
		expect(narrowingOf('?instance=3')).toEqual({ instanceId: 3, accountId: null });
		expect(narrowingOf('?instance=3&account=7')).toEqual({ instanceId: 3, accountId: 7 });
		expect(narrowingOf('?account=7')).toEqual({ instanceId: null, accountId: null });
		expect(narrowingOf('?instance=x&account=-1')).toEqual({ instanceId: null, accountId: null });
	});

	it('writes the address', () => {
		expect(narrowedPlanUrl(3)).toBe('/sync?instance=3');
		expect(narrowedPlanUrl(3, 7)).toBe('/sync?instance=3&account=7');
	});

	it('shows one login with all its items', () => {
		const shown = narrowPlan(plan, { instanceId: 1, accountId: null });
		expect(shown).toHaveLength(1);
		expect(shown[0].accounts).toHaveLength(2);
		expect(shown[0].documents_since).toBe('2026-03-01');
	});

	it('shows one account alone, without the documents', () => {
		const shown = narrowPlan(plan, { instanceId: 1, accountId: 8 });
		expect(shown[0].accounts.map((a) => a.account_id)).toEqual([8]);
		expect(shown[0].documents_since).toBeNull();
		expect(planItems(shown)).toEqual([{ instance_id: 1, account_id: 8 }]);
	});

	it('shows nothing for a login or an account the plan does not have', () => {
		expect(narrowPlan(plan, { instanceId: 5, accountId: null })).toEqual([]);
		expect(narrowPlan(plan, { instanceId: 1, accountId: 99 })).toEqual([]);
	});

	it('leaves a login with nothing to fetch out', () => {
		expect(narrowPlan([planInstance({ accounts: [] })], { instanceId: null, accountId: null })).toEqual([]);
	});
});

describe('sinceSourceText', () => {
	it('says where a start comes from, in words', () => {
		expect(sinceSourceText('coverage')).toBe('continues from the last sync, with an overlap');
		expect(sinceSourceText('latest_entry')).toBe('the day after its latest entry');
		expect(sinceSourceText('importer_default')).toBe("the importer's default");
	});
});
