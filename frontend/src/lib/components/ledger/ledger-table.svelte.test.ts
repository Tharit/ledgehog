import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { tick } from 'svelte';
import { describe, expect, it, vi } from 'vitest';
import { account, entry, tag } from '#lib/ledger/fixtures.js';
import { buildLookups } from '#lib/ledger/lookups.js';
import { COLUMNS, GRID_TEMPLATE } from './columns.js';
import LedgerTable from './ledger-table.svelte';

const lookups = buildLookups({
	accounts: [account(), account({ id: 2, name: 'Cash' })],
	tags: [tag({ id: 30, name: 'Lisbon' }), tag({ id: 31, name: 'Tax' })]
});
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
		// the box spans the table's width, its content centred
		const box = screen.getByText('No entries match these filters').parentElement;
		expect(box).toHaveClass('w-full', 'items-center', 'text-center');
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

	it('always shows every column, header cells in the order of the column definition', () => {
		table({ lookups: buildLookups({ accounts: [account()] }) });

		const headers = screen.getAllByRole('columnheader').map((h) => h.textContent?.trim());
		expect(headers).toEqual(COLUMNS.map((c) => c.header));
		expect(headers[1]).toBe('Account');
		expect(screen.getAllByRole('row')[0].style.gridTemplateColumns).toBe(GRID_TEMPLATE);
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

describe('LedgerTable: focus and scrolling', () => {
	it('hands the keyboard to the list without scrolling the page to it', async () => {
		const focus = vi.spyOn(HTMLElement.prototype, 'focus');
		const scroll = vi.fn();
		Element.prototype.scrollIntoView = scroll;
		const { component } = table();

		component.enterList();
		await tick();

		const grid = screen.getByRole('grid');
		const onGrid = focus.mock.calls.filter((_, i) => focus.mock.contexts[i] === grid);
		expect(onGrid.length).toBeGreaterThan(0);
		for (const [options] of onGrid) expect(options).toEqual({ preventScroll: true });
		// only the cursor row is scrolled, and only to where it is visible
		expect(scroll).toHaveBeenCalledWith({ block: 'nearest' });
		for (const context of scroll.mock.contexts) {
			expect(context).not.toBe(grid);
			expect((context as HTMLElement).dataset.entryId).toBeDefined();
		}
		focus.mockRestore();
	});

	it('moving the cursor scrolls the row only, never the whole grid', async () => {
		const scroll = vi.fn();
		Element.prototype.scrollIntoView = scroll;
		table();

		await key('j');
		await key('j');

		expect(scroll.mock.calls.length).toBeGreaterThan(0);
		for (const context of scroll.mock.contexts) {
			expect((context as HTMLElement).getAttribute('role')).toBe('row');
		}
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

	it('the help stays in view: fixed to the viewport, not inside the list', async () => {
		table();

		await key('?');

		const help = screen.getByRole('region', { name: 'Keyboard shortcuts' });
		expect(help).toHaveClass('fixed');
		expect(screen.getByRole('grid')).not.toContainElement(help);
	});

	it('the footer button shows and hides the help, and reports its state', async () => {
		table();
		const button = screen.getByRole('button', { name: /Keyboard shortcuts/ });
		expect(button).toHaveAttribute('aria-expanded', 'false');

		await fireEvent.click(button);
		expect(button).toHaveAttribute('aria-expanded', 'true');
		expect(screen.getByRole('region', { name: 'Keyboard shortcuts' })).toBeInTheDocument();

		await fireEvent.click(button);
		expect(screen.queryByRole('region', { name: 'Keyboard shortcuts' })).toBeNull();
	});

	it('enterList leaves a field, focuses the list and puts the cursor on the first row', async () => {
		const { component } = table();
		const field = document.createElement('input');
		document.body.append(field);
		field.focus();
		await key('j');
		await key('j');

		component.enterList();
		await tick();

		expect(document.activeElement).toBe(screen.getByRole('grid'));
		expect(cursorTexts()).toHaveLength(1);
		expect(cursorTexts()[0]).toContain('Third');
		// the list now has the keyboard again
		await fireEvent.keyDown(screen.getByRole('grid'), { key: 'j' });
		expect(cursorTexts()[0]).toContain('Second');
		field.remove();
	});

	it('enterList in an empty list sets no cursor', async () => {
		const { component } = table({ entries: [], total: 0, status: 'loading' });

		component.enterList();
		await tick();

		expect(cursorTexts()).toHaveLength(0);
	});

	it('lists the t key in the help', async () => {
		table();

		await key('?');

		const help = screen.getByRole('region', { name: 'Keyboard shortcuts' });
		expect(help).toHaveTextContent('t');
		expect(help).toHaveTextContent('Tag the row');
	});

	it('has no key for creating a rule: rules are written in the rule editor', async () => {
		const onnotice = vi.fn();
		table({ onnotice });
		await key('j');

		await key('r');

		expect(onnotice).not.toHaveBeenCalled();
		await key('?');
		expect(screen.getByRole('region', { name: 'Keyboard shortcuts' })).not.toHaveTextContent(
			/rule/i
		);
		expect(screen.queryByRole('button', { name: /rule/i })).toBeNull();
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

describe('LedgerTable: the tag picker (t)', () => {
	const toggle = () => vi.fn(async () => true);

	async function picker(props = {}) {
		const result = table({
			ontoggletag: toggle(),
			oncreatetag: toggle(),
			onnotice: vi.fn(),
			...props
		});
		await key('j');
		await key('t');
		return result;
	}

	const search = () => screen.queryByLabelText('Search tags');

	it('opens on t for the row under the cursor, listing the tags', async () => {
		await picker();

		expect(await screen.findByLabelText('Search tags')).toBeInTheDocument();
		expect(screen.getByRole('option', { name: /Lisbon/ })).toBeInTheDocument();
		expect(screen.getByRole('option', { name: /Tax/ })).toBeInTheDocument();
	});

	it('does nothing without a cursor row', async () => {
		table({ ontoggletag: toggle() });

		await key('t');

		expect(search()).toBeNull();
	});

	it('marks the tags the row already carries', async () => {
		await picker({ entries: [entry({ id: 3, tag_ids: [31] }), entry({ id: 2 })], total: 2 });

		const options = await screen.findAllByRole('option');
		const carried = options.filter((o) => o.getAttribute('data-checked') === 'true');
		expect(carried).toHaveLength(1);
		expect(carried[0]).toHaveTextContent('Tax');
		expect(carried[0]).toHaveTextContent('(tagged)');
	});

	it('adds a tag the row lacks, and removes one it carries', async () => {
		const ontoggletag = toggle();
		await picker({
			entries: [entry({ id: 3, tag_ids: [31] }), entry({ id: 2 })],
			total: 2,
			ontoggletag
		});

		await fireEvent.click(await screen.findByRole('option', { name: /Lisbon/ }));
		expect(ontoggletag).toHaveBeenLastCalledWith(3, 30, true);

		await fireEvent.click(screen.getByRole('option', { name: /Tax/ }));
		expect(ontoggletag).toHaveBeenLastCalledWith(3, 31, false);
	});

	it('follows the patched row: the check appears without closing', async () => {
		const first = [entry({ id: 3 }), entry({ id: 2 })];
		const { rerender } = await picker({ entries: first, total: 2 });
		await screen.findByRole('option', { name: /Lisbon/ });

		await rerender({ entries: [entry({ id: 3, tag_ids: [30] }), entry({ id: 2 })] });

		expect(screen.getByRole('option', { name: /Lisbon/ })).toHaveAttribute('data-checked', 'true');
		expect(search()).not.toBeNull();
		expect(cursorTexts()).toHaveLength(1);
	});

	it('Enter toggles the highlighted tag', async () => {
		const ontoggletag = toggle();
		await picker({ ontoggletag });
		const input = await screen.findByLabelText('Search tags');

		await fireEvent.keyDown(input, { key: 'ArrowDown' });
		await fireEvent.keyDown(input, { key: 'Enter' });

		expect(ontoggletag).toHaveBeenCalledWith(3, 31, true);
	});

	it('narrows the list as one types', async () => {
		await picker();
		const input = await screen.findByLabelText('Search tags');

		await fireEvent.input(input, { target: { value: 'tax' } });

		expect(screen.queryByRole('option', { name: /Lisbon/ })).toBeNull();
		expect(screen.getByRole('option', { name: /Tax/ })).toBeInTheDocument();
	});

	it('offers to create a name no tag has, and creates and tags in one step', async () => {
		const oncreatetag = toggle();
		await picker({ oncreatetag });
		const input = await screen.findByLabelText('Search tags');

		await fireEvent.input(input, { target: { value: '  Holiday ' } });
		await fireEvent.click(await screen.findByRole('option', { name: 'Create tag "Holiday"' }));

		expect(oncreatetag).toHaveBeenCalledWith(3, 'Holiday');
	});

	it('does not offer to create a name that exists (any case); it picks the tag instead', async () => {
		await picker();
		const input = await screen.findByLabelText('Search tags');

		await fireEvent.input(input, { target: { value: 'tax' } });

		expect(screen.queryByRole('option', { name: /Create tag/ })).toBeNull();
	});

	it('closes on Esc, leaving the cursor where it was', async () => {
		await picker();
		const input = await screen.findByLabelText('Search tags');

		await fireEvent.keyDown(input, { key: 'Escape' });

		await waitFor(() => expect(search()).toBeNull());
		expect(cursorTexts()[0]).toContain('Third');
	});

	it('closes when the write failed, so the notice can be read', async () => {
		await picker({ ontoggletag: vi.fn(async () => false) });

		await fireEvent.click(await screen.findByRole('option', { name: /Lisbon/ }));

		await waitFor(() => expect(search()).toBeNull());
	});

	it('refuses a derived entry with a quiet notice and opens nothing', async () => {
		const onnotice = vi.fn();
		table({
			entries: [entry({ id: 3, type: 'opening' })],
			total: 1,
			ontoggletag: toggle(),
			onnotice
		});
		await key('j');

		await key('t');

		expect(onnotice).toHaveBeenCalledWith('Derived entries cannot be tagged');
		expect(search()).toBeNull();
	});

	it('ignores t typed into a field', async () => {
		table({ ontoggletag: toggle() });
		await key('j');
		const field = document.createElement('input');
		document.body.append(field);

		await fireEvent.keyDown(field, { key: 't' });

		expect(search()).toBeNull();
		field.remove();
	});

	it('ignores t inside a dialog', async () => {
		table({ ontoggletag: toggle() });
		await key('j');
		const dialog = document.createElement('div');
		dialog.setAttribute('role', 'dialog');
		document.body.append(dialog);

		await fireEvent.keyDown(dialog, { key: 't' });

		expect(search()).toBeNull();
		dialog.remove();
	});

	it('ignores t typed into the open picker', async () => {
		const ontoggletag = toggle();
		await picker({ ontoggletag });
		const input = await screen.findByLabelText('Search tags');

		await fireEvent.keyDown(input, { key: 't' });

		expect(ontoggletag).not.toHaveBeenCalled();
		expect(screen.getAllByLabelText('Search tags')).toHaveLength(1);
	});
});

describe('LedgerTable: rows changed by the last action', () => {
	it('marks them, and keeps every row where it is', () => {
		table({ changedIds: new Set([2]) });

		const rows = screen.getAllByRole('row').slice(1);
		expect(rows).toHaveLength(3);
		expect(rows.map((r) => r.getAttribute('data-entry-id'))).toEqual(['3', '2', '1']);
		const changed = rows.filter((r) => r.hasAttribute('data-changed'));
		expect(changed).toHaveLength(1);
		expect(changed[0]).toHaveAttribute('data-entry-id', '2');
		expect(changed[0]).toHaveAttribute('title', 'changed by your last action');
	});

	it('marks rows a refresh did not return, with their own tooltip', () => {
		table({ changedIds: new Set([2]), movedIds: new Set([1]) });

		const rows = screen.getAllByRole('row').slice(1);
		const title = (id: string) =>
			rows.find((r) => r.getAttribute('data-entry-id') === id)?.getAttribute('title');
		expect(title('2')).toBe('changed by your last action');
		expect(title('1')).toBe('no longer matches, or changed elsewhere');
		expect(title('3')).toBeNull();
	});
});
