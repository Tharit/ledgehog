import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import { account, entry } from '#lib/ledger/fixtures.js';
import { buildLookups } from '#lib/ledger/lookups.js';
import LedgerTable from './ledger-table.svelte';

const lookups = buildLookups({ accounts: [account(), account({ id: 2, name: 'Cash' })] });
const three = [
	entry({ id: 3, display_text: 'Third' }),
	entry({ id: 2, display_text: 'Second' }),
	entry({ id: 1, display_text: 'First' })
];

function table(props = {}) {
	return render(LedgerTable, {
		props: { entries: three, total: three.length, status: 'ready', lookups, ...props }
	});
}

function key(name: string, init: KeyboardEventInit = {}) {
	return fireEvent.keyDown(document.body, { key: name, ...init });
}

function cursorTexts(): string[] {
	return screen
		.getAllByRole('row')
		.filter((row) => row.getAttribute('aria-selected') === 'true')
		.map((row) => row.textContent ?? '');
}

describe('LedgerTable: states', () => {
	it('shows 32px skeleton rows and no entries while loading', () => {
		table({ entries: [], total: 0, status: 'loading' });

		const rows = document.querySelectorAll('[data-skeleton]');
		expect(rows.length).toBeGreaterThan(5);
		expect(rows[0]).toHaveClass('h-8');
		expect(screen.getByRole('grid')).toHaveAttribute('aria-busy', 'true');
		expect(screen.queryByText(/ of /)).toBeNull();
	});

	it('explains how the ledger is fed when there is nothing at all', () => {
		table({ entries: [], total: 0 });

		expect(screen.getByText('No entries yet')).toBeInTheDocument();
		expect(screen.getByText(/synced/)).toBeInTheDocument();
		expect(screen.queryByRole('button')).toBeNull();
		expect(screen.queryByRole('link')).toBeNull();
	});

	it('names the filters when nothing matches, and clears them with one click', async () => {
		const onclearfilters = vi.fn();
		table({ entries: [], total: 0, activeFilters: ['Giro', '“rewe”'], onclearfilters });

		expect(screen.getByText('No entries match these filters')).toBeInTheDocument();
		expect(screen.getByText('Giro · “rewe”')).toBeInTheDocument();
		await fireEvent.click(screen.getByRole('button', { name: 'Clear filters' }));
		expect(onclearfilters).toHaveBeenCalledOnce();
	});

	it('offers a retry for a failure that a retry can fix', async () => {
		const onretry = vi.fn();
		table({
			entries: [],
			total: 0,
			status: 'error',
			error: { code: 'network_error', message: 'x' },
			onretry
		});

		expect(screen.getByRole('alert')).toHaveTextContent('could not be reached');
		await fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
		expect(onretry).toHaveBeenCalledOnce();
	});

	it('routes an invalid filter to a message without a retry', () => {
		table({
			entries: [],
			total: 0,
			status: 'error',
			error: { code: 'validation_error', message: 'x' },
			onretry: vi.fn()
		});

		expect(screen.getByRole('alert')).toHaveTextContent('This filter is not valid');
		expect(screen.queryByRole('button', { name: 'Try again' })).toBeNull();
	});
});

describe('LedgerTable: rows and the footer', () => {
	it('lists the entries under a header row', () => {
		table();

		expect(screen.getAllByRole('row')).toHaveLength(4);
		expect(screen.getByRole('columnheader', { name: 'Description' })).toBeInTheDocument();
		expect(screen.getByText('Second')).toBeInTheDocument();
	});

	it('hides the account column when told to', () => {
		table({ showAccount: false });

		expect(screen.queryByRole('columnheader', { name: 'Account' })).toBeNull();
	});

	it('says how many of the matches are shown', () => {
		table({ total: 1234, locale: 'en' });

		expect(screen.getByText('3 of 1,234')).toBeInTheDocument();
	});

	it('offers "Load more" only while there are more, and asks for them', async () => {
		const onloadmore = vi.fn();
		table({ total: 10, onloadmore });

		await fireEvent.click(screen.getByRole('button', { name: 'Load more' }));
		expect(onloadmore).toHaveBeenCalledOnce();
	});

	it('has no "Load more" once everything is shown', () => {
		table({ total: 3 });

		expect(screen.queryByRole('button', { name: 'Load more' })).toBeNull();
	});

	it('disables "Load more" while loading and says so', () => {
		table({ total: 10, loadingMore: true });

		expect(screen.getByRole('button', { name: /Loading/ })).toBeDisabled();
	});

	it('keeps the rows and offers a retry when "load more" fails', async () => {
		const onloadmore = vi.fn();
		table({ total: 10, moreError: { code: 'network_error', message: 'x' }, onloadmore });

		expect(screen.getByText('Second')).toBeInTheDocument();
		await fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
		expect(onloadmore).toHaveBeenCalledOnce();
	});

	it('writes the currency once amounts of several currencies are listed', () => {
		const { container } = table({
			entries: [entry({ id: 1 }), entry({ id: 2, amount: { amount: -500, currency: 'USD' } })]
		});

		expect(container.textContent).toContain(' USD');
		expect(container.textContent).toContain(' EUR');
	});

	it('leaves the currency out while all amounts share one', () => {
		const { container } = table();

		expect(container.textContent).not.toContain('EUR');
	});
});

describe('LedgerTable: the keyboard', () => {
	it('starts without a cursor; down puts it on the first row', async () => {
		table();
		expect(cursorTexts()).toHaveLength(0);

		await key('ArrowDown');

		expect(cursorTexts()).toHaveLength(1);
		expect(cursorTexts()[0]).toContain('Third');
	});

	it('moves with j and k, and with the arrows, and stops at the ends', async () => {
		table();

		await key('j');
		await key('j');
		expect(cursorTexts()[0]).toContain('Second');
		await key('k');
		expect(cursorTexts()[0]).toContain('Third');
		await key('ArrowUp');
		expect(cursorTexts()[0]).toContain('Third');
		await key('ArrowDown');
		await key('ArrowDown');
		await key('ArrowDown');
		expect(cursorTexts()[0]).toContain('First');
	});

	it('has exactly one cursor row, with the accent background', async () => {
		table();

		await key('j');
		await key('j');

		expect(cursorTexts()).toHaveLength(1);
		expect(
			screen.getAllByRole('row').filter((r) => r.classList.contains('bg-accent'))
		).toHaveLength(1);
	});

	it('moves the cursor to a clicked row', async () => {
		table();

		await fireEvent.click(screen.getByText('First'));

		expect(cursorTexts()[0]).toContain('First');
	});

	it('scrolls the cursor row into view', async () => {
		const scroll = vi.fn();
		Element.prototype.scrollIntoView = scroll;
		table();

		await key('j');

		expect(scroll).toHaveBeenCalledWith({ block: 'nearest' });
	});

	it('does nothing on Enter yet', async () => {
		table();
		await key('j');

		await key('Enter');

		expect(cursorTexts()).toHaveLength(1);
	});

	it('/ asks for the filter text box', async () => {
		const onsearch = vi.fn();
		table({ onsearch });

		await key('/');

		expect(onsearch).toHaveBeenCalledOnce();
	});

	it('ignores keys typed into a field', async () => {
		const onsearch = vi.fn();
		table({ onsearch });
		const field = document.createElement('input');
		document.body.append(field);

		await fireEvent.keyDown(field, { key: 'j' });
		await fireEvent.keyDown(field, { key: '/' });

		expect(cursorTexts()).toHaveLength(0);
		expect(onsearch).not.toHaveBeenCalled();
		field.remove();
	});

	it('? shows the keyboard help, and ? or Esc hides it', async () => {
		table();
		expect(screen.queryByRole('region', { name: 'Keyboard shortcuts' })).toBeNull();

		await key('?');
		expect(screen.getByRole('region', { name: 'Keyboard shortcuts' })).toBeInTheDocument();
		await key('Escape');
		expect(screen.queryByRole('region', { name: 'Keyboard shortcuts' })).toBeNull();

		await key('?');
		await key('?');
		expect(screen.queryByRole('region', { name: 'Keyboard shortcuts' })).toBeNull();
	});

	it('Esc leaves a focused control', async () => {
		table({ total: 10, onloadmore: vi.fn() });
		const button = screen.getByRole('button', { name: 'Load more' });
		button.focus();
		expect(document.activeElement).toBe(button);

		await key('Escape');

		expect(document.activeElement).not.toBe(button);
	});

	it('does not move the cursor on a key with a modifier', async () => {
		table();

		await key('j', { ctrlKey: true });

		expect(cursorTexts()).toHaveLength(0);
	});
});
