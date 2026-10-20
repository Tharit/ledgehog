import { describe, expect, it } from 'vitest';
import { sourceLines, uploadHref } from './sources.js';

describe('sourceLines', () => {
	const catalog = [
		{ name: 'csv', kind: 'file' },
		{ name: 'fints', kind: 'fetch' }
	];
	const instances = [
		{ id: 1, importer: 'csv', label: 'Giro file', accounts: [{ account_id: 7 }] },
		{ id: 2, importer: 'fints', label: 'Bank', accounts: [{ account_id: 7 }, { account_id: 8 }] },
		{ id: 3, importer: 'csv', label: 'Other', accounts: [{ account_id: 8 }] }
	];

	it('keeps the instances the account is linked to, each with its importer kind', () => {
		expect(sourceLines(7, instances, catalog)).toEqual([
			{
				instanceId: 1,
				label: 'Giro file',
				importer: 'csv',
				kind: 'file',
				disabled: false,
				otherLogin: null
			},
			{
				instanceId: 2,
				label: 'Bank',
				importer: 'fints',
				kind: 'fetch',
				disabled: false,
				otherLogin: null
			}
		]);
		expect(sourceLines(9, instances, catalog)).toEqual([]);
	});

	it('marks the other user’s login with whose it is, and nothing else', () => {
		const lines = sourceLines(
			7,
			[
				{ ...instances[1], access: 'owner', owner_name: 'Ben', manageable: false },
				{ ...instances[0], manageable: true }
			],
			catalog
		);

		expect(lines.map((l) => l.otherLogin)).toEqual([{ name: 'Ben' }, null]);
	});

	it('links the upload page with the instance chosen', () => {
		expect(uploadHref(7, 1)).toBe('/accounts/7/upload?instance=1');
	});
});
