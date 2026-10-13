import { fireEvent, render, screen, within } from '@testing-library/svelte';
import PencilIcon from '@lucide/svelte/icons/pencil';
import PlusIcon from '@lucide/svelte/icons/plus';
import Trash2Icon from '@lucide/svelte/icons/trash-2';
import { describe, expect, it, vi } from 'vitest';
import RowActions, { type RowAction } from './row-actions.svelte';

function actions() {
	return {
		rename: vi.fn(),
		add: vi.fn(),
		up: vi.fn(),
		move: vi.fn(),
		remove: vi.fn()
	};
}

function categoryRow(fn = actions(), over: { menu?: RowAction[] } = {}) {
	const primary: RowAction[] = [
		{ verb: 'Rename', icon: PencilIcon, onselect: fn.rename },
		{ verb: 'Add subcategory', label: 'Add subcategory to Food', icon: PlusIcon, onselect: fn.add }
	];
	const menu: RowAction[] = over.menu ?? [
		// given out of order: the menu puts the destructive item last
		{ verb: 'Delete…', destructive: true, onselect: fn.remove },
		{ verb: 'Move up', onselect: fn.up },
		{ verb: 'Move to…', onselect: fn.move }
	];
	render(RowActions, { props: { name: 'Food', primary, menu } });
	return fn;
}

async function openMenu() {
	await fireEvent.keyDown(screen.getByRole('button', { name: 'More actions for Food' }), {
		key: 'Enter'
	});
	return screen.findByRole('menu');
}

describe('RowActions', () => {
	it('shows at most two inline icon buttons, then the ⋯ menu', () => {
		categoryRow();

		expect(screen.getAllByRole('button').map((b) => b.getAttribute('aria-label'))).toEqual([
			'Rename Food',
			'Add subcategory to Food',
			'More actions for Food'
		]);
	});

	it('moves a third primary action into the menu rather than showing three icons', async () => {
		const fn = actions();
		render(RowActions, {
			props: {
				name: 'Food',
				primary: [
					{ verb: 'Rename', icon: PencilIcon, onselect: fn.rename },
					{ verb: 'Add subcategory', icon: PlusIcon, onselect: fn.add },
					{ verb: 'Archive', icon: Trash2Icon, onselect: fn.up }
				]
			}
		});

		expect(screen.getAllByRole('button')).toHaveLength(3);
		await openMenu();
		expect(screen.getByRole('menuitem', { name: 'Archive' })).toBeInTheDocument();
	});

	it('holds the rest in the menu as text, with Delete last', async () => {
		categoryRow();

		const menu = await openMenu();

		expect(
			within(menu)
				.getAllByRole('menuitem')
				.map((i) => i.textContent?.trim())
		).toEqual(['Move up', 'Move to…', 'Delete…']);
		expect(within(menu).getByRole('menuitem', { name: 'Delete…' })).toHaveAttribute(
			'data-variant',
			'destructive'
		);
		expect(within(menu).getAllByRole('separator')).toHaveLength(1);
	});

	it('runs the action of an item chosen from the menu, and of an inline button', async () => {
		const fn = categoryRow();

		await fireEvent.click(screen.getByRole('button', { name: 'Rename Food' }));
		expect(fn.rename).toHaveBeenCalledOnce();

		const menu = await openMenu();
		await fireEvent.click(within(menu).getByRole('menuitem', { name: 'Move to…' }));
		expect(fn.move).toHaveBeenCalledOnce();
	});

	it('shows a disabled menu item as disabled', async () => {
		const fn = actions();
		categoryRow(fn, { menu: [{ verb: 'Move up', disabled: true, onselect: fn.up }] });

		const menu = await openMenu();

		expect(within(menu).getByRole('menuitem', { name: 'Move up' })).toHaveAttribute(
			'aria-disabled',
			'true'
		);
	});

	it('has no menu when nothing is left for it', () => {
		const fn = actions();
		render(RowActions, {
			props: { name: 'Rule', primary: [{ verb: 'Delete', icon: Trash2Icon, onselect: fn.remove }] }
		});

		expect(screen.getAllByRole('button')).toHaveLength(1);
		expect(screen.queryByRole('button', { name: /More actions/ })).toBeNull();
	});

	it('keeps every control in the DOM and the tab order, hidden by opacity only until hover or focus', () => {
		categoryRow();

		const wrapper = document.querySelector('[data-slot="row-actions"]') as HTMLElement;
		expect(wrapper).toHaveClass(
			'opacity-0',
			'group-hover:opacity-100',
			'group-focus-within:opacity-100',
			'has-data-[state=open]:opacity-100',
			'[@media(hover:none)]:opacity-100'
		);
		expect(wrapper.className).not.toMatch(/\b(hidden|invisible)\b/);
		for (const button of within(wrapper).getAllByRole('button')) {
			expect(button).not.toHaveAttribute('tabindex', '-1');
			expect(button).toBeEnabled();
		}
	});

	it('names an inline button by its verb in the tooltip, not a native title', () => {
		categoryRow();

		for (const button of screen.getAllByRole('button')) expect(button).not.toHaveAttribute('title');
	});
});
