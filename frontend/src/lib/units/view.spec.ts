import { describe, expect, it } from 'vitest';
import { entry } from '#lib/ledger/fixtures.js';
import { Draft } from './draft.js';
import { knownRules } from './evidence.js';
import { consequence, fieldOut, preview, previewRowOf, unit } from './fixtures.js';
import { consequenceGroups, entryViews, previewRowEntry, resultText, shownFor } from './view.js';

const rules = knownRules(() => undefined);
const split = unit({
	anchor_entry_id: 1,
	entries: [
		entry({
			id: 1,
			unit_key: 1,
			source_transaction_id: 5,
			category_id: 10,
			derivation: { category: { pass: 'history', basis: { agree: 3, of: 4 } } }
		}),
		entry({
			id: 2,
			unit_key: 1,
			source_transaction_id: 5,
			amount: { amount: -1000, currency: 'EUR' }
		})
	]
});

function views(draft: Draft, shown: ReturnType<typeof preview> | null = null, base = split) {
	return entryViews({ unit: base, draft, preview: shown, rules, locale: 'en' });
}

describe('entryViews: before a preview', () => {
	it('shows the entries as stored, the lowest id of a source as its original', () => {
		const [first, second] = views(Draft.of(split));

		expect(first).toMatchObject({ id: 1, original: true, inSplit: true, amountEditable: false });
		expect(second).toMatchObject({ id: 2, original: false, amountEditable: true, removable: true });
		expect(first.fields.category).toMatchObject({ value: 10, proposal: true });
		expect(first.fields.category.shown).toEqual({
			pass: 'history',
			basis: { agree: 3, of: 4 }
		});
		expect(first.fields.category.evidence?.text).toBe('history: 3 of 4');
	});

	it('adds a new split row that has no amount yet', () => {
		const rows = views(Draft.of(split).addSplit(1));

		const added = rows.at(-1)!;
		expect(added).toMatchObject({ id: -1, isNew: true, amount: null, amountEditable: true });
		expect(added.sourceId).toBe(5);
	});

	it('leaves out an entry the draft removes', () => {
		expect(views(Draft.of(split).removeSplit(2)).map((v) => v.id)).toEqual([1]);
	});

	it('shows the draft’s texts over the stored ones', () => {
		const [first] = views(Draft.of(split).setDescription(1, 'mine').setNote(1, 'n'));
		expect(first.description).toBe('mine');
		expect(first.note).toBe('n');
	});
});

describe('entryViews: with a preview', () => {
	it('takes the values and their proposals from the preview’s rows', () => {
		const answer = preview(split);
		answer.rows[0].fields.category = fieldOut(11, { pass: 'rule', basis: { rule_id: 3 } });

		const [first] = views(Draft.of(split), answer);

		expect(first.fields.category).toMatchObject({
			value: 11,
			proposal: false,
			canReset: false // the user changed nothing: the draft holds no value of theirs
		});
		expect(first.fields.category.shown).toBeNull();
	});

	it('offers Reset only for a value the user chose that differs from the stored one', () => {
		const answer = preview(split);
		const untouched = views(Draft.of(split), answer)[0];
		expect(untouched.fields.category.canReset).toBe(false);
		expect(untouched.fields.payee.canReset).toBe(false);

		const changed = views(Draft.of(split).setField(1, 'category', 11), answer)[0];
		expect(changed.fields.category.canReset).toBe(true);
		expect(changed.fields.payee.canReset).toBe(false);

		// back to the stored value: no edit, so no link
		const back = Draft.of(split).setField(1, 'category', 11).setField(1, 'category', 10);
		expect(views(back, answer)[0].fields.category.canReset).toBe(false);
	});

	it('offers Reset on a proposal only after the user changed it', () => {
		const [proposed] = views(Draft.of(split));
		expect(proposed.fields.category.proposal).toBe(true);
		expect(proposed.fields.category.canReset).toBe(false);
		const [changed] = views(Draft.of(split).setField(1, 'category', 11));
		expect(changed.fields.category.canReset).toBe(true);
	});

	it('shows only what is in the unit once the draft is applied', () => {
		const answer = preview(split);
		answer.rows[1].in_unit = false;
		expect(views(Draft.of(split), answer).map((v) => v.id)).toEqual([1]);
	});

	it('shows the residual as the server computed it, with what the source was', () => {
		const answer = preview(split);
		answer.rows[0].amount = { amount: -3000, currency: 'EUR' };
		answer.splits = [
			{
				source_transaction_id: 5,
				source_amount: { amount: -4731, currency: 'EUR' },
				residual_entry_id: 1,
				residual_amount: { amount: -3000, currency: 'EUR' },
				entry_ids: [1, 2]
			}
		];

		const [first] = views(Draft.of(split), answer);

		expect(first.amount).toEqual({ amount: -3000, currency: 'EUR' });
		expect(first.sourceAmount).toEqual({ amount: -4731, currency: 'EUR' });
	});

	it('does not offer Reset on a field already reset, or empty', () => {
		const draft = Draft.of(split).resetField(1, 'category');
		const [first, second] = views(draft, preview(split));
		expect(first.fields.category.canReset).toBe(false);
		expect(second.fields.category.canReset).toBe(false);
	});

	it('draws a new row from its preview row', () => {
		const draft = Draft.of(split).addSplit(1).setSplitAmount(-1, -500);
		const answer = preview(split);
		answer.rows.push(
			previewRowOf(entry({ id: -1, amount: { amount: -500, currency: 'EUR' } }), {
				version: null,
				original: false,
				source_transaction_id: 5
			})
		);

		const added = views(draft, answer).at(-1)!;

		expect(added).toMatchObject({ isNew: true, amount: { amount: -500, currency: 'EUR' } });
		expect(views(draft, answer)).toHaveLength(3);
	});
});

describe('shownFor', () => {
	it('names the proposal only for the very value shown', () => {
		const [first] = views(Draft.of(split));
		expect(shownFor(first.fields.category, 10)).toEqual(first.fields.category.shown);
		expect(shownFor(first.fields.category, 11)).toBeNull();
		expect(shownFor(first.fields.category, null)).toBeNull();
	});
});

describe('resultText', () => {
	it('says what the commit leads to', () => {
		expect(resultText({ confirmed: true, reasons: [] })).toBe('Confirmed');
		expect(resultText({ confirmed: false, reasons: ['unpaired_transfer'] })).toBe(
			'Waits for its partner'
		);
		expect(resultText({ confirmed: false, reasons: ['incomplete', 'non_standing_keys'] })).toBe(
			'Stays unclassified · Proposals to check'
		);
		expect(resultText({ confirmed: false, reasons: [] })).toBe('Stays in review');
	});
});

describe('consequenceGroups', () => {
	it('orders the groups as the pattern does and leaves empty ones out', () => {
		const row = (id: number) => previewRowOf(entry({ id }));
		const groups = consequenceGroups(
			preview(split, {
				consequences: [
					consequence('unpaired', row(5)),
					consequence('created', row(-1)),
					consequence('deleted', row(6)),
					consequence('changed', row(7)),
					consequence('changed', row(8))
				]
			})
		);

		expect(groups.map((g) => [g.kind, g.title, g.items.length])).toEqual([
			['created', 'Created', 1],
			['changed', 'Changed', 2],
			['deleted', 'Deleted', 1],
			['unpaired', 'Unpaired', 1]
		]);
		expect(consequenceGroups(null)).toEqual([]);
	});
});

describe('previewRowEntry', () => {
	it('lets the ledger’s row draw a preview row, with the text of the entry the unit holds', () => {
		const row = previewRowOf(entry({ id: 2, category_id: 10, payee_id: 20, version: 4 }), {
			description: 'mine'
		});
		const asEntry = previewRowEntry(row, entry({ id: 2, display_text: 'REWE Markt' }));

		expect(asEntry).toMatchObject({
			id: 2,
			version: 4,
			type: 'flow',
			category_id: 10,
			payee_id: 20,
			display_text: 'REWE Markt'
		});
		expect(previewRowEntry(row).display_text).toBe('mine');
	});

	it('reads a transfer’s counter-account', () => {
		const row = previewRowOf(entry({ id: 2, type: 'transfer', counter_account_id: 3 }));
		expect(previewRowEntry(row)).toMatchObject({ type: 'transfer', counter_account_id: 3 });
	});
});
