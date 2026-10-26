import { describe, expect, it } from 'vitest';
import {
	asKey,
	describeKey,
	isPartnerBasis,
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

	it('shows the model rationale inline', () => {
		expect(describeIt({ pass: 'llm', basis: { rationale: ' Looks like groceries ' } })).toEqual({
			text: 'AI model: Looks like groceries',
			proposal: true
		});
		expect(describeIt({ pass: 'llm', basis: { model: 'x' } })?.text).toBe('AI model');
	});

	it('words the model\'s "none" answer as no fitting category, with its rationale', () => {
		expect(
			describeIt({
				pass: 'llm',
				basis: { none: true, rationale: 'a motorway toll; there is no category for tolls' }
			})
		).toEqual({
			text: 'AI model: no fitting category — a motorway toll; there is no category for tolls',
			proposal: true
		});
		expect(describeIt({ pass: 'llm', basis: { none: true } })?.text).toBe(
			'AI model: no fitting category'
		);
	});

	it('a matcher decision is decided', () => {
		expect(describeIt({ pass: 'matcher_decision' })).toMatchObject({
			text: 'matched automatically',
			proposal: false
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

	it('user over a model proposal names the model', () => {
		const e = describeIt({ pass: 'user', basis: { pass: 'llm', basis: { rationale: 'because' } } });
		expect(e?.text).toBe('confirmed by you, proposed by the model');
	});

	it('words the pair key: the partner account when known, else "matched automatically"', () => {
		const key = { pass: 'matcher_decision', basis: {} };
		expect(describeKey(key, rules, 'en', { field: 'counterpart', partnerAccount: 'Cash' })).toEqual(
			{
				text: 'paired with Cash',
				proposal: false
			}
		);
		expect(describeKey(key, rules, 'en', { field: 'counterpart' })?.text).toBe(
			'matched automatically'
		);
		expect(
			describeKey(key, rules, 'en', { field: 'counterpart', partnerAccount: undefined })?.text
		).toBe('matched automatically');
	});

	it('words a pair the user picked as set by you', () => {
		expect(
			describeKey({ pass: 'user', basis: {} }, rules, 'en', {
				field: 'counterpart',
				partnerAccount: 'Cash'
			})?.text
		).toBe('set by you');
	});

	it('leaves the same pass on another field as it was', () => {
		expect(
			describeKey({ pass: 'matcher_decision' }, rules, 'en', { field: 'category' })?.text
		).toBe('matched automatically');
	});

	it.each(['matcher_decision', 'user', 'rule'])(
		'words a counter-account that follows its partner (%s) as "from its partner"',
		(pass) => {
			const key = { pass, basis: { from: 'counterpart' } };
			expect(describeKey(key, rules, 'en')).toEqual({ text: 'from its partner', proposal: false });
			expect(isPartnerBasis(key)).toBe(true);
		}
	);

	it('tells a partner basis from any other', () => {
		expect(isPartnerBasis({ pass: 'user', basis: {} })).toBe(false);
		expect(isPartnerBasis({ pass: 'user' })).toBe(false);
		expect(isPartnerBasis(null)).toBe(false);
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
		expect(['history', 'llm'].every(isProposalPass)).toBe(true);
		expect(['rule', 'own_account', 'user', 'matcher_decision'].some(isProposalPass)).toBe(false);
	});
});

describe('describeKey: the booking pass (patterns §4.3)', () => {
	const key = { pass: 'booking', basis: {} };
	const say = (context: Parameters<typeof describeKey>[3]) =>
		describeKey(key, rules, 'en', context)?.text;

	it('says "from its document" on the type of a document booking', () => {
		expect(say({ field: 'type', booking: 'document' })).toBe('from its document');
		expect(say({})).toBe('from its document');
	});

	it('says "booked from <account>’s charge" on a counter-leg booking’s type, counter-account and pair', () => {
		for (const field of ['type', 'counter_account', 'counterpart'])
			expect(say({ field, booking: 'transfer', chargeAccount: 'Giro' })).toBe(
				'booked from Giro’s charge'
			);
		expect(say({ field: 'type', booking: 'transfer' })).toBe('booked from its charge');
	});

	it('says "counter-leg booked on <account>" on the pair of the charge', () => {
		expect(say({ field: 'counterpart', partnerAccount: 'Amazon clearing' })).toBe(
			'counter-leg booked on Amazon clearing'
		);
		expect(say({ field: 'counterpart' })).toBe('counter-leg booked');
	});

	it('is never a proposal', () => {
		expect(describeKey(key, rules, 'en', {})?.proposal).toBe(false);
	});
});
