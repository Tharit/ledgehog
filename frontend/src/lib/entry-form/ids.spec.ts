import { afterEach, describe, expect, it, vi } from 'vitest';
import { newClientId } from './ids.js';

const PATTERN = /^[A-Za-z0-9_-]{1,100}$/;

afterEach(() => {
	vi.unstubAllGlobals();
});

describe('newClientId', () => {
	it('is random and fits the API pattern', () => {
		const a = newClientId();
		expect(a).toMatch(PATTERN);
		expect(newClientId()).not.toBe(a);
	});

	it('has a fallback without randomUUID, and without any crypto', () => {
		vi.stubGlobal('crypto', { getRandomValues: (b: Uint8Array) => b.fill(7) });
		expect(newClientId()).toMatch(PATTERN);
		vi.stubGlobal('crypto', undefined);
		const id = newClientId();
		expect(id).toMatch(PATTERN);
		expect(newClientId()).not.toBe(id);
	});
});
