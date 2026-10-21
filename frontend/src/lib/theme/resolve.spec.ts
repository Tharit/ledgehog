import { describe, expect, it } from 'vitest';
import type { Category } from '#lib/types/domain.js';
import { isKnownIcon, iconFor, DEFAULT_ICON } from './icons.js';
import {
	categoryPath,
	resolveAccount,
	resolveCategory,
	resolvePayee,
	resolveTag
} from './resolve.js';

function category(id: number, parent_id: number | null, over: Partial<Category> = {}): Category {
	return {
		id,
		parent_id,
		name: `c${id}`,
		kind: 'expense',
		sort_order: 0,
		icon: null,
		color: null,
		...over
	};
}

function tree(...items: Category[]): Map<number, Category> {
	return new Map(items.map((c) => [c.id, c]));
}

describe('resolveCategory', () => {
	it('uses its own icon and colour', () => {
		const c = category(1, null, { icon: 'car', color: 'slate' });
		expect(resolveCategory(c, tree(c))).toEqual({ icon: 'car', color: 'slate' });
	});

	it('takes the parent’s when it has none, up to the top level', () => {
		const top = category(1, null, { icon: 'house', color: 'forest' });
		const mid = category(2, 1);
		const leaf = category(3, 2);
		expect(resolveCategory(leaf, tree(top, mid, leaf))).toEqual({ icon: 'house', color: 'forest' });
	});

	it('inherits icon and colour independently', () => {
		const top = category(1, null, { color: 'plum' });
		const leaf = category(2, 1, { icon: 'coffee' });
		expect(resolveCategory(leaf, tree(top, leaf))).toEqual({ icon: 'coffee', color: 'plum' });
	});

	it('treats an unknown name as none, so the parent’s applies', () => {
		const top = category(1, null, { icon: 'wine', color: 'olive' });
		const leaf = category(2, 1, { icon: 'no-such-icon', color: 'hotpink' });
		expect(resolveCategory(leaf, tree(top, leaf))).toEqual({ icon: 'wine', color: 'olive' });
	});

	it('falls back to shapes and stone with nothing anywhere, and for a missing category', () => {
		const lone = category(1, null);
		expect(resolveCategory(lone, tree(lone))).toEqual({ icon: 'shapes', color: 'stone' });
		expect(resolveCategory(undefined, tree())).toEqual({ icon: 'shapes', color: 'stone' });
	});

	it('survives a parent cycle and a dangling parent', () => {
		const a = category(1, 2);
		const b = category(2, 1);
		expect(resolveCategory(a, tree(a, b))).toEqual({ icon: 'shapes', color: 'stone' });
		const orphan = category(3, 99, { color: 'teal' });
		expect(resolveCategory(orphan, tree(orphan)).color).toBe('teal');
	});
});

describe('categoryPath', () => {
	it('names the categories from the top down', () => {
		const top = category(1, null, { name: 'Food' });
		const leaf = category(2, 1, { name: 'Groceries' });
		expect(categoryPath(leaf, tree(top, leaf))).toBe('Food › Groceries');
		expect(categoryPath(top, tree(top, leaf))).toBe('Food');
	});

	it('survives a cycle', () => {
		const a = category(1, 2, { name: 'A' });
		const b = category(2, 1, { name: 'B' });
		expect(categoryPath(a, tree(a, b))).toBe('B › A');
	});
});

describe('resolveAccount', () => {
	it('keeps its own icon and colour', () => {
		expect(resolveAccount({ kind: 'checking', icon: 'vault', color: 'ochre' })).toEqual({
			icon: 'vault',
			color: 'ochre'
		});
	});

	it('derives the icon from its kind and the colour from stone', () => {
		const kinds = {
			checking: 'landmark',
			savings: 'piggy-bank',
			card: 'credit-card',
			cash: 'wallet',
			digital_wallet: 'wallet-cards',
			depot: 'chart-line',
			loan: 'hand-coins',
			asset: 'gem'
		};
		for (const [kind, icon] of Object.entries(kinds)) {
			expect(resolveAccount({ kind, icon: null, color: null })).toEqual({ icon, color: 'stone' });
		}
	});

	it('falls back for an unknown kind, icon or colour', () => {
		expect(resolveAccount({ kind: 'mystery', icon: 'nope', color: 'nope' })).toEqual({
			icon: 'shapes',
			color: 'stone'
		});
	});
});

describe('resolvePayee and resolveTag', () => {
	it('shows the initial in place of a missing icon', () => {
		expect(resolvePayee({ name: ' rewe', icon: null, color: null })).toEqual({
			icon: null,
			color: 'stone',
			initial: 'R'
		});
		expect(resolvePayee({ name: '', icon: null, color: null }).initial).toBe('?');
	});

	it('keeps a known icon and colour, and drops unknown ones', () => {
		expect(resolvePayee({ name: 'DB', icon: 'train-front', color: 'slate' })).toMatchObject({
			icon: 'train-front',
			color: 'slate'
		});
		expect(resolvePayee({ name: 'DB', icon: 'x', color: 'y' })).toMatchObject({
			icon: null,
			color: 'stone'
		});
	});

	it('tags default to stone', () => {
		expect(resolveTag({ color: 'lavender' }).color).toBe('lavender');
		expect(resolveTag({ color: null }).color).toBe('stone');
	});
});

describe('icons', () => {
	it('knows the curated names and rejects others', () => {
		expect(isKnownIcon('shopping-cart')).toBe(true);
		expect(isKnownIcon('arrow-left-right')).toBe(true);
		expect(isKnownIcon('circle-question-mark')).toBe(true);
		expect(isKnownIcon('toString')).toBe(false);
		expect(isKnownIcon(null)).toBe(false);
		expect(isKnownIcon('')).toBe(false);
	});

	it('gives the default for an unknown or missing name', () => {
		expect(iconFor('no-such')).toBe(iconFor(DEFAULT_ICON));
		expect(iconFor(undefined)).toBe(iconFor(DEFAULT_ICON));
		expect(iconFor('car')).not.toBe(iconFor(DEFAULT_ICON));
	});
});
