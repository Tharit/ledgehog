import { describe, expect, it } from 'vitest';
import { addAndLinkOptions, canRefreshAccounts, kindOfHint, rowState } from './discovery.js';
import { catalogEntry, discoveryEntry, instance } from './fixtures.js';

describe('rowState', () => {
	it('is linked first, whatever else the row is', () => {
		expect(
			rowState(
				discoveryEntry({
					linked_account_id: 7,
					capabilities: [],
					matches_account: { id: 9, closed: true }
				})
			)
		).toEqual({ kind: 'linked', accountId: 7 });
	});

	it('is nothing to fetch when the bank offers neither bookings nor a balance', () => {
		expect(
			rowState(discoveryEntry({ capabilities: [], matches_account: { id: 3, closed: false } }))
		).toEqual({ kind: 'nothing_to_fetch' });
	});

	it('is a closed account’s when it matches a closed account, which is not offered', () => {
		expect(rowState(discoveryEntry({ matches_account: { id: 3, closed: true } }))).toEqual({
			kind: 'closed',
			accountId: 3
		});
	});

	it('is a match when it matches an open account', () => {
		expect(rowState(discoveryEntry({ matches_account: { id: 3, closed: false } }))).toEqual({
			kind: 'match',
			accountId: 3
		});
	});

	it('is new when the ledger does not know it', () => {
		expect(rowState(discoveryEntry())).toEqual({ kind: 'new' });
		// a balance alone is something to fetch
		expect(rowState(discoveryEntry({ capabilities: ['balance'] }))).toEqual({ kind: 'new' });
	});
});

describe('canRefreshAccounts', () => {
	const catalog = [catalogEntry(), catalogEntry({ name: 'testfetch', kind: 'fetch' })];

	it('is for an instance of a fetch importer that emits transactions', () => {
		expect(canRefreshAccounts(instance({ importer: 'testfetch' }), catalog)).toBe(true);
	});

	it('is not for a file importer, one that emits no transactions, or one the catalog lacks', () => {
		expect(canRefreshAccounts(instance({ importer: 'csv' }), catalog)).toBe(false);
		expect(
			canRefreshAccounts(instance({ importer: 'testfetch', emits: ['documents'] }), catalog)
		).toBe(false);
		expect(canRefreshAccounts(instance({ importer: 'gone' }), catalog)).toBe(false);
	});
});

describe('the add dialog for a row not in the ledger', () => {
	it('is prefilled with name, kind, currency and reference and ends "Add and link"', () => {
		const onadded = () => {};
		expect(addAndLinkOptions(discoveryEntry({ name: 'Testbank Giro' }), onadded)).toMatchObject({
			name: 'Testbank Giro',
			kind: 'checking',
			currency: 'EUR',
			externalRef: 'TB-GIRO',
			verb: 'Add and link',
			onadded
		});
	});

	it('takes the dialog’s default kind for a hint this ledger does not know, and leaves a missing currency free', () => {
		const options = addAndLinkOptions(
			discoveryEntry({ kind_hint: 'unheard-of', currency: null }),
			undefined
		);
		expect(options.kind).toBeUndefined();
		expect(options.currency).toBeUndefined();
		expect(kindOfHint(null)).toBeUndefined();
	});
});
