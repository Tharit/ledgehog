import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { account, category, payee, tag } from '#lib/ledger/fixtures.js';
import { emptyFilter, type LedgerFilterState } from '#lib/ledger/filter.js';
import { buildLookups } from '#lib/ledger/lookups.js';
import FilterBar from './filter-bar.svelte';

const lookups = buildLookups({
	accounts: [account(), account({ id: 2, name: 'Cash', currency: 'USD' })],
	categories: [category()],
	payees: [payee({ id: 20, name: 'REWE' }), payee({ id: 21, name: 'Kiosk', icon: 'store' })],
	tags: [tag()]
});

function bar(filter: Partial<LedgerFilterState> = {}, props = {}) {
	const onchange = vi.fn();
	const view = render(FilterBar, {
		props: {
			filter: { ...emptyFilter(), ...filter },
			lookups,
			today: '2026-10-11',
			baseCurrency: 'EUR',
			onchange,
			...props
		}
	});
	return { onchange, ...view };
}

beforeEach(() => {
	vi.useFakeTimers();
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

afterEach(() => {
	vi.useRealTimers();
	vi.unstubAllGlobals();
});

describe('FilterBar: chips', () => {
	it('shows the dimension names while nothing is filtered', () => {
		bar();

		for (const name of [
			'Any date',
			'All accounts',
			'All categories',
			'All payees',
			'Tags',
			'Review',
			'Amount'
		]) {
			expect(screen.getByRole('button', { name })).toBeInTheDocument();
		}
		expect(screen.queryByRole('button', { name: 'Clear' })).toBeNull();
	});

	it('shows what an active chip filters by', () => {
		bar({
			from: '2026-10-01',
			to: '2026-10-11',
			account_id: [1],
			tag_id: [30],
			flag: ['waiting'],
			amount_min: 5000,
			currency: 'EUR',
			direction: 'out'
		});

		expect(screen.getByRole('button', { name: 'Oct 1 – Oct 11' })).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Giro' })).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Lisbon trip' })).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Waiting' })).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Out · ≥ 50.00 EUR' })).toBeInTheDocument();
	});

	it('offers Clear only while something is filtered, and clears everything', async () => {
		const { onchange } = bar({ account_id: [1], q: 'rewe' });

		await fireEvent.click(screen.getByRole('button', { name: 'Clear' }));

		expect(onchange).toHaveBeenCalledWith(emptyFilter());
	});

	it('picks accounts from the list the accounts chip opens', async () => {
		const { onchange } = bar();

		await fireEvent.click(screen.getByRole('button', { name: 'All accounts' }));
		await fireEvent.click(await screen.findByRole('checkbox', { name: 'Cash' }));

		expect(onchange).toHaveBeenCalledWith({ ...emptyFilter(), account_id: [2] });
	});

	it('links the category and payee chips to where they are managed', async () => {
		bar();

		await fireEvent.click(screen.getByRole('button', { name: 'All categories' }));
		expect(await screen.findByRole('link', { name: 'Manage…' })).toHaveAttribute(
			'href',
			'/settings/categories'
		);
		await fireEvent.keyDown(document.activeElement ?? document.body, { key: 'Escape' });
		await fireEvent.click(screen.getByRole('button', { name: 'All payees' }));

		const hrefs = screen
			.getAllByRole('link', { name: 'Manage…' })
			.map((a) => a.getAttribute('href'));
		expect(hrefs).toContain('/settings/payees');
	});

	it('leaves a placeholder for the tag-all action and renders nothing in it', () => {
		bar();

		expect(screen.queryByText(/Tag all/)).toBeNull();
	});
});

describe('FilterBar: the lead tile of an option', () => {
	const tileOf = (row: HTMLElement) => row.querySelector<HTMLElement>('span[style*="--tile-fg"]');

	it('draws a category in its own icon and colour', async () => {
		bar();

		await fireEvent.click(screen.getByRole('button', { name: /All categories/ }));
		const row = (await screen.findByRole('checkbox', { name: 'Groceries' })).closest('label')!;

		expect(tileOf(row)?.querySelector('svg')).not.toBeNull();
		expect(tileOf(row)?.getAttribute('style')).toContain('--dim-sage');
	});

	it('draws an account in its own colour, with its kind icon, not a dot', async () => {
		bar();

		await fireEvent.click(screen.getByRole('button', { name: 'All accounts' }));
		const row = (await screen.findByRole('checkbox', { name: 'Giro' })).closest('label')!;

		expect(tileOf(row)?.querySelector('svg')).not.toBeNull();
		expect(tileOf(row)?.getAttribute('style')).toContain('--dim-forest');
		expect(row.querySelector('[data-slot="account-dot"]')).toBeNull();
	});

	it('gives a payee with no icon its initial, and one with an icon its glyph', async () => {
		bar();

		await fireEvent.click(screen.getByRole('button', { name: 'All payees' }));
		const plain = (await screen.findByRole('checkbox', { name: 'REWE' })).closest('label')!;
		const iconed = screen.getByRole('checkbox', { name: 'Kiosk' }).closest('label')!;

		expect(tileOf(plain)).toHaveTextContent('R');
		expect(tileOf(plain)?.querySelector('svg')).toBeNull();
		expect(tileOf(iconed)?.querySelector('svg')).not.toBeNull();
	});

	it('draws a tag as a chip, not a tile', async () => {
		bar();

		await fireEvent.click(screen.getByRole('button', { name: 'Tags' }));
		const row = (await screen.findByRole('checkbox', { name: 'Lisbon trip' })).closest('label')!;

		expect(row.querySelector('[data-slot="tag-chip"]')).not.toBeNull();
		expect(tileOf(row)).toBeNull();
	});
});

describe('FilterBar: the type section of the category chip', () => {
	it('lists the five types with their row icons', async () => {
		bar();

		await fireEvent.click(screen.getByRole('button', { name: 'All categories' }));
		const list = await screen.findByRole('list', { name: 'Type' });

		for (const name of ['Flow', 'Transfer', 'Opening', 'Valuation', 'Reconciliation']) {
			expect(within(list).getByRole('checkbox', { name })).toBeInTheDocument();
		}
		expect(list.querySelectorAll('svg')).toHaveLength(5);
	});

	it('adds and removes a type in the filter', async () => {
		const { onchange, rerender } = bar();

		await fireEvent.click(screen.getByRole('button', { name: 'All categories' }));
		await fireEvent.click(await screen.findByRole('checkbox', { name: 'Transfer' }));
		expect(onchange).toHaveBeenLastCalledWith({ ...emptyFilter(), type: ['transfer'] });

		await rerender({ filter: { ...emptyFilter(), type: ['transfer', 'flow'] } });
		await fireEvent.click(screen.getByRole('checkbox', { name: 'Transfer' }));
		expect(onchange).toHaveBeenLastCalledWith({ ...emptyFilter(), type: ['flow'] });
	});

	it('counts the type in the chip label', () => {
		bar({ type: ['opening'] });
		expect(screen.getByRole('button', { name: 'Type: Opening' })).toBeInTheDocument();
	});

	it('shows the category and the type together', () => {
		bar({ category_id: [10], type: ['flow', 'transfer'] });
		expect(
			screen.getByRole('button', { name: 'Groceries · Type: Flow, Transfer' })
		).toBeInTheDocument();
	});
});

describe('FilterBar: the review state chip', () => {
	it('shows each option with the badge and the sentence the rows use', async () => {
		bar();

		await fireEvent.click(screen.getByRole('button', { name: 'Review' }));
		const list = await screen.findByRole('list', { name: 'Review state' });

		expect(list.querySelectorAll('[data-flag]')).toHaveLength(4);
		expect(list.querySelector('[data-flag="waiting"]')).toHaveAttribute(
			'title',
			'Partner still expected'
		);
		expect(within(list).getByRole('checkbox', { name: 'Waiting' })).toBeInTheDocument();
		expect(list.querySelector('span[style*="--tile-fg"]')).toBeNull();
	});
});

describe('FilterBar: Export CSV', () => {
	it('is a plain link to the given address', () => {
		bar({}, { exportHref: '/api/ledger/entries/export?flag=waiting' });

		const link = screen.getByRole('link', { name: 'Export CSV' });
		expect(link).toHaveAttribute('href', '/api/ledger/entries/export?flag=waiting');
		expect(link).toHaveAttribute('data-sveltekit-reload');
		expect(screen.queryByRole('button', { name: 'Export CSV' })).not.toBeInTheDocument();
	});

	it('is left out without an address', () => {
		bar();

		expect(screen.queryByText('Export CSV')).not.toBeInTheDocument();
	});
});

describe('FilterBar: the text box', () => {
	function box() {
		return screen.getByRole('textbox', { name: 'Filter entries by text' });
	}

	it('sends the text after a pause, not on every key', async () => {
		const { onchange } = bar();

		await fireEvent.input(box(), { target: { value: 'rew' } });
		vi.advanceTimersByTime(200);
		expect(onchange).not.toHaveBeenCalled();
		await fireEvent.input(box(), { target: { value: 'rewe' } });
		vi.advanceTimersByTime(249);
		expect(onchange).not.toHaveBeenCalled();
		vi.advanceTimersByTime(1);

		expect(onchange).toHaveBeenCalledOnce();
		expect(onchange).toHaveBeenCalledWith({ ...emptyFilter(), q: 'rewe' });
	});

	it('sends at once on Enter, trimmed', async () => {
		const { onchange } = bar();

		await fireEvent.input(box(), { target: { value: ' rewe ' } });
		await fireEvent.keyDown(box(), { key: 'Enter' });

		expect(onchange).toHaveBeenCalledWith({ ...emptyFilter(), q: 'rewe' });
	});

	it('shows the text of the filter, and follows a change from outside', async () => {
		const { rerender } = bar({ q: 'start' });
		expect(box()).toHaveValue('start');

		await rerender({ filter: { ...emptyFilter(), q: 'later' } });
		expect(box()).toHaveValue('later');

		await rerender({ filter: emptyFilter() });
		expect(box()).toHaveValue('');
	});

	it('hands the keyboard to the list on ArrowDown, without changing the filter', async () => {
		const ondown = vi.fn();
		const { onchange } = bar({}, { ondown });
		box().focus();

		const notPrevented = await fireEvent.keyDown(box(), { key: 'ArrowDown' });

		expect(ondown).toHaveBeenCalledOnce();
		expect(notPrevented).toBe(false);
		expect(onchange).not.toHaveBeenCalled();
	});

	it('does not leave the box on ArrowUp', async () => {
		const ondown = vi.fn();
		bar({}, { ondown });

		await fireEvent.keyDown(box(), { key: 'ArrowUp' });

		expect(ondown).not.toHaveBeenCalled();
	});

	it('leaves the box on Esc', async () => {
		bar();
		box().focus();

		await fireEvent.keyDown(box(), { key: 'Escape' });

		expect(document.activeElement).not.toBe(box());
	});
});
