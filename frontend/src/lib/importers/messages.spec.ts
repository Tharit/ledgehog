import { describe, expect, it } from 'vitest';
import {
	describeImporterError,
	describeUploadFailure,
	doneFromSearch,
	doneText,
	doneUrl
} from './messages.js';

describe('describeImporterError', () => {
	it('names a refused setting once, without repeating it in the plugin’s message', () => {
		expect(
			describeImporterError({
				kind: 'invalid_profile',
				setting: 'amount.column',
				message: 'amount.column: a column position counts from 1'
			})
		).toBe(
			'The server did not accept the setting “amount.column”: a column position counts from 1'
		);
	});

	it('points a refused delete at Disable', () => {
		expect(describeImporterError({ kind: 'instance_has_runs' })).toBe(
			'This importer has runs; disable it instead.'
		);
	});

	it('says each refusal of an upload in words', () => {
		expect(describeImporterError({ kind: 'file_too_large' })).toMatch(/10 MiB/);
		expect(describeImporterError({ kind: 'account_closed' })).toMatch(/closed/);
		expect(describeImporterError({ kind: 'account_not_linked' })).toMatch(/not linked/);
	});

	it('does not leak a status for an unknown failure', () => {
		expect(describeImporterError({ kind: 'other', status: 500 })).toBe(
			'The server could not do this. Try again in a moment.'
		);
	});
});

describe('describeUploadFailure', () => {
	it('says which setting to look at for a currency that differs from the account’s', () => {
		expect(
			describeUploadFailure({ kind: 'contract_violation', rule: 'currency_mismatch', message: 'x' })
		).toMatch(/currency column and the row filters/);
	});

	it('gives the importer’s own words for a file it could not read', () => {
		expect(
			describeUploadFailure({ kind: 'parse_failed', rule: null, message: 'no header row found' })
		).toBe('The file could not be read with this profile: no header row found');
	});
});

describe('what a page that saved tells the list', () => {
	it('rides in the address and is read back once', () => {
		const url = doneUrl({ action: 'saved', label: 'Giro & card' });

		expect(doneFromSearch(url.slice(url.indexOf('?')))).toEqual({
			action: 'saved',
			label: 'Giro & card'
		});
		expect(doneText({ action: 'saved', label: 'Giro' })).toBe(
			'Importer “Giro” was saved. Later uploads use the new settings.'
		);
	});

	it('ignores an address that holds nothing of the kind', () => {
		expect(doneFromSearch('')).toBeNull();
		expect(doneFromSearch('?done=exploded&label=x')).toBeNull();
	});
});
