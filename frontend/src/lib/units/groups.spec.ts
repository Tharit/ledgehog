import { describe, expect, it } from 'vitest';
import { entry } from '#lib/ledger/fixtures.js';
import { source } from '#lib/rules/fixtures.js';
import { Draft } from './draft.js';
import { knownRules } from './evidence.js';
import { preview, unit } from './fixtures.js';
import { groupsOf, pairLine } from './groups.js';
import { entryViews } from './view.js';

const rules = knownRules(() => undefined);

function leg(id: number, account: number, src: number, booked: string, over = {}) {
	return entry({
		id,
		unit_key: 1,
		type: 'transfer',
		account_id: account,
		booked_on: booked,
		amount: { amount: account === 1 ? -5000 : 5000, currency: 'EUR' },
		source_transaction_id: src,
		source: source({ amount: { amount: account === 1 ? -5000 : 5000, currency: 'EUR' } }),
		derivation: { counterpart: { pass: 'matcher_decision' } },
		...over
	});
}

function viewsOf(u: ReturnType<typeof unit>, draft = Draft.of(u)) {
	return entryViews({ unit: u, draft, preview: preview(u), rules, locale: 'en' });
}

const pair = unit({
	anchor_entry_id: 1,
	entries: [leg(1, 1, 5, '2026-10-10'), leg(2, 2, 6, '2026-10-09')]
});

describe('groupsOf', () => {
	it('puts a new split right under the leg it splits, not after the other leg', () => {
		const draft = Draft.of(pair).addSplit(1);
		const groups = groupsOf(viewsOf(pair, draft), pair.entries);
		const ids = groups.map((g) => g.views.map((v) => v.id));
		expect(ids).toEqual([[2], [1, -1]]);
	});

	it('keeps a split under each leg with its own group', () => {
		const draft = Draft.of(pair).addSplit(1).addSplit(2);
		const groups = groupsOf(viewsOf(pair, draft), pair.entries);
		expect(groups.map((g) => g.views.map((v) => v.id))).toEqual([
			[2, -2],
			[1, -1]
		]);
		expect(groups.map((g) => g.splitEntryId)).toEqual([2, 1]);
	});

	it('orders groups by the earlier booked date, ties by entry id; the anchor is not special', () => {
		expect(groupsOf(viewsOf(pair), pair.entries).map((g) => g.sourceId)).toEqual([6, 5]);
		const tie = unit({
			anchor_entry_id: 2,
			entries: [leg(1, 1, 5, '2026-10-09'), leg(2, 2, 6, '2026-10-09')]
		});
		expect(groupsOf(viewsOf(tie), tie.entries).map((g) => g.sourceId)).toEqual([5, 6]);
	});

	it('says what the header shows: account, booked date, source amount, authored', () => {
		const authored = unit({
			anchor_entry_id: 1,
			entries: [leg(1, 1, 5, '2026-10-10', { authored: true }), leg(2, 2, 6, '2026-10-09')]
		});
		const [first, second] = groupsOf(viewsOf(authored), authored.entries);
		expect(first.header).toEqual({
			accountId: 2,
			bookedOn: '2026-10-09',
			amount: { amount: 5000, currency: 'EUR' },
			authored: false
		});
		expect(second.header).toMatchObject({ accountId: 1, bookedOn: '2026-10-10', authored: true });
	});

	it('is one group for a single source: residual first, then the splits as added', () => {
		const one = unit({
			anchor_entry_id: 1,
			entries: [
				entry({ id: 1, unit_key: 1, source_transaction_id: 5 }),
				entry({ id: 2, unit_key: 1, source_transaction_id: 5 })
			]
		});
		const groups = groupsOf(viewsOf(one, Draft.of(one).addSplit(1)), one.entries);
		expect(groups).toHaveLength(1);
		expect(groups[0].views.map((v) => v.id)).toEqual([1, 2, -1]);
	});
});

describe('pairLine', () => {
	const args = {
		accountName: (id: number) => (id === 1 ? 'Giro' : 'Savings'),
		rules,
		locale: 'en'
	};

	it('names both accounts and how the pair was made', () => {
		const groups = groupsOf(viewsOf(pair), pair.entries);
		const line = pairLine(groups, pair.entries, args);
		expect(line?.text).toBe('Transfer between Savings and Giro');
		expect(line?.evidence?.text).toBe('paired with Giro');
	});

	it('is absent for one source', () => {
		const one = unit({ anchor_entry_id: 1, entries: [entry({ id: 1, source_transaction_id: 5 })] });
		expect(pairLine(groupsOf(viewsOf(one), one.entries), one.entries, args)).toBeNull();
	});
});
