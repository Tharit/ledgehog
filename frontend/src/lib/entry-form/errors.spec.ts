import { describe, expect, it } from 'vitest';
import { classifyEntryError } from './errors.js';

describe('classifyEntryError', () => {
	it('puts account_synced under Account', () => {
		expect(classifyEntryError({ code: 'account_synced' })).toMatchObject({
			kind: 'field',
			field: 'account'
		});
	});

	it('puts a stale account under Account and asks for the lists to be reloaded', () => {
		expect(
			classifyEntryError({ code: 'stale_reference', details: { field: 'account_id' } })
		).toMatchObject({ kind: 'field', field: 'account', reloadLookups: true });
	});

	it('routes a validation error to the field it names', () => {
		const details = [{ location: ['body', 'booked_on'], message: 'bad date', type: 'x' }];
		expect(classifyEntryError({ code: 'validation_error', details })).toEqual({
			kind: 'field',
			field: 'date',
			text: 'bad date'
		});
		expect(classifyEntryError({ code: 'validation_error', details: null })).toMatchObject({
			kind: 'error'
		});
	});

	it('tells a taken id from a version conflict by its reason', () => {
		expect(classifyEntryError({ code: 'conflict', details: { reason: 'id_taken' } }).kind).toBe(
			'id_taken'
		);
		expect(classifyEntryError({ code: 'conflict', details: { entry_ids: [3] } }).kind).toBe(
			'conflict'
		);
	});

	it('makes busy and unreachable retryable, a missing row final', () => {
		expect(classifyEntryError({ code: 'try_again' })).toMatchObject({
			kind: 'error',
			retryable: true
		});
		expect(classifyEntryError({ code: 'network_error' })).toMatchObject({
			kind: 'error',
			retryable: true
		});
		expect(classifyEntryError({ code: 'not_found' }).kind).toBe('gone');
		expect(classifyEntryError({ code: 'not_user_authored' }).kind).toBe('gone');
	});
});
