import { describe, expect, it } from 'vitest';
import { DERIVED_NOT_TAGGABLE, describeLoadError, describeTagError } from './errors.js';

describe('describeLoadError', () => {
	it('lets an unreachable server be retried', () => {
		expect(describeLoadError('network_error')).toMatchObject({ retryable: true });
	});

	it('does not offer a retry for an invalid filter or an ended session', () => {
		expect(describeLoadError('validation_error')).toMatchObject({
			title: 'This filter is not valid',
			retryable: false
		});
		expect(describeLoadError('unauthenticated').retryable).toBe(false);
	});

	it('treats every other code as a server problem worth retrying', () => {
		expect(describeLoadError('http_error').retryable).toBe(true);
		expect(describeLoadError('something_new').retryable).toBe(true);
	});
});

describe('describeTagError', () => {
	it('routes by code and conflict reason', () => {
		expect(describeTagError({ code: 'not_found' })).toMatch(/no longer exists.*Refresh/);
		expect(describeTagError({ code: 'conflict', details: { reason: 'derived_entry' } })).toBe(
			DERIVED_NOT_TAGGABLE
		);
		expect(describeTagError({ code: 'conflict', details: { reason: 'duplicate_name' } })).toMatch(
			/already exists/
		);
		expect(describeTagError({ code: 'conflict', details: null })).toMatch(/Refresh/);
		expect(describeTagError({ code: 'validation_error' })).toMatch(/did not accept/);
		expect(describeTagError({ code: 'network_error' })).toMatch(/could not be reached/);
		expect(describeTagError({ code: 'weird' })).toMatch(/Try again/);
	});

	it('never depends on the message', () => {
		expect(describeTagError({ code: 'not_found', details: 'x' })).toBe(
			describeTagError({ code: 'not_found' })
		);
	});
});
