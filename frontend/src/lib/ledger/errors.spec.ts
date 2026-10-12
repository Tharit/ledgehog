import { describe, expect, it } from 'vitest';
import {
	DERIVED_NOT_TAGGABLE,
	describeLoadError,
	describeTagError,
	ROWS_REFRESHED,
	tagErrorEffects
} from './errors.js';

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
		expect(describeTagError({ code: 'not_found' })).toBe(
			'This entry or tag no longer exists — the list and the tag list were refreshed in place.'
		);
		expect(describeTagError({ code: 'not_found' }, 'bulk')).toBe(
			'This tag no longer exists — the tag list was refreshed.'
		);
		expect(describeTagError({ code: 'conflict', details: { reason: 'derived_entry' } })).toBe(
			DERIVED_NOT_TAGGABLE
		);
		expect(
			describeTagError({ code: 'conflict', details: { reason: 'duplicate_name' } }, 'entry', 'Trip')
		).toBe('A tag named "Trip" already exists — the tag list was refreshed.');
		expect(describeTagError({ code: 'conflict', details: null })).toBe(ROWS_REFRESHED);
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

describe('tagErrorEffects', () => {
	const conflict = (reason: string | null) => ({ code: 'conflict', details: reason && { reason } });

	it('refreshes rows and tags for a vanished entry or tag, tags only in a bulk action', () => {
		expect(tagErrorEffects({ code: 'not_found' }, 'entry')).toEqual({ rows: true, tags: true });
		expect(tagErrorEffects({ code: 'not_found' }, 'bulk')).toEqual({ rows: false, tags: true });
	});

	it('reloads the tags for a duplicate name, the rows for any other conflict', () => {
		expect(tagErrorEffects(conflict('duplicate_name'), 'entry')).toEqual({
			rows: false,
			tags: true
		});
		expect(tagErrorEffects(conflict(null), 'entry')).toEqual({ rows: true, tags: false });
	});

	it('does nothing for a derived entry, a moved filter result, or a network failure', () => {
		const none = { rows: false, tags: false };
		expect(tagErrorEffects(conflict('derived_entry'), 'entry')).toEqual(none);
		expect(tagErrorEffects(conflict('filter_result_changed'), 'bulk')).toEqual(none);
		expect(tagErrorEffects({ code: 'network_error' }, 'entry')).toEqual(none);
	});

	it('never says "Refresh the page"', () => {
		const codes = ['not_found', 'conflict', 'validation_error', 'network_error', 'x'];
		for (const code of codes) {
			expect(describeTagError({ code })).not.toMatch(/Refresh the page/);
		}
	});
});
