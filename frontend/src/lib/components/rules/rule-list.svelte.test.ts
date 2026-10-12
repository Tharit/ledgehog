import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import { account, category, payee } from '#lib/ledger/fixtures.js';
import { buildLookups } from '#lib/ledger/lookups.js';
import { rule } from '#lib/rules/fixtures.js';
import RuleList from './rule-list.svelte';

const lookups = buildLookups({
	accounts: [account({ id: 3, name: 'Cash', kind: 'cash' })],
	categories: [category({ id: 10, name: 'Groceries' })],
	payees: [payee({ id: 20, name: 'REWE' })]
});

const rules = [
	rule({
		id: 1,
		name: 'Cash withdrawals',
		sets: 'counter_account',
		category_id: null,
		counter_account_id: 3,
		name_prefix: null,
		booking_text: 'ATM'
	}),
	rule({
		id: 2,
		name: 'Rewe',
		sets: 'payee',
		category_id: null,
		payee_id: 20,
		name_prefix: 'REWE SAGT DANKE',
		priority: 50
	}),
	rule({ id: 3, name: 'Groceries', condition_payee_id: 20, name_prefix: null }),
	rule({ id: 4, name: 'Landlord', purpose_regex: 'miete|rent', name_prefix: null })
];

function setup(props: Record<string, unknown> = {}) {
	const ondelete = vi.fn();
	const onretry = vi.fn();
	render(RuleList, {
		props: { rules, status: 'ready', lookups, ondelete, onretry, ...props }
	});
	return { ondelete, onretry };
}

describe('RuleList', () => {
	it('groups the rules by what they set, in evaluation order', () => {
		setup();

		const headings = screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent);
		expect(headings).toEqual(['Counter-account rules', 'Payee rules', 'Category rules']);
		const category = screen.getByRole('region', { name: 'Category rules' });
		expect(
			within(category)
				.getAllByRole('listitem')
				.map((li) => li.getAttribute('data-rule-id'))
		).toEqual(['3', '4']);
	});

	it('leaves out a group with no rules', () => {
		setup({ rules: [rules[3]] });

		expect(screen.getAllByRole('heading', { level: 2 })).toHaveLength(1);
		expect(screen.queryByText('Payee rules')).toBeNull();
	});

	it('sums up the conditions in one line, from the fields', () => {
		setup();

		expect(screen.getByText('booking text “ATM”')).toBeInTheDocument();
		expect(screen.getByText('name starts with “REWE SAGT DANKE”')).toBeInTheDocument();
		expect(screen.getByText('purpose matches /miete|rent/')).toBeInTheDocument();
		expect(screen.getByText('payee is REWE')).toBeInTheDocument();
	});

	it('shows what each sets, the way the ledger draws it', () => {
		setup();

		const cash = screen.getByRole('region', { name: 'Counter-account rules' });
		expect(cash).toHaveTextContent('→');
		expect(cash).toHaveTextContent('Cash');
		expect(screen.getByRole('region', { name: 'Payee rules' })).toHaveTextContent('REWE');
		expect(screen.getByRole('region', { name: 'Category rules' })).toHaveTextContent('Groceries');
	});

	it('shows the priority only when it is not the default', () => {
		setup();

		expect(screen.getAllByText(/^priority /)).toHaveLength(1);
		expect(screen.getByText('priority 50')).toBeInTheDocument();
	});

	it('opens a rule through its name and its Open button', () => {
		setup();

		expect(screen.getByRole('link', { name: 'Landlord' })).toHaveAttribute(
			'href',
			'/settings/rules/4'
		);
		expect(screen.getAllByRole('link', { name: 'Open' })[0]).toHaveAttribute(
			'href',
			'/settings/rules/1'
		);
	});

	it('asks to delete a rule, naming it', async () => {
		const { ondelete } = setup();

		await fireEvent.click(screen.getByRole('button', { name: 'Delete the rule Landlord' }));

		expect(ondelete).toHaveBeenCalledWith(rules[3]);
	});

	it('shows an unknown target as absent, not as a guess', () => {
		setup({ rules: [rule({ category_id: 999 })] });

		expect(screen.getByText('Unknown category')).toBeInTheDocument();
	});

	it('explains the next step when there are no rules, and links to the ledger', () => {
		setup({ rules: [] });

		expect(
			screen.getByText(
				'A rule decides entries like this one for good; start from an entry in the ledger.'
			)
		).toBeInTheDocument();
		expect(screen.getByRole('link', { name: 'Go to the ledger' })).toHaveAttribute(
			'href',
			'/ledger'
		);
	});

	it('shows placeholders while loading', () => {
		setup({ rules: [], status: 'loading' });

		expect(document.querySelector('[data-slot="rules-loading"]')).toHaveAttribute(
			'aria-busy',
			'true'
		);
		expect(screen.queryByText('No rules yet')).toBeNull();
	});

	it('offers a retry when the list could not be loaded', async () => {
		const { onretry } = setup({
			rules: [],
			status: 'error',
			failure: 'The server could not be reached.'
		});

		expect(screen.getByRole('alert')).toHaveTextContent('The rules could not be loaded');
		await fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
		expect(onretry).toHaveBeenCalledOnce();
	});
});
