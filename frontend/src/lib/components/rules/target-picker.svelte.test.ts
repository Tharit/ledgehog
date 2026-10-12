import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import { account, category, payee } from '#lib/ledger/fixtures.js';
import { buildLookups } from '#lib/ledger/lookups.js';
import TargetPicker from './target-picker.svelte';

const lookups = buildLookups({
	accounts: [
		account({ id: 1, name: 'Giro' }),
		account({ id: 2, name: 'Old wallet', kind: 'cash', closed_on: '2025-01-01' })
	],
	categories: [
		category({ id: 10, name: 'Food' }),
		category({ id: 11, name: 'Groceries', parent_id: 10 })
	],
	payees: [payee({ id: 20, name: 'REWE' }), payee({ id: 21, name: 'Aldi' })]
});

function setup(props: Record<string, unknown> = {}) {
	const onchange = vi.fn();
	render(TargetPicker, {
		props: {
			kind: 'category',
			value: null,
			lookups,
			label: 'The category this rule sets',
			onchange,
			...props
		}
	});
	return { onchange };
}

const trigger = () => screen.getByRole('button', { name: 'The category this rule sets' });

describe('TargetPicker', () => {
	it('asks for a choice while there is none', () => {
		setup();

		expect(trigger()).toHaveTextContent('Choose a category…');
	});

	it('shows the chosen value as the ledger draws it', () => {
		setup({ value: 11 });

		expect(trigger()).toHaveTextContent('Food › Groceries');
	});

	it('lists what can be chosen, searchable, and reports the choice', async () => {
		const { onchange } = setup();

		await fireEvent.click(trigger());
		await fireEvent.input(await screen.findByLabelText('Search category'), {
			target: { value: 'groc' }
		});

		expect(screen.queryByRole('option', { name: 'Food' })).toBeNull();
		await fireEvent.click(await screen.findByRole('option', { name: /Groceries/ }));
		expect(onchange).toHaveBeenCalledWith(11);
	});

	it('links to where a missing one is created, rather than creating it', async () => {
		setup();

		await fireEvent.click(trigger());

		expect(await screen.findByRole('link', { name: /Manage categories/ })).toHaveAttribute(
			'href',
			'/settings/categories'
		);
	});

	it('lists payees for a payee', async () => {
		setup({ kind: 'payee', label: 'The payee', value: null });

		await fireEvent.click(screen.getByRole('button', { name: 'The payee' }));

		expect(await screen.findByRole('option', { name: /REWE/ })).toBeInTheDocument();
		expect(screen.getByRole('option', { name: /Aldi/ })).toBeInTheDocument();
	});

	it('leaves a closed account out of the counter-accounts', async () => {
		setup({ kind: 'counter_account', label: 'Account' });

		await fireEvent.click(screen.getByRole('button', { name: 'Account' }));

		expect(await screen.findByRole('option', { name: /Giro/ })).toBeInTheDocument();
		expect(screen.queryByRole('option', { name: /Old wallet/ })).toBeNull();
	});

	it('clears a clearable choice', async () => {
		const { onchange } = setup({ kind: 'payee', label: 'The payee', value: 20, clearable: true });

		await fireEvent.click(screen.getByRole('button', { name: 'Clear the payee' }));

		expect(onchange).toHaveBeenCalledWith(null);
	});

	it('has no clear button unless asked', () => {
		setup({ value: 11 });

		expect(screen.queryByRole('button', { name: /Clear/ })).toBeNull();
	});
});
