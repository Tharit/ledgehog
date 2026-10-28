import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import { account } from '#lib/ledger/fixtures.js';
import AccountActions from './account-actions.svelte';

function actions(over = {}) {
	const handlers = {
		onsetbalance: vi.fn(),
		onedit: vi.fn(),
		onclose: vi.fn(),
		onreopen: vi.fn(),
		ondelete: vi.fn()
	};
	render(AccountActions, { props: { account: account({ id: 7 }), ...handlers, ...over } });
	return handlers;
}

describe('AccountActions', () => {
	it('has "Set balance", "View entries" of this account and the more menu', async () => {
		const { onsetbalance } = actions();

		await fireEvent.click(screen.getByRole('button', { name: 'Set balance' }));
		expect(onsetbalance).toHaveBeenCalledOnce();
		expect(screen.getByRole('link', { name: 'View entries' })).toHaveAttribute(
			'href',
			'/ledger?account_id=7'
		);
		expect(screen.getByRole('button', { name: /More actions/ })).toBeInTheDocument();
	});
});
