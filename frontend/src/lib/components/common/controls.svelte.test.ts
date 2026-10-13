import { fireEvent, render, screen } from '@testing-library/svelte';
import { createRawSnippet } from 'svelte';
import { describe, expect, it, vi } from 'vitest';
import ActionButton from './action-button.svelte';
import IconButton from './icon-button.svelte';

const text = (label: string) => createRawSnippet(() => ({ render: () => `<span>${label}</span>` }));
const glyph = createRawSnippet(() => ({ render: () => '<svg aria-hidden="true"></svg>' }));

describe('ActionButton', () => {
	it('is the default 32px text button, whatever its role', () => {
		for (const variant of ['primary', 'outline', 'destructive', 'ghost'] as const) {
			const { unmount } = render(ActionButton, { props: { variant, children: text('Go') } });
			expect(screen.getByRole('button', { name: 'Go' })).toHaveClass('h-8');
			unmount();
		}
	});

	it('uses one variant per role', () => {
		const { unmount } = render(ActionButton, { props: { children: text('Add') } });
		expect(screen.getByRole('button', { name: 'Add' })).toHaveClass('bg-primary');
		unmount();
		const outline = render(ActionButton, {
			props: { variant: 'outline', children: text('Cancel') }
		});
		expect(screen.getByRole('button', { name: 'Cancel' })).toHaveClass('bg-background');
		outline.unmount();
		render(ActionButton, { props: { variant: 'destructive', children: text('Delete') } });
		expect(screen.getByRole('button', { name: 'Delete' })).toHaveClass('text-destructive');
	});

	it('names what it is doing while busy, and is disabled', () => {
		render(ActionButton, { props: { busy: true, busyLabel: 'Saving…', children: text('Save') } });

		const button = screen.getByRole('button', { name: 'Saving…' });
		expect(button).toBeDisabled();
		expect(button).toHaveAttribute('aria-busy', 'true');
	});

	it('keeps its verb while busy when it has no busy label', () => {
		render(ActionButton, { props: { busy: true, children: text('Save') } });

		expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
	});

	it('stays visible when disabled, with its reason', () => {
		render(ActionButton, {
			props: { disabled: true, reason: 'Nothing to add yet', children: text('Add') }
		});

		expect(screen.getByRole('button', { name: 'Add' })).toBeDisabled();
	});

	it('passes the click on', async () => {
		const onclick = vi.fn();
		render(ActionButton, { props: { onclick, children: text('Add') } });

		await fireEvent.click(screen.getByRole('button', { name: 'Add' }));

		expect(onclick).toHaveBeenCalledOnce();
	});
});

describe('IconButton', () => {
	it('is named "<Verb> <name>"', () => {
		render(IconButton, { props: { verb: 'Rename', name: 'Food', children: glyph } });

		expect(screen.getByRole('button', { name: 'Rename Food' })).toBeInTheDocument();
	});

	it('takes a whole label where "<verb> <name>" does not read', () => {
		render(IconButton, {
			props: {
				verb: 'Add subcategory',
				name: 'Food',
				label: 'Add subcategory to Food',
				children: glyph
			}
		});

		expect(screen.getByRole('button', { name: 'Add subcategory to Food' })).toBeInTheDocument();
	});

	it('is named by its verb alone when it acts on nothing in particular', () => {
		render(IconButton, { props: { verb: 'Log out', children: glyph } });

		expect(screen.getByRole('button', { name: 'Log out' })).toBeInTheDocument();
	});

	it('has no native title: its tooltip comes from ui/tooltip', () => {
		render(IconButton, { props: { verb: 'Rename', name: 'Food', children: glyph } });

		expect(screen.getByRole('button', { name: 'Rename Food' })).not.toHaveAttribute('title');
	});

	it('is 32px, and 24px in a row', () => {
		const { unmount } = render(IconButton, {
			props: { verb: 'Rename', name: 'A', children: glyph }
		});
		expect(screen.getByRole('button', { name: 'Rename A' })).toHaveClass('size-8');
		unmount();
		render(IconButton, {
			props: { verb: 'Rename', name: 'A', compact: true, children: glyph }
		});
		expect(screen.getByRole('button', { name: 'Rename A' })).toHaveClass('size-6');
	});

	it('passes the click on, with or without a tooltip', async () => {
		const onclick = vi.fn();
		const { unmount } = render(IconButton, {
			props: { verb: 'Rename', name: 'Food', onclick, children: glyph }
		});
		await fireEvent.click(screen.getByRole('button', { name: 'Rename Food' }));
		expect(onclick).toHaveBeenCalledOnce();
		unmount();

		const bare = vi.fn();
		render(IconButton, {
			props: { verb: 'Rename', name: 'Food', tooltip: false, onclick: bare, children: glyph }
		});
		await fireEvent.click(screen.getByRole('button', { name: 'Rename Food' }));
		expect(bare).toHaveBeenCalledOnce();
	});

	it('can be disabled', () => {
		render(IconButton, {
			props: { verb: 'Move up', name: 'Food', disabled: true, children: glyph }
		});

		expect(screen.getByRole('button', { name: 'Move up Food' })).toBeDisabled();
	});
});
