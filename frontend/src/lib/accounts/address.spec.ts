import { describe, expect, it } from 'vitest';
import { accountIdOf, sourceIdOf, withSource } from './address.js';

describe('the row detail address', () => {
	it('reads a positive integer and nothing else', () => {
		expect(sourceIdOf(new URL('http://x/accounts/1?source=42'))).toBe(42);
		for (const bad of ['', '0', '-1', 'abc', '1.5'])
			expect(sourceIdOf(new URL(`http://x/accounts/1?source=${bad}`))).toBeNull();
		expect(sourceIdOf(new URL('http://x/accounts/1'))).toBeNull();
	});

	it('sets and removes `source`, keeping the rest', () => {
		const url = new URL('http://x/accounts/1?unit=3');
		expect(withSource(url, 9)).toBe('/accounts/1?unit=3&source=9');
		expect(withSource(new URL('http://x/accounts/1?source=9&unit=3'), null)).toBe(
			'/accounts/1?unit=3'
		);
	});

	it('reads the account id of the route', () => {
		expect(accountIdOf('12')).toBe(12);
		expect(accountIdOf('x')).toBeNull();
		expect(accountIdOf(undefined)).toBeNull();
	});
});
