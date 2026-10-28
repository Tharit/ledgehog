import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import Picker from './picker.svelte';

const items = [
	{ id: 1, label: 'Food' },
	{ id: 2, label: 'Rent', disabled: 'current parent' }
];

function setup(props: Record<string, unknown> = {}) {
	const onselect = vi.fn();
	render(Picker, { props: { items, label: 'Categories', onselect, ...props } });
	return { onselect };
}

const find = () => screen.getByLabelText('Search Categories');

describe('Picker', () => {
	it('chooses an item and filters by the find box', async () => {
		const { onselect } = setup();

		await fireEvent.input(find(), { target: { value: 'foo' } });
		expect(screen.queryByRole('option', { name: /Rent/ })).toBeNull();
		await fireEvent.click(screen.getByRole('option', { name: /Food/ }));

		expect(onselect).toHaveBeenCalledWith(1);
	});

	it('draws a tag item as a chip and an icon item as a tile', async () => {
		setup({
			items: [
				{ id: 1, label: 'Lisbon', color: 'lavender', tag: true },
				{ id: 2, label: 'Giro', icon: 'landmark', color: 'forest' }
			]
		});

		const [chipRow, tileRow] = await screen.findAllByRole('option');
		expect(chipRow.querySelector('[data-slot="tag-chip"]')).not.toBeNull();
		expect(chipRow.querySelector('span[style*="--tile-fg"]')).toBeNull();
		expect(tileRow.querySelector('[data-slot="tag-chip"]')).toBeNull();
		expect(tileRow.querySelector('span[style*="--tile-fg"] svg')).not.toBeNull();
	});

	it('shows why an item cannot be chosen', () => {
		setup();

		expect(screen.getByRole('option', { name: /Rent/ })).toHaveTextContent('current parent');
	});

	it('offers to add a name nothing has, only where adding is allowed', async () => {
		const oncreate = vi.fn();
		setup({ oncreate, createLabel: (name: string) => `Add tag “${name}”` });

		await fireEvent.input(find(), { target: { value: 'Holiday' } });
		await fireEvent.click(screen.getByRole('option', { name: 'Add tag “Holiday”' }));

		expect(oncreate).toHaveBeenCalledWith('Holiday');
	});

	it('offers no add row for a name that exists, or without oncreate', async () => {
		const oncreate = vi.fn();
		const { unmount } = render(Picker, {
			props: { items, label: 'Tags', oncreate, onselect: vi.fn() }
		});
		await fireEvent.input(screen.getByLabelText('Search Tags'), { target: { value: 'food' } });
		expect(screen.queryByRole('option', { name: /Add/ })).toBeNull();
		unmount();

		setup();
		await fireEvent.input(find(), { target: { value: 'Holiday' } });
		expect(screen.queryByRole('option', { name: /Add/ })).toBeNull();
		expect(screen.getByText('No match.')).toBeInTheDocument();
	});

	it('says what is missing in one line, and an error instead of the list', () => {
		const { unmount } = render(Picker, {
			props: { items: [], label: 'Tags', emptyText: 'No tags yet.', onselect: vi.fn() }
		});
		expect(screen.getByText('No tags yet.')).toBeInTheDocument();
		unmount();

		setup({ error: 'The list could not be loaded.' });
		expect(screen.getByRole('alert')).toHaveTextContent('The list could not be loaded.');
		expect(screen.queryByRole('option')).toBeNull();
	});
});
