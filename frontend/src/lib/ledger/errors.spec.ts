import { describe, expect, it } from 'vitest';
import { describeLoadError } from './errors.js';

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
