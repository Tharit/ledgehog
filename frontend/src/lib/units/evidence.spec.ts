import { describe, expect, it } from 'vitest';
import {
	asKey,
	describeKey,
	isProposalPass,
	keyOf,
	knownRules,
	type RuleNames
} from './evidence.js';

const rules = knownRules((id) => (id === 3 ? 'Rewe' : undefined));
const describeIt = (key: Parameters<typeof describeKey>[0], r: RuleNames = rules) =>
	describeKey(key, r, 'en');

describe('describeKey', () => {
	it('has nothing to say without a key', () => {
		expect(describeIt(null)).toBeNull();
		expect(describeIt(undefined)).toBeNull();
	});

	it('own account is decided', () => {
		expect(describeIt({ pass: 'own_account', basis: { account_id: 2 } })).toMatchObject({
			text: 'own account',
			proposal: false
		});
	});

	it('names a rule and links to it', () => {
		expect(describeIt({ pass: 'rule', basis: { rule_id: 3 } })).toEqual({
			text: 'rule: Rewe',
			proposal: false,
			href: '/settings/rules/3'
		});
	});

	it('says "rule deleted" for a rule the loaded list lacks, or a basis without an id', () => {
		expect(describeIt({ pass: 'rule', basis: { rule_id: 9 } })?.text).toBe('rule deleted');
		expect(describeIt({ pass: 'rule', basis: {} })?.text).toBe('rule deleted');
		expect(describeIt({ pass: 'rule', basis: { rule_id: 9 } })?.href).toBeUndefined();
	});

	it('does not claim a rule is deleted before the rule list has arrived', () => {
		const loading: RuleNames = { loaded: false, name: () => undefined };
		expect(describeIt({ pass: 'rule', basis: { rule_id: 9 } }, loading)?.text).toBe('rule');
	});

	it('still names a rule it knows while the list is old, and says "deleted" only when fresh', () => {
		const old: RuleNames = { loaded: false, name: (id) => (id === 3 ? 'Rewe' : undefined) };
		expect(describeIt({ pass: 'rule', basis: { rule_id: 3 } }, old)?.text).toBe('rule: Rewe');
		expect(describeIt({ pass: 'rule', basis: { rule_id: 9 } }, old)?.text).toBe('rule');
		expect(describeIt({ pass: 'rule', basis: { rule_id: 9 } }, rules)?.text).toBe('rule deleted');
	});

	it('writes history as counts since a month, a proposal', () => {
		const e = describeIt({
			pass: 'history',
			basis: { matched_on: 'payee', agree: 3, of: 4, since: '2026-03-14' }
		});
		expect(e).toMatchObject({
			text: 'history: 3 of 4 since Mar 2026',
			proposal: true
		});
	});

	it('shows thin evidence as it is, never a percentage', () => {
		const e = describeIt({ pass: 'history', basis: { agree: 1, of: 1, since: '2026-03-01' } });
		expect(e?.text).toBe('history: 1 of 1 since Mar 2026');
		expect(e?.text).not.toContain('%');
	});

	it('copes with a history basis it does not understand', () => {
		expect(describeIt({ pass: 'history', basis: {} })?.text).toBe('history');
		expect(describeIt({ pass: 'history' })?.text).toBe('history');
	});

	it('keeps the model rationale for a popover', () => {
		expect(
			describeIt({ pass: 'llm', basis: { rationale: ' Looks like groceries ' } })
		).toMatchObject({
			text: 'suggested by the model',
			proposal: true,
			rationale: 'Looks like groceries'
		});
		expect(describeIt({ pass: 'llm', basis: { model: 'x' } })?.rationale).toBeUndefined();
	});

	it('matcher keys: a decision is decided, a proposal is not', () => {
		expect(describeIt({ pass: 'matcher_decision' })).toMatchObject({
			text: 'matched automatically',
			proposal: false
		});
		expect(describeIt({ pass: 'matcher_proposal' })).toMatchObject({
			text: 'document matched — check the split',
			proposal: true
		});
	});

	it('user without a basis is "set by you"', () => {
		expect(describeIt({ pass: 'user' })).toMatchObject({ text: 'set by you', proposal: false });
	});

	it('user with a nested basis names what was proposed', () => {
		const e = describeIt({
			pass: 'user',
			basis: { pass: 'history', basis: { agree: 3, of: 4, since: '2026-03-01' } }
		});
		expect(e?.text).toBe('confirmed by you, proposed by history (3 of 4 since Mar 2026)');
		expect(e?.proposal).toBe(false);
	});

	it('user over a model proposal keeps the rationale', () => {
		const e = describeIt({ pass: 'user', basis: { pass: 'llm', basis: { rationale: 'because' } } });
		expect(e?.text).toBe('confirmed by you, proposed by the model');
		expect(e?.rationale).toBe('because');
	});

	it('shows an unknown pass as itself', () => {
		expect(describeIt({ pass: 'future' })?.text).toBe('future');
	});
});

describe('keys of a derivation', () => {
	it('reads one field, or null', () => {
		const derivation = { category: { pass: 'rule', basis: { rule_id: 3 } }, payee: 'junk' };
		expect(keyOf(derivation, 'category')).toEqual({ pass: 'rule', basis: { rule_id: 3 } });
		expect(keyOf(derivation, 'payee')).toBeNull();
		expect(keyOf(derivation, 'type')).toBeNull();
		expect(keyOf(null, 'type')).toBeNull();
		expect(asKey({ basis: {} })).toBeNull();
	});

	it('knows the proposal passes', () => {
		expect(['history', 'llm', 'matcher_proposal'].every(isProposalPass)).toBe(true);
		expect(['rule', 'own_account', 'user', 'matcher_decision'].some(isProposalPass)).toBe(false);
	});
});
