import { render, screen, within } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import { groupAccounts } from '#lib/accounts/list.js';
import { account } from '#lib/ledger/fixtures.js';
import AccountGroups from './account-groups.svelte';

const eur = (amount: number) => ({ amount, currency: 'EUR' });
const usd = (amount: number) => ({ amount, currency: 'USD' });
const props = { today: '2026-10-20' };

function groups() {
	return groupAccounts(
		[
			account({ id: 1, name: 'Giro', kind: 'checking', balance: eur(150000) }),
			account({ id: 2, name: 'Cash', kind: 'cash', balance: eur(5000) }),
			account({ id: 3, name: 'Wallet', kind: 'cash', sort_order: 1, balance: eur(2550) }),
			account({ id: 4, name: 'Old savings', kind: 'savings', closed_on: '2026-01-01' })
		],
		[
			{ kind: 'checking', accounts: 1, sums: [eur(150000)] },
			{ kind: 'cash', accounts: 2, sums: [eur(7550)] },
			{ kind: null, accounts: 1, sums: [eur(0)] }
		]
	);
}

const group = (key: string) => document.querySelector<HTMLElement>(`[data-group="${key}"]`)!;
const headers = (key: string) =>
	within(group(key))
		.getAllByRole('columnheader')
		.map((h) => h.textContent?.trim());

describe('the grouped accounts list', () => {
	it('is a card per kind, its title row inside,, the closed accounts last, every account in its group', () => {
		render(AccountGroups, { props: { groups: groups(), ...props } });

		const sections = [...document.querySelectorAll<HTMLElement>('[data-group]')];
		expect(sections.map((s) => s.dataset.group)).toEqual(['checking', 'cash', 'closed']);
		expect(screen.getByRole('heading', { name: 'Cash (2)' })).toBeInTheDocument();
		expect(screen.getByRole('heading', { name: 'Checking (1)' })).toBeInTheDocument();
		expect(group('closed')).toHaveAttribute('data-closed');
		const links = within(group('cash')).getAllByRole('link');
		expect(links.map((a) => a.getAttribute('href'))).toEqual(['/accounts/2', '/accounts/3']);
		// the kind icon stands in the heading, the Closed one has none
		expect(group('cash').querySelector('h2 svg')).not.toBeNull();
		// the title is the card's first row, over the header row in one band, not on the background
		const title = group('cash').querySelector('[data-slot="card-title"]')!;
		expect(title).toHaveClass('bg-muted');
		expect(title.parentElement).toHaveClass('rounded-xl');
		expect(title.nextElementSibling).toHaveAttribute('role', 'table');
		expect(group('closed').querySelector('h2 svg')).toBeNull();
	});

	it('has a header row of Account, Data age, Notices and Balance, the currency named once where shared', () => {
		render(AccountGroups, { props: { groups: groups(), ...props } });

		expect(headers('cash')).toEqual(['Account', 'Data age', 'Notices', 'Balance (EUR)']);
		const row = group('cash').querySelector('[data-account-id="2"]')!;
		expect(row).toHaveTextContent('50.00');
		expect(row).not.toHaveTextContent('EUR');
	});

	it('names the header "Balance" and the code in each cell where the currencies are mixed', () => {
		const mixed = groupAccounts(
			[
				account({ id: 1, kind: 'cash', balance: eur(5000) }),
				account({ id: 2, kind: 'cash', currency: 'USD', balance: usd(700) })
			],
			[{ kind: 'cash', accounts: 2, sums: [eur(5000), usd(700)] }]
		);
		render(AccountGroups, { props: { groups: mixed, ...props } });

		expect(headers('cash')).toEqual(['Account', 'Data age', 'Notices', 'Balance']);
		expect(group('cash').querySelector('[data-account-id="1"]')).toHaveTextContent('50.00 EUR');
		expect(group('cash').querySelector('[data-account-id="2"]')).toHaveTextContent('7.00 USD');
	});

	it('ends a group of several accounts in a Total row, a sum per currency, never converted', () => {
		render(AccountGroups, { props: { groups: groups(), ...props } });

		const total = group('cash').querySelector<HTMLElement>('[data-total-row]')!;
		expect(total).toHaveTextContent('Total');
		expect(total).toHaveTextContent('75.50');
		expect(total).not.toHaveTextContent('Total of'); // no count
		// one account: no total
		expect(group('checking').querySelector('[data-total-row]')).toBeNull();
		expect(group('closed').querySelector('[data-total-row]')).toBeNull();

		const mixed = groupAccounts(
			[
				account({ id: 1, kind: 'cash', balance: eur(5000) }),
				account({ id: 2, kind: 'cash', currency: 'USD', balance: usd(700) })
			],
			[{ kind: 'cash', accounts: 2, sums: [eur(5000), usd(700)] }]
		);
		document.body.innerHTML = '';
		render(AccountGroups, { props: { groups: mixed, ...props } });
		const row = group('cash').querySelector<HTMLElement>('[data-total-row]')!;
		expect(row).toHaveTextContent('50.00 EUR');
		expect(row).toHaveTextContent('7.00 USD');
	});

	it('shows the kind beneath the name in the Closed group only', () => {
		render(AccountGroups, { props: { groups: groups(), ...props } });

		expect(within(group('closed')).getByText('Savings')).toBeInTheDocument();
		expect(within(group('cash')).queryByText('Cash', { selector: 'span.text-xs' })).toBeNull();
		expect(group('checking')).not.toHaveTextContent('Checking beneath');
	});

	it('shows the data age and the notices in columns of their own', () => {
		const list = groupAccounts(
			[
				account({
					id: 1,
					kind: 'checking',
					last_data_on: '2026-10-17',
					anchored: false,
					unexplained_difference: eur(-1240)
				})
			],
			[{ kind: 'checking', accounts: 1, sums: [eur(0)] }]
		);
		render(AccountGroups, { props: { groups: list, ...props } });

		const row = group('checking').querySelector<HTMLElement>('[data-account-id="1"]')!;
		expect(row.querySelector('[data-fact="age"]')).toHaveTextContent('Data from 3 days ago');
		const notices = row.querySelector<HTMLElement>('[data-slot="notices"]')!;
		expect(notices).toHaveTextContent('Balance not anchored');
		expect(notices).toHaveTextContent('Unexplained difference −12.40');
	});

	it('adds a gain and a return column to the depot and asset cards, "—" where there is no return', () => {
		const list = groupAccounts(
			[
				account({
					id: 1,
					kind: 'depot',
					balance: eur(100000),
					net_deposits: eur(94000),
					gain: eur(6000),
					return_rate: 620,
					return_as_of: '2026-10-01'
				}),
				account({
					id: 2,
					kind: 'depot',
					balance: eur(500),
					net_deposits: eur(400),
					gain: eur(100),
					return_rate: null
				})
			],
			[
				{ kind: 'depot', accounts: 2, sums: [eur(100500)] },
				{ kind: 'cash', accounts: 0, sums: [] }
			]
		);
		render(AccountGroups, { props: { groups: list, ...props } });

		expect(headers('depot')).toEqual([
			'Account',
			'Data age',
			'Notices',
			'Gain (EUR)',
			'Return',
			'Balance (EUR)'
		]);
		const first = group('depot').querySelector<HTMLElement>('[data-account-id="1"]')!;
		expect(first.querySelector('[data-slot="gain"]')).toHaveTextContent('+60.00');
		expect(first.querySelector('[data-slot="return"]')).toHaveTextContent('6.2');
		const second = group('depot').querySelector<HTMLElement>('[data-account-id="2"]')!;
		expect(second.querySelector('[data-slot="return"]')).toHaveTextContent('—');
	});

	it('says "No accounts yet" when there is no group', () => {
		render(AccountGroups, { props: { groups: [], ...props } });

		expect(screen.getByText('No accounts yet')).toBeInTheDocument();
	});
});
