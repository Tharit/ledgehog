import { describe, expect, it } from 'vitest';
import { catalogEntry } from './fixtures.js';
import { deliversDocumentsOnly, kindText } from './list.js';

describe('kindText', () => {
	it('says a file importer takes a file, whatever it delivers', () => {
		expect(kindText(catalogEntry())).toBe('takes a file');
	});

	it('names what a fetching importer delivers', () => {
		const fetch = (emits: ('transactions' | 'documents' | 'rates')[]) =>
			kindText(catalogEntry({ kind: 'fetch', emits }));

		expect(fetch(['transactions'])).toBe('fetches transactions');
		expect(fetch(['documents'])).toBe('fetches documents');
		expect(fetch(['transactions', 'documents'])).toBe('fetches transactions and documents');
		expect(fetch(['transactions', 'rates'])).toBe('fetches transactions');
		expect(fetch(['rates'])).toBe('fetches');
	});
});

describe('deliversDocumentsOnly', () => {
	it('is true only where documents are delivered and transactions are not', () => {
		expect(deliversDocumentsOnly({ emits: ['documents'] })).toBe(true);
		expect(deliversDocumentsOnly({ emits: ['documents', 'transactions'] })).toBe(false);
		expect(deliversDocumentsOnly({ emits: ['transactions'] })).toBe(false);
		expect(deliversDocumentsOnly({ emits: ['rates'] })).toBe(false);
	});
});
