import { afterEach, describe, expect, it, vi } from 'vitest';
import { account } from '#lib/ledger/fixtures.js';
import { defaultAccountId, entryAccounts, readLastAccount, writeLastAccount } from './defaults.js';

const cash = account({ id: 1, name: 'Cash', kind: 'cash', synced: false, sort_order: 2 });
const wallet = account({ id: 2, name: 'Wallet', kind: 'cash', synced: false, sort_order: 1 });
const loan = account({ id: 3, name: 'Loan', kind: 'debt', synced: false, sort_order: 3 });
const giro = account({ id: 4, name: 'Giro', synced: true, sort_order: 0 });

afterEach(() => {
	vi.unstubAllGlobals();
});

describe('entryAccounts', () => {
	it('keeps only accounts without a bank connection (I40), in display order', () => {
		expect(entryAccounts([cash, giro, loan, wallet]).map((a) => a.id)).toEqual([2, 1, 3]);
	});
});

describe('defaultAccountId', () => {
	const available = [cash, loan];

	it('is the ledger filter when it names exactly one available account', () => {
		expect(defaultAccountId(available, { filtered: [3], lastUsed: 1 })).toBe(3);
		expect(defaultAccountId(available, { filtered: [3, 1], lastUsed: 1 })).toBe(1);
		expect(defaultAccountId(available, { filtered: [4], lastUsed: 1 })).toBe(1);
	});

	it('is the last one used when it is still available', () => {
		expect(defaultAccountId(available, { lastUsed: 3 })).toBe(3);
		expect(defaultAccountId(available, { lastUsed: 99 })).toBe(1);
	});

	it('is the only cash account, else none', () => {
		expect(defaultAccountId(available)).toBe(1);
		expect(defaultAccountId([cash, wallet, loan])).toBeNull();
		expect(defaultAccountId([loan])).toBeNull();
		expect(defaultAccountId([])).toBeNull();
	});
});

describe('the last account used', () => {
	it('is remembered per viewer', () => {
		const store = new Map<string, string>();
		vi.stubGlobal('localStorage', {
			getItem: (k: string) => store.get(k) ?? null,
			setItem: (k: string, v: string) => void store.set(k, v)
		});

		writeLastAccount(1, 5);
		writeLastAccount(2, 6);

		expect(readLastAccount(1)).toBe(5);
		expect(readLastAccount(2)).toBe(6);
		expect(readLastAccount(3)).toBeNull();
	});

	it('survives blocked storage', () => {
		vi.stubGlobal('localStorage', {
			getItem: () => {
				throw new Error('blocked');
			},
			setItem: () => {
				throw new Error('blocked');
			}
		});

		expect(readLastAccount(1)).toBeNull();
		expect(() => writeLastAccount(1, 5)).not.toThrow();
	});
});
