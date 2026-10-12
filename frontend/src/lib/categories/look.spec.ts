import { describe, expect, it } from 'vitest';
import { category } from '#lib/ledger/fixtures.js';
import { inheritHint } from './look.js';

function map(...items: ReturnType<typeof category>[]) {
	return new Map(items.map((c) => [c.id, c]));
}

describe('inheritHint', () => {
	it('says nothing for a category with its own icon and colour', () => {
		const own = category({ id: 1, icon: 'car', color: 'slate' });

		expect(inheritHint(own, map(own))).toBeNull();
	});

	it('names the parent both come from', () => {
		const parent = category({ id: 1, name: 'Food', icon: 'utensils', color: 'sage' });
		const child = category({ id: 2, parent_id: 1, icon: null, color: null });

		expect(inheritHint(child, map(parent, child))).toBe('icon and colour inherited from Food');
	});

	it('finds the nearest ancestor that has one', () => {
		const root = category({ id: 1, name: 'Food', icon: null, color: 'sage' });
		const mid = category({
			id: 2,
			name: 'Groceries',
			parent_id: 1,
			icon: 'shopping-cart',
			color: null
		});
		const leaf = category({ id: 3, parent_id: 2, icon: null, color: null });

		expect(inheritHint(leaf, map(root, mid, leaf))).toBe(
			'icon inherited from Groceries, colour inherited from Food'
		);
	});

	it('names only the part that is inherited', () => {
		const parent = category({ id: 1, name: 'Food', color: 'sage' });
		const child = category({ id: 2, parent_id: 1, icon: 'car', color: null });

		expect(inheritHint(child, map(parent, child))).toBe('colour inherited from Food');
	});

	it('calls the fallback the default', () => {
		const top = category({ id: 1, icon: null, color: null });

		expect(inheritHint(top, map(top))).toBe('default icon and colour');
	});

	it('treats a name outside the fixed sets as none', () => {
		const parent = category({ id: 1, name: 'Food', icon: 'utensils', color: 'sage' });
		const child = category({ id: 2, parent_id: 1, icon: 'not-an-icon', color: 'red' });

		expect(inheritHint(child, map(parent, child))).toBe('icon and colour inherited from Food');
	});
});
