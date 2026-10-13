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
