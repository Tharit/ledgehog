import { fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { account, category, tag } from '#lib/ledger/fixtures.js';
import { emptyFilter, type LedgerFilterState } from '#lib/ledger/filter.js';
import { buildLookups } from '#lib/ledger/lookups.js';
import FilterBar from './filter-bar.svelte';

const lookups = buildLookups({
	accounts: [account(), account({ id: 2, name: 'Cash', currency: 'USD' })],
	categories: [category()],
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

	it('leaves a placeholder for the tag-all action and renders nothing in it', () => {
		bar();

		expect(screen.queryByText(/Tag all/)).toBeNull();
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

	it('leaves the box on Esc', async () => {
		bar();
		box().focus();

		await fireEvent.keyDown(box(), { key: 'Escape' });

		expect(document.activeElement).not.toBe(box());
	});
});
