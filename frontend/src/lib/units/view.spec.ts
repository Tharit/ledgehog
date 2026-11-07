import { describe, expect, it } from 'vitest';
import { entry } from '#lib/ledger/fixtures.js';
import { Draft } from './draft.js';
import { knownRules } from './evidence.js';
import { consequence, fieldOut, preview, previewRowOf, unit } from './fixtures.js';
import {
	consequenceGroups,
	effectiveChanged,
	entryViews,
	previewRowEntry,
	resultText,
	shownFor
} from './view.js';

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

describe('resultText', () => {
	it('words the new reasons', () => {
		expect(resultText({ confirmed: false, reasons: ['waiting_for_partner'] })).toBe(
			'Waits for its partner'
		);
		expect(resultText({ confirmed: false, reasons: ['unmatched_transfer'] })).toBe(
			'Stays without a partner'
		);
	});
});

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
		expect(added.fromEntryId).toBe(1);
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

describe('entryViews: source text', () => {
	it('is the entry’s source text, and none for a new split row', () => {
		const withText = unit({
			anchor_entry_id: 1,
			entries: [entry({ id: 1, unit_key: 1, source_transaction_id: 5, source_text: 'USB cable' })]
		});
		const rows = views(Draft.of(withText).addSplit(1), null, withText);

		expect(rows[0].sourceText).toBe('USB cable');
		expect(rows.at(-1)!.sourceText).toBeNull();
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

		const picked = preview(split);
		picked.rows[0].fields.category = fieldOut(11, { pass: 'user' });
		const changed = views(Draft.of(split).setField(1, 'category', 11), picked)[0];
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

describe('the evidence of a transfer leg’s counter-account', () => {
	const partner = {
		entry_id: 9,
		account_id: 2,
		booked_on: '2026-10-08',
		amount: { amount: 100, currency: 'EUR' }
	};
	const leg = (over: Parameters<typeof entry>[0]) =>
		unit({
			anchor_entry_id: 1,
			entries: [entry({ id: 1, unit_key: 1, type: 'transfer', counter_account_id: 2, ...over })]
		});
	const counter = (
		base: ReturnType<typeof unit>,
		accountName?: (id: number) => string | undefined
	) =>
		entryViews({
			unit: base,
			draft: Draft.of(base),
			preview: null,
			rules,
			locale: 'en',
			accountName
		})[0].fields.counter_account;

	it('says "paired with <account>" for a counter-account that only the pair key explains', () => {
		const base = leg({
			counterpart_entry_id: 9,
			partner,
			derivation: { counterpart: { pass: 'matcher_decision', basis: {} } }
		});

		expect(counter(base, (id) => (id === 2 ? 'Cash' : undefined)).evidence?.text).toBe(
			'paired with Cash'
		);
		expect(counter(base).evidence?.text).toBe('matched automatically');
	});

	it('words a counter-account of the partner basis as "from its partner", and offers no X', () => {
		const base = leg({
			counterpart_entry_id: 9,
			partner,
			derivation: {
				counter_account: { pass: 'user', basis: { from: 'counterpart' } },
				counterpart: { pass: 'user', basis: {} }
			}
		});

		expect(counter(base)).toMatchObject({
			evidence: { text: 'from its partner' },
			clearable: false
		});
	});

	it('offers no X on a counter-account that the user’s pair explains', () => {
		const base = leg({
			counterpart_entry_id: 9,
			partner,
			derivation: { counterpart: { pass: 'user', basis: {} } }
		});

		expect(counter(base)).toMatchObject({ evidence: { text: 'set by you' }, clearable: false });
	});

	it('still offers the X on a counter-account the user chose themselves', () => {
		const base = leg({ derivation: { counter_account: { pass: 'user' } } });

		expect(counter(base)).toMatchObject({ evidence: { text: 'set by you' }, clearable: true });
	});
});

describe('the X and "Reset to proposal" follow what the preview shows', () => {
	const stored = (over: Parameters<typeof entry>[0]) =>
		unit({ anchor_entry_id: 1, entries: [entry({ id: 1, unit_key: 1, ...over })] });
	const field = (
		base: ReturnType<typeof unit>,
		draft: Draft,
		answer: ReturnType<typeof preview> | null,
		name: 'category' | 'payee' | 'counter_account' = 'category'
	) => views(draft, answer, base)[0].fields[name];

	it('offers no Reset when clearing lets the rule propose the stored category again', () => {
		const base = stored({
			category_id: 10,
			derivation: { category: { pass: 'rule', basis: { rule_id: 3 } } }
		});
		const answer = preview(base); // the rule decides 10 again
		const cleared = Draft.of(base).clearField(1, 'category');

		expect(field(base, cleared, answer)).toMatchObject({ value: 10, canReset: false });
		expect(effectiveChanged('category', answer.rows[0], base.entries[0])).toBe(false);
	});

	it('offers Reset when a cleared user decision is proposed otherwise or not at all', () => {
		const base = stored({
			category_id: 10,
			derivation: { category: { pass: 'user' } }
		});
		const none = preview(base);
		none.rows[0].fields.category = fieldOut(null);
		const cleared = Draft.of(base).clearField(1, 'category');
		expect(field(base, cleared, none)).toMatchObject({ value: null, canReset: true });

		const history = preview(base);
		history.rows[0].fields.category = fieldOut(10, { pass: 'history', basis: { agree: 2, of: 2 } });
		// the same value under another key is a change: the user's decision is gone
		expect(field(base, cleared, history).canReset).toBe(true);
	});

	it('offers Reset by the key alone when a pick confirms the stored proposal', () => {
		const base = stored({
			category_id: 10,
			derivation: { category: { pass: 'history', basis: { agree: 3, of: 4 } } }
		});
		const answer = preview(base);
		answer.rows[0].fields.category = fieldOut(10, { pass: 'user' });
		const shown = { pass: 'history', basis: { agree: 3, of: 4 } };
		const draft = Draft.of(base).setField(1, 'category', 10, shown);
		expect(field(base, draft, answer).canReset).toBe(true);
	});

	it('shows the X only on the user’s own decision, by key pass', () => {
		const clearable = (pass: string | null, value: number | null = 10) => {
			const base = stored({
				category_id: value,
				derivation: pass ? { category: { pass, basis: pass === 'rule' ? { rule_id: 3 } : {} } } : {}
			});
			return field(base, Draft.of(base), preview(base)).clearable;
		};
		expect(clearable('user')).toBe(true);
		expect(clearable('rule')).toBe(false);
		expect(clearable('history')).toBe(false);
		expect(clearable('llm')).toBe(false);
		expect(clearable('matcher_decision')).toBe(false);
		expect(clearable('own_account')).toBe(false);
		expect(clearable(null)).toBe(false);
		expect(clearable('user', null)).toBe(false); // nothing shown, nothing to remove

		// a value the user just picked (not yet previewed) is theirs
		const base = stored({ category_id: 10, derivation: { category: { pass: 'rule', basis: {} } } });
		const picked = Draft.of(base).setField(1, 'category', 11);
		expect(field(base, picked, null).clearable).toBe(true);
	});

	it('shows the X on a payee whenever one is shown, whatever its source', () => {
		for (const pass of ['rule', 'history', 'llm', 'user']) {
			const base = stored({ payee_id: 20, derivation: { payee: { pass, basis: {} } } });
			expect(field(base, Draft.of(base), preview(base), 'payee').clearable).toBe(true);
		}
		const empty = stored({ payee_id: null });
		expect(field(empty, Draft.of(empty), preview(empty), 'payee').clearable).toBe(false);
	});

	it('shows a payee decided empty as set by you, an undecided empty payee with no evidence', () => {
		const decided = stored({ payee_id: null, derivation: { payee: { pass: 'user' } } });
		const open = stored({ payee_id: null });
		expect(field(decided, Draft.of(decided), preview(decided), 'payee')).toMatchObject({
			value: null,
			clearable: false,
			evidence: { text: 'set by you' }
		});
		expect(field(open, Draft.of(open), preview(open), 'payee')).toMatchObject({
			value: null,
			clearable: false,
			evidence: null
		});
	});

	it('offers Reset on a payee cleared over an undecided or a set payee, not over the same decision', () => {
		const open = stored({ payee_id: null });
		const answer = preview(open);
		answer.rows[0].fields.payee = fieldOut(null, { pass: 'user' });
		const none = Draft.of(open).clearField(1, 'payee');
		expect(field(open, none, answer, 'payee')).toMatchObject({ canReset: true });
		// before any preview, the fixed null still differs from an undecided payee
		expect(field(open, none, null, 'payee').canReset).toBe(true);

		const decided = stored({ payee_id: null, derivation: { payee: { pass: 'user' } } });
		const same = Draft.of(decided).clearField(1, 'payee');
		expect(field(decided, same, preview(decided), 'payee').canReset).toBe(false);
	});
});

describe('entryViews: a value a rule set that the draft changes', () => {
	const ruled = (derivation: Record<string, unknown>) =>
		unit({
			anchor_entry_id: 1,
			entries: [
				entry({
					id: 1,
					unit_key: 1,
					type: 'flow',
					category_id: 10,
					payee_id: 20,
					derivation
				})
			]
		});
	const fieldsOf = (base: ReturnType<typeof ruled>, draft: Draft) =>
		views(draft, preview(base), base)[0].fields;
	const answered = (base: ReturnType<typeof ruled>, name: 'category' | 'payee', value: number) => {
		const out = preview(base);
		out.rows[0].fields[name] = fieldOut(value, { pass: 'user' });
		return out;
	};

	it('is flagged for a category whose stored key is a rule, once another value is in the draft', () => {
		const base = ruled({ category: { pass: 'rule', basis: { rule_id: 3 } } });
		const draft = Draft.of(base).setField(1, 'category', 11, null);

		const shown = views(draft, answered(base, 'category', 11), base)[0].fields;
		expect(shown.category.changedFromRule).toBe(true);
		expect(fieldsOf(base, Draft.of(base)).category.changedFromRule).toBe(false);
	});

	it('is flagged for a payee and for a type, not for a counter-account', () => {
		const base = ruled({
			payee: { pass: 'rule', basis: { rule_id: 3 } },
			type: { pass: 'rule', basis: { rule_id: 4 } }
		});
		const draft = Draft.of(base).setField(1, 'payee', 21, null);

		const shown = views(draft, answered(base, 'payee', 21), base)[0].fields;
		expect(shown.payee.changedFromRule).toBe(true);
		expect(shown.counter_account.changedFromRule).toBe(false);
	});

	it('is not flagged for history, the model, the user or the own account', () => {
		for (const key of [
			{ pass: 'history', basis: { agree: 3, of: 4 } },
			{ pass: 'llm', basis: {} },
			{ pass: 'user' },
			{ pass: 'own_account' }
		]) {
			const base = ruled({ category: key });
			const draft = Draft.of(base).setField(1, 'category', 11, null);

			const shown = views(draft, answered(base, 'category', 11), base)[0].fields;
			expect(shown.category.changedFromRule).toBe(false);
		}
	});

	it('is not flagged while a rule still decides the value shown', () => {
		const base = ruled({ category: { pass: 'rule', basis: { rule_id: 3 } } });
		const out = preview(base);
		out.rows[0].fields.category = fieldOut(11, { pass: 'rule', basis: { rule_id: 4 } });
		const draft = Draft.of(base).clearField(1, 'category');

		expect(views(draft, out, base)[0].fields.category.changedFromRule).toBe(false);
	});
});

describe('entryViews: the pair key', () => {
	it('keeps a transfer pair\'s counter-account "matched automatically"', () => {
		const base = unit({
			anchor_entry_id: 1,
			entries: [
				entry({
					id: 1,
					unit_key: 1,
					type: 'transfer',
					counter_account_id: 2,
					derivation: { counterpart: { pass: 'matcher_decision', basis: {} } }
				})
			]
		});
		const [view] = views(Draft.of(base), null, base);
		expect(view.pairEvidence?.text).toBe('matched automatically');
	});
});

describe('entryViews: tags', () => {
	const tagged = unit({
		anchor_entry_id: 1,
		entries: [entry({ id: 1, unit_key: 1, source_transaction_id: 5, tag_ids: [30] })]
	});
	const withTags = (draft: Draft, shown: ReturnType<typeof preview> | null, stale = false) =>
		entryViews({ unit: tagged, draft, preview: shown, rules, locale: 'en', stale })[0].tagIds;

	it('shows the stored tags, then the draft applied, before any preview', () => {
		expect(withTags(Draft.of(tagged), null)).toEqual([30]);
		expect(withTags(Draft.of(tagged).toggleTag(1, 31), null)).toEqual([30, 31]);
	});

	it('takes the preview row’s tags when it is the draft’s own', () => {
		const shown = preview(tagged);
		shown.rows[0].tag_ids = [31];
		expect(withTags(Draft.of(tagged).toggleTag(1, 31), shown)).toEqual([31]);
	});

	it('takes the draft’s tags while the preview is not its own yet', () => {
		const shown = preview(tagged); // answers the draft before the toggle
		expect(withTags(Draft.of(tagged).toggleTag(1, 30), shown, true)).toEqual([]);
	});

	it('gives a new split row the tags of its original, the change on top', () => {
		const draft = Draft.of(tagged).addSplit(1).toggleTag(-1, 31);
		const rows = entryViews({ unit: tagged, draft, preview: null, rules, locale: 'en' });
		expect(rows.at(-1)!.tagIds).toEqual([30, 31]);
	});
});
