import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { cash, loan } from '#lib/entry-form/fixtures.js';
import AccountSelect from './account-select.svelte';

const trigger = () => screen.getByRole('button', { name: 'Account' });

beforeEach(() => {
	// jsdom has no ResizeObserver, which the popover's positioning looks for
	vi.stubGlobal(
		'ResizeObserver',
		class {
			observe() {}
			unobserve() {}
			disconnect() {}
		}
	);
});

describe('AccountSelect', () => {
	it('shows the chosen account with its tile, or asks to choose', async () => {
		const view = render(AccountSelect, {
			props: { accounts: [cash, loan], label: 'Account', value: 3 }
		});

		expect(trigger()).toHaveTextContent('Hand loan');
		expect(trigger().querySelector('[data-slot="account-dot"]')).toBeNull();
		const tile = trigger().querySelector<HTMLElement>('span[style*="--tile-fg"]');
		expect(tile?.querySelector('svg')).not.toBeNull();
		await view.rerender({ accounts: [cash, loan], label: 'Account', value: null });
		expect(trigger()).toHaveTextContent('Choose an account…');
	});

	it('chooses an account from the list and closes it', async () => {
		const onchange = vi.fn();
		render(AccountSelect, {
			props: { accounts: [cash, loan], label: 'Account', value: null, onchange }
		});

		await fireEvent.click(trigger());
		await fireEvent.click(await screen.findByRole('option', { name: /Hand loan/ }));

		expect(onchange).toHaveBeenCalledWith(3);
		expect(trigger()).toHaveTextContent('Hand loan');
		await waitFor(() => expect(screen.queryByRole('option')).toBeNull());
	});

	it('draws each listed account as a tile, not a dot', async () => {
		render(AccountSelect, { props: { accounts: [cash, loan], label: 'Account', value: null } });

		await fireEvent.click(trigger());
		const option = await screen.findByRole('option', { name: /Hand loan/ });

		expect(option.querySelector('span[style*="--tile-fg"] svg')).not.toBeNull();
		expect(option.querySelector('[data-slot="account-dot"]')).toBeNull();
	});

	it('finds an account by typing', async () => {
		render(AccountSelect, { props: { accounts: [cash, loan], label: 'Account', value: null } });

		await fireEvent.click(trigger());
		await fireEvent.input(await screen.findByLabelText('Search account'), {
			target: { value: 'cas' }
		});

		expect(screen.queryByRole('option', { name: /Hand loan/ })).toBeNull();
		expect(screen.getByRole('option', { name: /Cash/ })).toBeInTheDocument();
	});
});
