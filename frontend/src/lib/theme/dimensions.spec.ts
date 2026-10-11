import { describe, it, expect } from 'vitest';
import { DIMENSION_COLORS, dimensionVars, resolveDimensionColor } from './dimensions.js';

describe('resolveDimensionColor', () => {
	it('keeps every name of the set', () => {
		for (const name of DIMENSION_COLORS) expect(resolveDimensionColor(name)).toBe(name);
	});

	it('maps an unknown, empty or missing name to stone', () => {
		expect(resolveDimensionColor('red')).toBe('stone');
		expect(resolveDimensionColor('')).toBe('stone');
		expect(resolveDimensionColor(null)).toBe('stone');
		expect(resolveDimensionColor(undefined)).toBe('stone');
	});
});

describe('dimensionVars', () => {
	it('names the foreground and tint variables', () => {
		expect(dimensionVars('plum')).toEqual({ fg: 'var(--dim-plum)', tint: 'var(--dim-plum-tint)' });
		expect(dimensionVars('nope').fg).toBe('var(--dim-stone)');
	});
});
