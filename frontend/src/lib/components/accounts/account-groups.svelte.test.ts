import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import { groupAccounts } from '#lib/accounts/list.js';
import { account } from '#lib/ledger/fixtures.js';
import AccountGroups from './account-groups.svelte';

const eur = (amount: number) => ({
	total: { amount, currency: 'EUR' },
	unvalued: [] as { amount: { amount: number; currency: string }; accounts: number }[]
});

function groups() {
	return groupAccounts(
		[
			account({ id: 1, name: 'Giro', kind: 'checking' }),
			account({ id: 2, name: 'Cash', kind: 'cash' }),
			account({ id: 3, name: 'Wallet', kind: 'cash', sort_order: 1 }),
			account({ id: 4, name: 'Old savings', kind: 'savings', closed_on: '2026-01-01' })
		],
		[
			{ kind: 'checking', accounts: 1, net_worth: eur(150000) },
			{ kind: 'cash', accounts: 2, net_worth: eur(7550) },
			{ kind: null, accounts: 1, net_worth: eur(0) }
		],
		'EUR'
	);
}

describe('the grouped accounts list', () => {
	it('opens collapsed: a row per kind with its number of accounts and total, none of the accounts', () => {
		render(AccountGroups, { props: { groups: groups(), today: '2026-10-20' } });

		const list = screen.getByRole('list', { name: 'Accounts' });
		const rows = [...list.querySelectorAll<HTMLElement>('[data-group]')];
		expect(rows.map((r) => r.dataset.group)).toEqual(['checking', 'cash', 'closed']);
		expect(within(rows[1]).getByText('Cash')).toBeInTheDocument();
		expect(within(rows[1]).getByText('2 accounts')).toBeInTheDocument();
		expect(within(rows[1]).getByText('75.50 EUR')).toBeInTheDocument();
		expect(within(rows[0]).getByText('1 account')).toBeInTheDocument();
		expect(rows[2]).toHaveAttribute('data-closed');
		expect(within(list).queryAllByRole('link')).toHaveLength(0);
	});

	it('expands a group to its accounts in sort order and folds it again', async () => {
		render(AccountGroups, { props: { groups: groups(), today: '2026-10-20' } });

		await fireEvent.click(screen.getByRole('button', { name: 'Expand Cash' }));
		const links = within(screen.getByRole('list', { name: 'Accounts' })).getAllByRole('link');
		expect(links.map((a) => a.getAttribute('href'))).toEqual(['/accounts/2', '/accounts/3']);

		await fireEvent.click(screen.getByRole('button', { name: 'Collapse Cash' }));
		expect(screen.queryAllByRole('link')).toHaveLength(0);
	});

	it('lists the closed accounts in a last, muted group', async () => {
		render(AccountGroups, { props: { groups: groups(), today: '2026-10-20' } });

		await fireEvent.click(screen.getByRole('button', { name: 'Expand Closed' }));
		const link = screen.getByRole('link', { name: /Old savings/ });
		expect(link).toHaveAttribute('data-closed');
	});

	it('says "unvalued", not zero, for a group that could not be valued', () => {
		const unvalued = groupAccounts(
			[account({ id: 1, kind: 'cash', currency: 'USD' })],
			[
				{
					kind: 'cash',
					accounts: 1,
					net_worth: {
						total: null,
						unvalued: [{ amount: { amount: 5, currency: 'USD' }, accounts: 1 }]
					}
				}
			],
			'EUR'
		);
		render(AccountGroups, { props: { groups: unvalued, today: '2026-10-20' } });

		expect(screen.getByText('unvalued')).toBeInTheDocument();
	});

	it('says "No accounts yet" when there is no group', () => {
		render(AccountGroups, { props: { groups: [], today: '2026-10-20' } });

		expect(screen.getByText('No accounts yet')).toBeInTheDocument();
	});
});
