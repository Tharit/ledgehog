import { describe, expect, it } from 'vitest';
import { account } from '#lib/ledger/fixtures.js';
import { buildLookups } from '#lib/ledger/lookups.js';
import { offerOut, transferOut } from './fixtures.js';
import {
	offerGroups,
	offerHints,
	proposalEvidence,
	shownOffers,
	shownPartner,
	stateSentence
} from './transfer.js';

const lookups = buildLookups({
	accounts: [
		account({ id: 1, name: 'Giro' }),
		account({ id: 2, name: 'Savings' }),
		account({ id: 3, name: 'Cash', synced: false }),
		account({ id: 4, name: 'Card', synced: true })
	],
	categories: [],
	payees: [],
	tags: []
});
const words = { lookups, locale: 'en' };

describe('offerGroups', () => {
	it('keeps the server’s order inside two groups: open (open legs, untyped entries), paired elsewhere', () => {
		const offers = [
			offerOut({ entry_id: 5, kind: 'untyped_entry', exact: false }),
			offerOut({ entry_id: 4, kind: 'open_leg' }),
			offerOut({ entry_id: 6, kind: 'paired_elsewhere' }),
			offerOut({ entry_id: 3, kind: 'open_leg', exact: false })
		];
		const groups = offerGroups(offers);
		expect(groups.map((g) => g.label)).toEqual(['Open', 'Paired elsewhere']);
		expect(groups[0].offers.map((o) => o.entry_id)).toEqual([5, 4, 3]);
		expect(groups[1].offers.map((o) => o.entry_id)).toEqual([6]);
	});

	it('leaves out the counter-leg offer (a later wave) and empty groups', () => {
		const offers = [offerOut({ kind: 'counter_leg', entry_id: null })];
		expect(offerGroups(offers)).toEqual([]);
		expect(shownOffers(offers)).toEqual([]);
	});
});

describe('offerHints', () => {
	const none = transferOut();

	it('says an untyped entry will be typed as a transfer', () => {
		const offer = offerOut({
			effect: { types_as_transfer: true, fee: null, breaks_pair_with: [] }
		});
		expect(offerHints(offer, none, words)).toEqual(['will be typed as a transfer']);
	});

	it('says what a fee does, in the amount of the difference', () => {
		const offer = offerOut({
			effect: {
				types_as_transfer: false,
				fee: { difference: { amount: -250, currency: 'EUR' }, larger_entry_id: 1 },
				breaks_pair_with: []
			}
		});
		expect(offerHints(offer, none, words)).toEqual([
			'differs by 2.50: the difference becomes a separate flow'
		]);
	});

	it('names the pair a pick breaks, from the partner of the leg or the offer’s own pair', () => {
		const partner = {
			entry_id: 9,
			account_id: 2,
			booked_on: '2026-10-03',
			amount: { amount: 5000, currency: 'EUR' },
			description: null
		};
		const offer = offerOut({
			kind: 'paired_elsewhere',
			paired_with: { ...partner, entry_id: 8, account_id: 4 },
			effect: { types_as_transfer: false, fee: null, breaks_pair_with: [9, 8] }
		});
		const [hint] = offerHints(offer, transferOut({ partner }), words);
		expect(hint).toContain('breaks the pair with Savings · ');
		expect(hint).toContain('Card · ');
		expect(
			offerHints(
				offerOut({ effect: { types_as_transfer: false, fee: null, breaks_pair_with: [99] } }),
				none,
				words
			)
		).toEqual(['breaks the pair with its current partner']);
	});

	it('has no hint for a plain exact offer', () => {
		expect(offerHints(offerOut(), none, words)).toEqual([]);
	});
});

describe('shownPartner', () => {
	const partner = {
		entry_id: 2,
		account_id: 2,
		booked_on: '2026-10-10',
		amount: { amount: 5000, currency: 'EUR' },
		description: 'In'
	};

	it('shows a pair’s partner as a pair', () => {
		expect(shownPartner(transferOut({ state: 'paired', partner }))).toMatchObject({
			account_id: 2,
			proposal: false
		});
	});

	it('shows the proposed offer of an unpaired leg as a proposal, with its evidence', () => {
		const offers = [offerOut({ entry_id: 7, account_id: 3, proposed: true, exact: true })];
		const shown = shownPartner(transferOut({ offers, proposed_pick: { entry_id: 7 } }))!;
		expect(shown).toMatchObject({ account_id: 3, proposal: true });
		expect(proposalEvidence(shown)).toBe('proposed: exact match');
		expect(proposalEvidence({ ...shown, exact: false })).toBe('proposed: closest candidate');
	});

	it('shows the partner the preview applied from a proposal as a proposal', () => {
		const offers = [offerOut({ entry_id: 2, proposed: true })];
		expect(
			shownPartner(
				transferOut({ state: 'paired', partner, offers, proposed_pick: { entry_id: 2 } })
			)
		).toMatchObject({ proposal: true, exact: true });
	});

	it('shows nothing when there is no partner and no proposal', () => {
		expect(shownPartner(transferOut({ offers: [offerOut()] }))).toBeNull();
	});
});

describe('stateSentence', () => {
	it('says nothing of a pair', () => {
		expect(stateSentence(transferOut({ state: 'paired' }), 2, words)).toBeNull();
	});

	it('says what a waiting leg waits for, and how far that account is', () => {
		const waiting = (synced_through: string | null) =>
			transferOut({ state: 'waiting', waiting_for: { account_id: 2, synced_through } });
		expect(stateSentence(waiting('2026-10-05'), 2, words)).toBe(
			'Waiting for Savings. Its import has not reached the matching window yet (synced through Oct 5, 2026).'
		);
		expect(stateSentence(waiting(null), 2, words)).toContain('(not synced yet)');
	});

	it('says an unmatched leg’s partner is missing from a synced counter-account’s import', () => {
		expect(stateSentence(transferOut({ state: 'unmatched' }), 4, words)).toBe(
			'The partner is missing from Card’s import. Import what is missing, or convert this to a flow if it is not a transfer.'
		);
	});

	it('says only "no partner" for an unsynced counter-account (the counter-leg comes later)', () => {
		expect(stateSentence(transferOut({ state: 'unmatched' }), 3, words)).toBeNull();
	});

	it('asks where the money went when there is no counter-account', () => {
		expect(stateSentence(transferOut({ state: 'unmatched' }), null, words)).toBe(
			'Choose where the money went.'
		);
	});

	it('says an account in the currency is needed', () => {
		expect(
			stateSentence(
				transferOut({ state: 'needs_account', needs_account: { currency: 'USD' } }),
				null,
				words
			)
		).toBe('Needs an account in USD');
	});
});
