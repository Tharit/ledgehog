import { describe, expect, it } from 'vitest';
import {
	classifyDimensionError,
	describeFailure,
	describeHeld,
	isFieldFailure,
	needsReload
} from './errors.js';

describe('classifyDimensionError', () => {
	it('routes a conflict by its reason', () => {
		expect(
			classifyDimensionError({ code: 'conflict', details: { reason: 'duplicate_name' } })
		).toEqual({
			kind: 'duplicate_name'
		});
		expect(classifyDimensionError({ code: 'conflict', details: { reason: 'cycle' } })).toEqual({
			kind: 'cycle'
		});
		expect(
			classifyDimensionError({ code: 'conflict', details: { reason: 'into_descendant' } })
		).toEqual({ kind: 'into_descendant' });
	});

	it('keeps the counts that hold a category or payee', () => {
		const held = { entries: 3, rules: 1, children: 0 };
		expect(
			classifyDimensionError({ code: 'conflict', details: { reason: 'category_in_use', held } })
		).toEqual({ kind: 'in_use', held });
		expect(
			classifyDimensionError({
				code: 'conflict',
				details: { reason: 'payee_in_use', held: { entries: 2 } }
			})
		).toEqual({ kind: 'in_use', held: { entries: 2 } });
	});

	it('keeps what a moved count was and is', () => {
		expect(
			classifyDimensionError({
				code: 'conflict',
				details: { reason: 'filter_result_changed', expected: 3, actual: 5 }
			})
		).toEqual({ kind: 'count_changed', expected: 3, actual: 5 });
	});

	it('names the field of a stale reference', () => {
		expect(
			classifyDimensionError({ code: 'stale_reference', details: { field: 'into', id: 4 } })
		).toEqual({ kind: 'stale', field: 'into' });
		expect(classifyDimensionError({ code: 'stale_reference' })).toEqual({
			kind: 'stale',
			field: null
		});
	});

	it('takes the first message of a validation error', () => {
		expect(
			classifyDimensionError({
				code: 'validation_error',
				details: [{ location: ['body', 'into'], message: 'cannot merge into itself' }]
			})
		).toEqual({ kind: 'validation', message: 'cannot merge into itself' });
	});

	it('routes the transport codes, and falls back to other', () => {
		expect(classifyDimensionError({ code: 'network_error' })).toEqual({ kind: 'network' });
		expect(classifyDimensionError({ code: 'not_found' })).toEqual({ kind: 'not_found' });
		expect(classifyDimensionError({ code: 'conflict', details: { reason: 'new' } })).toEqual({
			kind: 'other'
		});
		expect(classifyDimensionError({ code: 'boom' })).toEqual({ kind: 'other' });
	});
});

describe('needsReload', () => {
	it('reloads the lists after a stale reference, a vanished row or a changed count', () => {
		expect(needsReload({ kind: 'stale', field: 'into' })).toBe(true);
		expect(needsReload({ kind: 'not_found' })).toBe(true);
		expect(needsReload({ kind: 'count_changed', expected: 1, actual: 2 })).toBe(true);
		expect(needsReload({ kind: 'cycle' })).toBe(false);
		expect(needsReload({ kind: 'validation', message: 'x' })).toBe(false);
	});
});

describe('describeHeld', () => {
	it('lists the non-zero counts with their nouns', () => {
		expect(describeHeld({ entries: 3, rules: 1, children: 2 })).toBe(
			'3 entries, 1 rule, 2 subcategories'
		);
		expect(describeHeld({ entries: 1, rules: 0, children: 0 })).toBe('1 entry');
		expect(describeHeld({})).toBe('');
	});
});

describe('describeFailure', () => {
	it('says what a duplicate name collided with', () => {
		expect(describeFailure({ kind: 'duplicate_name' }, 'category', 'Food')).toContain('"Food"');
		expect(describeFailure({ kind: 'duplicate_name' }, 'payee', 'REWE')).toBe(
			'A payee named "REWE" already exists.'
		);
	});

	it('offers merge when something is in use', () => {
		expect(describeFailure({ kind: 'in_use', held: { entries: 2 } }, 'payee')).toBe(
			'This payee is still in use (2 entries). Merge it into another payee instead.'
		);
	});

	it('shows the new count of a changed result', () => {
		expect(
			describeFailure({ kind: 'count_changed', expected: 3, actual: 5 }, 'category')
		).toContain('5 entries');
	});

	it('names the stale field', () => {
		expect(describeFailure({ kind: 'stale', field: 'into' }, 'category')).toMatch(
			/^The merge target no longer exists/
		);
	});
});

describe('isFieldFailure', () => {
	it('puts a taken name and a rejected value under the field, everything else on the dialog', () => {
		expect(isFieldFailure({ kind: 'duplicate_name' })).toBe(true);
		expect(isFieldFailure({ kind: 'validation', message: 'x' })).toBe(true);
		expect(isFieldFailure({ kind: 'network' })).toBe(false);
		expect(isFieldFailure({ kind: 'other' })).toBe(false);
		expect(isFieldFailure({ kind: 'stale', field: null })).toBe(false);
	});
});
