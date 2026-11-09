import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import type { SourceLine } from '#lib/accounts/sources.js';
import { account } from '#lib/ledger/fixtures.js';
import AccountSummary from './account-summary.svelte';

const file: SourceLine = {
	instanceId: 1,
	label: 'Giro export',
	importer: 'csv',
	kind: 'file',
	disabled: false,
	otherLogin: null
};
const fetcher: SourceLine = {
	instanceId: 2,
	label: 'Giro login',
	importer: 'testfetch',
	kind: 'fetch',
	disabled: false,
	otherLogin: null
};

function summary(sources: SourceLine[], over: Parameters<typeof account>[0] = {}) {
	const onfetch = vi.fn();
	render(AccountSummary, {
		props: {
			account: account({ id: 7, ...over }),
			sources,
			today: '2026-10-18',
			onfetch
		}
	});
	return onfetch;
}

const line = (id: number) =>
	document.querySelector(`[data-source-instance="${id}"]`) as HTMLElement;

describe('AccountSummary: the balance card', () => {
	it('has the balance as its figure and the facts as its rows', () => {
		summary([]);

		const card = screen.getByRole('region', { name: 'Balance' });
		expect(within(card).getByRole('heading', { name: 'Balance' })).toBeInTheDocument();
		expect(card.querySelector('[data-fact="age"]')).not.toBeNull();
	});

	it('says the date the balance is known for, "as of <date>"', () => {
		summary([], { balance_as_of: '2026-10-14' });

		const card = screen.getByRole('region', { name: 'Balance' });
		expect(card).toHaveTextContent('as of Oct 14, 2026');
		expect(within(card).queryByText('Today')).toBeNull();
	});

	it('shows no date where the balance is known for none, and keeps the subtitle line', () => {
		summary([], { balance_as_of: null });

		const card = screen.getByRole('region', { name: 'Balance' });
		expect(card).not.toHaveTextContent('as of');
		expect(card.querySelector('header p')).not.toBeNull();
	});

	it('has no account actions: they are the page header’s', () => {
		summary([]);

		expect(screen.queryByRole('button', { name: 'Set balance' })).toBeNull();
		expect(screen.queryByRole('link', { name: 'View entries' })).toBeNull();
	});
});

describe('AccountSummary: the sources', () => {
	it('offers "Upload file" on a file importer and "Fetch" on one that fetches', () => {
		summary([file, fetcher]);

		expect(within(line(1)).getByRole('link', { name: 'Upload file' })).toBeInTheDocument();
		expect(within(line(1)).queryByRole('button', { name: 'Fetch' })).toBeNull();
		expect(within(line(2)).getByRole('button', { name: 'Fetch' })).toBeInTheDocument();
		expect(within(line(2)).queryByRole('link', { name: 'Upload file' })).toBeNull();
	});

	it('asks for the fetch of the instance on its line', async () => {
		const onfetch = summary([fetcher]);

		await fireEvent.click(screen.getByRole('button', { name: 'Fetch' }));

		expect(onfetch).toHaveBeenCalledWith(2);
	});

	it('shows whose login the other user’s source is, in place of its action', () => {
		summary([{ ...fetcher, otherLogin: { name: 'Ben' } }, file]);

		expect(within(line(2)).getByText('Ben’s login')).toBeInTheDocument();
		expect(within(line(2)).queryByRole('button', { name: 'Fetch' })).toBeNull();
		expect(within(line(1)).getByRole('link', { name: 'Upload file' })).toBeInTheDocument();
	});

	it('cannot fetch from a disabled instance', () => {
		summary([{ ...fetcher, disabled: true }]);

		expect(screen.getByRole('button', { name: 'Fetch' })).toBeDisabled();
	});
});

describe('AccountSummary: a clearance account', () => {
	it('says it is fed by the orders of its providers, each linking to the documents filtered by it', () => {
		render(AccountSummary, {
			props: {
				account: account({ id: 7, kind: 'clearance', providers: ['amazon', 'pay pal'] }),
				sources: [],
				today: '2026-10-18'
			}
		});

		expect(screen.getByRole('link', { name: 'amazon' })).toHaveAttribute(
			'href',
			'/documents?provider=amazon'
		);
		expect(screen.getByRole('link', { name: 'pay pal' })).toHaveAttribute(
			'href',
			'/documents?provider=pay%20pal'
		);
		expect(screen.getByText(/charges decided as transfers to it/)).toBeInTheDocument();
		expect(screen.queryByText(/Entered by hand/)).toBeNull();
	});
});

describe('AccountSummary: the performance card', () => {
	const invest = {
		kind: 'investment' as const,
		net_deposits: { amount: 6_500_000, currency: 'EUR' },
		gain: { amount: 400_000, currency: 'EUR' },
		return_as_of: '2026-10-14'
	};
	const show = (over: Parameters<typeof account>[0]) =>
		render(AccountSummary, { props: { account: account(over), sources: [], today: '2026-10-18' } });

	it('shows net deposits, gain and return p.a. as of the latest record', () => {
		show({ ...invest, return_rate: 623 });

		const card = screen.getByRole('region', { name: 'Performance' });
		expect(card).toHaveTextContent('as of Oct 14, 2026');
		expect(card.querySelector('[data-slot="gain"]')).toHaveTextContent('+4,000.00');
		expect(card.querySelector('[data-slot="net-deposits"]')).toHaveTextContent('65,000.00');
		expect(card.querySelector('[data-slot="net-deposits"] [title]')?.getAttribute('title')).toMatch(
			/not the cost of what is held/
		);
		expect(card).toHaveTextContent('Return p.a.');
		expect(card.querySelector('[data-slot="return"]')).toHaveTextContent('+6.2');
		expect(card.querySelector('[data-slot="return"]')).toHaveTextContent('p.a.');
	});

	it('shows a dash with the reason as help where there is no return', () => {
		show({ ...invest, return_rate: null });

		const ret = screen
			.getByRole('region', { name: 'Performance' })
			.querySelector('[data-slot="return"]');
		expect(ret).toHaveTextContent('—');
		expect(ret?.querySelector('[title]')?.getAttribute('title')).toMatch(/span a year/);
	});

	it('is absent on an account without the facts', () => {
		show({});
		expect(screen.queryByRole('region', { name: 'Performance' })).toBeNull();
	});
});
