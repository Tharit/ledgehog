import { fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { tick } from 'svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { account, entry, tag } from '#lib/ledger/fixtures.js';
import { buildLookups } from '#lib/ledger/lookups.js';
import { DERIVED_NOTICE } from '#lib/units/describe.js';
import { applyAffected, MARK_RESOLVED } from '#lib/units/patch.js';
import { unitPanel } from '#lib/units/panel-instance.js';
import { activeUnitSource } from '#lib/units/sources.js';
import { COLUMNS, GRID_TEMPLATE } from './columns.js';
import LedgerTable from './ledger-table.svelte';

vi.mock('#lib/units/panel-instance.js', () => ({ unitPanel: { open: vi.fn() } }));

beforeEach(() => vi.mocked(unitPanel.open).mockClear());

const lookups = buildLookups({
	accounts: [account(), account({ id: 2, name: 'Cash' })],
	tags: [tag({ id: 30, name: 'Lisbon' }), tag({ id: 31, name: 'Tax' })]
});
const three = [
	entry({ id: 3, description: 'Third', display_text: 'Third' }),
	entry({ id: 2, description: 'Second', display_text: 'Second' }),
	entry({ id: 1, description: 'First', display_text: 'First' })
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
		// the shared empty state: a left-aligned card
		expect(
			screen.getByText('No entries match these filters').closest('[data-slot="empty"]')
		).not.toBeNull();
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

	it('Enter opens the unit panel on the entry under the cursor', async () => {
		table();
		await key('j');
		await key('j');

		await key('Enter');

		expect(unitPanel.open).toHaveBeenCalledOnce();
		expect(vi.mocked(unitPanel.open).mock.calls[0][0]).toBe(2);
	});

	it('Enter without a cursor opens nothing', async () => {
		table();

		await key('Enter');

		expect(unitPanel.open).not.toHaveBeenCalled();
	});

	it('a click on a row opens it, a click on the tags cell edits tags instead', async () => {
		table();

		await fireEvent.click(screen.getByText('First'));
		expect(vi.mocked(unitPanel.open).mock.calls.map((c) => c[0])).toEqual([1]);

		const row = screen.getByText('Second').closest('[role="row"]') as HTMLElement;
		await fireEvent.click(within(row).getByRole('button', { name: 'Edit tags' }));
		expect(unitPanel.open).toHaveBeenCalledOnce();
	});

	it('a derived entry shows a quiet notice instead of opening', async () => {
		const onnotice = vi.fn();
		table({
			entries: [entry({ id: 5, type: 'opening', description: null })],
			total: 1,
			onnotice
		});
		await key('j');

		await key('Enter');

		expect(onnotice).toHaveBeenCalledWith(DERIVED_NOTICE);
		expect(unitPanel.open).not.toHaveBeenCalled();
	});

	it('registers as the panel source and steps past the siblings of one unit', async () => {
		table({
			entries: [
				entry({ id: 4, unit_key: 11 }),
				entry({ id: 3, unit_key: 10 }),
				entry({ id: 2, unit_key: 10 }),
				entry({ id: 1, unit_key: 9 })
			],
			total: 4
		});

		await tick();
		const source = activeUnitSource();

		expect(source?.neighbour(4, 1)).toBe(3);
		expect(source?.neighbour(3, 1)).toBe(1);
		expect(source?.neighbour(2, -1)).toBe(4);
	});

	it('moves the cursor to the unit the panel shows, and says when the entry is not in the list', async () => {
		table();
		await tick();
		const source = activeUnitSource();

		expect(source?.reveal?.(2)).toBe(true);
		await tick();

		expect(cursorTexts()).toHaveLength(1);
		expect(cursorTexts()[0]).toContain('Second');
		expect(source?.reveal?.(99)).toBe(false);
		expect(cursorTexts()[0]).toContain('Second');
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

	it('opens from a click on the tags cell, for that row', async () => {
		table({
			entries: [entry({ id: 3, tag_ids: [31] }), entry({ id: 2 })],
			total: 2,
			ontoggletag: toggle(),
			oncreatetag: toggle(),
			onnotice: vi.fn()
		});
		const rows = screen.getAllByRole('row').filter((r) => r.hasAttribute('data-entry-id'));

		await fireEvent.click(within(rows[0]).getByRole('button', { name: 'Edit tags' }));

		expect(await screen.findByLabelText('Search tags')).toBeInTheDocument();
		const carried = screen
			.getAllByRole('option')
			.filter((o) => o.getAttribute('data-checked') === 'true');
		expect(carried).toHaveLength(1);
		expect(carried[0]).toHaveTextContent(/Tax/);
		expect(rows[0]).toHaveAttribute('aria-selected', 'true');
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
		await fireEvent.click(await screen.findByRole('option', { name: 'Add tag “Holiday”' }));

		expect(oncreatetag).toHaveBeenCalledWith(3, 'Holiday');
	});

	it('does not offer to create a name that exists (any case); it picks the tag instead', async () => {
		await picker();
		const input = await screen.findByLabelText('Search tags');

		await fireEvent.input(input, { target: { value: 'tax' } });

		expect(screen.queryByRole('option', { name: /Add tag/ })).toBeNull();
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

describe('LedgerTable: marks of the unit panel (patterns §7, design §7)', () => {
	const marked = () =>
		applyAffected(three, {
			entries: [
				entry({ id: 3, description: 'Third', display_text: 'Third' }),
				entry({
					id: 2,
					description: 'Second',
					display_text: 'Second',
					review_flags: ['unconfirmed']
				}),
				entry({ id: 1, description: 'First', display_text: 'First', review_flags: ['unconfirmed'] })
			],
			resolved: [3, 1],
			confirmed: [3]
		}).marks;

	it('mutes a committed row; one that is confirmed also gets a check in its badge slot', () => {
		table({ marks: marked() });

		const rows = screen.getAllByRole('row').slice(1);
		const resolved = rows.find((r) => r.getAttribute('data-entry-id') === '3')!;
		expect(resolved).toHaveAttribute('data-resolved');
		expect(resolved).toHaveClass('text-muted-foreground');
		expect(resolved).toHaveAttribute('title', MARK_RESOLVED);
		expect(within(resolved).getByRole('img', { name: 'Confirmed' })).toBeInTheDocument();
		expect(resolved).not.toHaveAttribute('data-changed');
	});

	it('mutes a committed row that stays in review too, with its own badge and no check', () => {
		const patched = [
			entry({ id: 3, description: 'Third', display_text: 'Third' }),
			entry({ id: 2, description: 'Second', display_text: 'Second' }),
			entry({ id: 1, description: 'First', display_text: 'First', review_flags: ['unconfirmed'] })
		];
		table({ marks: marked(), entries: patched, total: patched.length });

		const staying = document.querySelector('[data-entry-id="1"]')!;
		expect(staying).toHaveAttribute('data-resolved');
		expect(staying).toHaveClass('text-muted-foreground');
		expect(within(staying as HTMLElement).queryByRole('img', { name: 'Confirmed' })).toBeNull();
		expect(staying).not.toHaveAttribute('data-changed');
		expect(staying.querySelector('[data-flag="unconfirmed"]')).not.toBeNull();
	});

	it('marks a row changed as a consequence with the ochre bar and its tooltip', () => {
		table({ marks: marked() });

		const changed = document.querySelector('[data-entry-id="2"]')!;
		expect(changed).toHaveAttribute('data-changed');
		expect(changed).toHaveAttribute('title', 'changed by your last action');
		expect(changed.querySelector('.bg-dim-ochre')).not.toBeNull();
	});

	it('tells the page which rows the cursor visits, so their marks fade', async () => {
		const onvisit = vi.fn();
		table({ marks: marked(), onvisit });

		await key('j'); // the cursor is not on a row yet: this puts it on the first
		await key('j');

		expect(onvisit).toHaveBeenCalledWith([3]);
		expect(onvisit).toHaveBeenCalledWith([2]);
	});

	it('hands the panel the end of the list: a notice, "load more", and no resolved neighbour', async () => {
		const onnotice = vi.fn();
		const onloadmore = vi.fn();
		table({ onnotice, onloadmore });
		const source = activeUnitSource()!;

		source.notice!('No more units');
		expect(onnotice).toHaveBeenCalledWith('No more units');
		expect(await source.loadMore!()).toBe(false); // nothing was added
		expect(onloadmore).toHaveBeenCalled();
	});
});

describe('LedgerTable: the entries of a unit are drawn together (patterns §4.1)', () => {
	const rows = [
		entry({ id: 5, unit_key: null, description: 'Alone', display_text: 'Alone' }),
		entry({ id: 4, unit_key: 10, amount: { amount: -300, currency: 'EUR' }, description: 'A' }),
		entry({ id: 3, unit_key: 10, amount: { amount: -200, currency: 'EUR' }, description: 'B' }),
		entry({ id: 2, unit_key: 11, type: 'transfer', description: 'Out' }),
		entry({ id: 1, unit_key: 11, type: 'transfer', description: 'In' })
	];

	it('frames adjacent rows of one unit in one bordered group and leaves single rows alone', () => {
		table({ entries: rows, total: rows.length });

		const groups = document.querySelectorAll<HTMLElement>('[role="rowgroup"]');
		expect(groups).toHaveLength(2);
		expect(groups[0].dataset.unit).toBe('10');
		expect(groups[0].className).toContain('border');
		expect(groups[0].className).toContain('group/unit');
		expect(
			[...groups[0].querySelectorAll('[role="row"]')].map((r) => (r as HTMLElement).dataset.entryId)
		).toEqual(['4', '3']);
		expect(document.querySelector('[data-entry-id="5"]')!.closest('[role="rowgroup"]')).toBeNull();
		expect(document.querySelector('[data-entry-id="4"]')).toHaveAttribute('data-joined');
		expect(document.querySelector('[data-entry-id="5"]')).not.toHaveAttribute('data-joined');
	});

	it('joins rows of a unit only when they are adjacent', () => {
		const apart = [
			entry({ id: 3, unit_key: 7 }),
			entry({ id: 2, unit_key: null }),
			entry({ id: 1, unit_key: 7 })
		];
		table({ entries: apart, total: 3 });

		expect(document.querySelectorAll('[role="rowgroup"]')).toHaveLength(0);
	});

	it('highlights the unit together: hover on the group, a lighter cursor on the siblings', async () => {
		table({ entries: rows, total: rows.length });
		await key('j'); // row 5
		await key('j'); // row 4, first of the split

		const first = document.querySelector('[data-entry-id="4"]')!;
		const second = document.querySelector('[data-entry-id="3"]')!;
		expect(first).toHaveAttribute('data-cursor');
		expect(second).not.toHaveAttribute('data-cursor');
		expect(second.className).toContain('bg-accent/60');
		expect(second.className).toContain('group-hover/unit:bg-muted');
		expect(document.querySelector('[data-entry-id="5"]')!.className).not.toContain('bg-accent');
	});

	it('marks the first row of a split with the unit total, and nothing on a pair', () => {
		table({ entries: rows, total: rows.length });

		const markers = document.querySelectorAll('[data-unit-marker]');
		expect(markers).toHaveLength(1);
		expect(document.querySelector('[data-entry-id="4"]')!.contains(markers[0])).toBe(true);
		expect(markers[0].getAttribute('title')).toMatch(/^Split total .*5\.00/);
	});
});
