import { describe, expect, it } from 'vitest';
import { entry } from '#lib/ledger/fixtures.js';
import { source } from '#lib/rules/fixtures.js';
import { Draft } from './draft.js';
import { knownRules } from './evidence.js';
import { preview, previewRowOf, transferOut, unit } from './fixtures.js';
import { groupsOf, partnerDirections } from './groups.js';
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

describe('partnerDirections', () => {
	const partner = (entryId: number, account: number) => ({
		entry_id: entryId,
		account_id: account,
		booked_on: '2026-10-10',
		amount: { amount: 5000, currency: 'EUR' },
		description: null
	});
	function paired() {
		const out = preview(pair);
		out.rows.find((r) => r.id === 1)!.transfer = transferOut({
			state: 'paired',
			partner: partner(2, 2)
		});
		out.rows.find((r) => r.id === 2)!.transfer = transferOut({
			state: 'paired',
			partner: partner(1, 1)
		});
		return entryViews({ unit: pair, draft: Draft.of(pair), preview: out, rules, locale: 'en' });
	}

	it('says above for the leg of the later group and below for the earlier one', () => {
		// order: entry 2 (Oct 9), then entry 1 (Oct 10)
		const groups = groupsOf(paired(), pair.entries);
		const directions = partnerDirections(groups);
		expect(directions.get(2)).toBe('below');
		expect(directions.get(1)).toBe('above');
	});

	it('has none for a leg without a partner in another group', () => {
		const one = unit({ anchor_entry_id: 1, entries: [entry({ id: 1, source_transaction_id: 5 })] });
		expect(partnerDirections(groupsOf(viewsOf(one), one.entries)).size).toBe(0);
		expect(partnerDirections(groupsOf(viewsOf(pair), pair.entries)).size).toBe(0);
	});
});

describe('the ghost group of a counter-leg', () => {
	const single = unit({ anchor_entry_id: 1, entries: [leg(1, 1, 5, '2026-10-10')] });
	const ghostRow = () =>
		previewRowOf(
			entry({
				id: -7,
				unit_key: 1,
				type: 'transfer',
				account_id: 2,
				booked_on: '2026-10-11',
				amount: { amount: 5000, currency: 'EUR' },
				description: 'Savings top-up',
				source_transaction_id: -7,
				derivation: {}
			}),
			{ original: false, in_unit: true, transfer: transferOut({ state: 'paired' }) }
		);
	function withGhost(extra: Partial<ReturnType<typeof preview>> = {}) {
		const out = preview(single, extra);
		out.rows[0].transfer = transferOut({
			state: 'paired',
			partner: {
				entry_id: -7,
				account_id: 2,
				booked_on: '2026-10-11',
				amount: { amount: 5000, currency: 'EUR' },
				description: null
			}
		});
		out.rows.push(ghostRow());
		return out;
	}
	const views = () =>
		entryViews({
			unit: single,
			draft: Draft.of(single),
			preview: withGhost(),
			rules,
			locale: 'en'
		});

	it('turns a row with a negative id the draft does not own into a view that is no split', () => {
		const ghost = views().find((v) => v.id === -7)!;
		expect(ghost).toMatchObject({
			counterLeg: true,
			isNew: false,
			sourceId: null,
			inSplit: false,
			removable: false,
			amountEditable: false
		});
		// the real leg is not counted as a split because of it
		expect(views().find((v) => v.id === 1)).toMatchObject({ counterLeg: false, inSplit: false });
	});

	it('is appended after the real groups, read-only, with its header, purpose and the leg it is for', () => {
		const groups = groupsOf(views(), single.entries);
		expect(groups.map((g) => g.key)).toEqual(['source-5', 'counter-leg--7']);
		const ghost = groups[1];
		expect(ghost.ghost).toEqual({ forAccountId: 1, purpose: 'Savings top-up' });
		expect(ghost.header).toEqual({
			accountId: 2,
			bookedOn: '2026-10-11',
			amount: { amount: 5000, currency: 'EUR' },
			authored: false
		});
		expect(ghost.splitEntryId).toBeNull();
		expect(ghost.strip).toBeNull();
		expect(groups[0].ghost).toBeNull();
		expect(groups[0].views.map((v) => v.id)).toEqual([1]);
	});

	it('is below the real leg whose partner it stands for', () => {
		const directions = partnerDirections(groupsOf(views(), single.entries));
		expect(directions.get(1)).toBe('below');
	});

	it('is no group when the draft’s own split has a negative id', () => {
		const draft = Draft.of(single).addSplit(1).setSplitAmount(-1, -1000);
		const groups = groupsOf(
			entryViews({ unit: single, draft, preview: preview(single), rules, locale: 'en' }),
			single.entries
		);
		expect(groups.map((g) => g.ghost)).toEqual([null]);
	});
});
