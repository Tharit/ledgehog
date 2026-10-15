import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { account, entry } from '#lib/ledger/fixtures.js';
import { buildLookups } from '#lib/ledger/lookups.js';
import { source } from '#lib/rules/fixtures.js';
import { FIND_DEBOUNCE_MS, RuleExampleStore } from '#lib/stores/rule-example.svelte.js';
import RuleExample from './rule-example.svelte';

// components never import the API, not even in tests: the mocks come from here
const api = vi.hoisted(() => ({ getEntry: vi.fn(), listEntries: vi.fn() }));
vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	...api
}));

/** what the API client throws: only the status and the code matter to the store */
const failure = (status: number, code: string) => Object.assign(new Error(code), { status, code });

const lookups = buildLookups({ accounts: [account({ id: 1, name: 'Giro' })] });

const rewe = entry({
	id: 11,
	booked_on: '2026-10-09',
	amount: { amount: -4731, currency: 'EUR' },
	source: source({
		counterparty_name: 'REWE Markt GmbH',
		purpose: 'Einkauf 09.10. Kartenzahlung girocard mit einem sehr langen Verwendungszweck',
		booking_text: 'KARTENZAHLUNG'
	})
});
const spotify = entry({
	id: 12,
	booked_on: '2026-10-05',
	amount: { amount: -999, currency: 'EUR' },
	source: source({
		counterparty_name: 'Spotify AB',
		purpose: 'Premium',
		booking_text: 'LASTSCHRIFT'
	})
});
const handmade = entry({ id: 13, source: null, display_text: 'Coffee at Starbucks' });

function find(entries = [rewe, spotify], total = entries.length) {
	vi.mocked(api.listEntries).mockResolvedValue({ entries, total, limit: 8, offset: 0 });
}

function setup(options: ConstructorParameters<typeof RuleExampleStore>[0] = {}) {
	const onchange = vi.fn();
	const store = new RuleExampleStore({ onchange, ...options });
	render(RuleExample, { props: { store, lookups } });
	return { store, onchange };
}

const box = () => screen.getByRole('combobox', { name: 'Find an entry' });

async function type(text: string) {
	await fireEvent.input(box(), { target: { value: text } });
	await vi.advanceTimersByTimeAsync(FIND_DEBOUNCE_MS);
}

beforeEach(() => {
	vi.useFakeTimers();
	vi.resetAllMocks();
});

afterEach(() => {
	vi.useRealTimers();
});

describe('RuleExample: without an example', () => {
	it('shows the find box, with a label and a helper line and no placeholder', () => {
		setup();

		expect(box()).not.toHaveAttribute('placeholder');
		expect(
			screen.getByText(/Type part of a counterparty, purpose or booking text/)
		).toBeInTheDocument();
		expect(screen.queryByRole('button', { name: 'Change' })).toBeNull();
		expect(screen.queryByRole('table')).toBeNull();
	});

	it('says nothing is filled in from the example', () => {
		setup();

		expect(screen.getByText(/Nothing is filled in from it/)).toBeInTheDocument();
	});

	it('searches after a pause and lists the results under column headers', async () => {
		find();
		setup();

		await type('rewe');

		expect(api.listEntries).toHaveBeenCalledTimes(1);
		const header = document.querySelector('[data-slot="example-results-header"]')!;
		expect(header.textContent).toContain('Booked');
		expect(header.textContent).toContain('Amount');
		expect(header.textContent).toContain('Counterparty name');
		expect(header.textContent).toContain('Purpose');
		expect(header.textContent).toContain('Booking text');
		const options = screen.getAllByRole('option');
		expect(options).toHaveLength(2);
		expect(options[0]).toHaveTextContent('Oct 9, 2026');
		expect(options[0]).toHaveTextContent('−47.31');
		expect(options[0]).toHaveTextContent('REWE Markt GmbH');
		expect(options[0]).toHaveTextContent('KARTENZAHLUNG');
		expect(options[0]).toHaveAttribute('aria-selected', 'true');
	});

	it('says it is searching, then that nothing matches', async () => {
		find([]);
		setup();

		await fireEvent.input(box(), { target: { value: 'zzz' } });
		expect(screen.getByText('Searching…')).toBeInTheDocument();
		await vi.advanceTimersByTimeAsync(FIND_DEBOUNCE_MS);

		expect(screen.getByText('No entries match.')).toBeInTheDocument();
	});

	it('says the search failed and tries again', async () => {
		vi.mocked(api.listEntries).mockRejectedValueOnce(failure(0, 'network_error'));
		setup();
		await type('rewe');
		expect(screen.getByText('The search failed.')).toBeInTheDocument();

		find();
		await fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
		await vi.advanceTimersByTimeAsync(0);

		expect(screen.getAllByRole('option')).toHaveLength(2);
	});

	it('says how many results there are when it shows only some', async () => {
		find([rewe, spotify], 40);
		setup();

		await type('shop');

		expect(screen.getByText(/Showing 2 of 40/)).toBeInTheDocument();
	});

	it('moves the highlight with ↓ and ↑ and names it for assistive technology', async () => {
		find();
		setup();
		await type('shop');

		await fireEvent.keyDown(box(), { key: 'ArrowDown' });
		const options = screen.getAllByRole('option');
		expect(options[1]).toHaveAttribute('aria-selected', 'true');
		expect(box()).toHaveAttribute('aria-activedescendant', options[1].id);

		await fireEvent.keyDown(box(), { key: 'ArrowUp' });
		expect(options[0]).toHaveAttribute('aria-selected', 'true');
		expect(box()).toHaveAttribute('aria-expanded', 'true');
	});

	it('picks the highlighted result with Enter and shows it as the example', async () => {
		find();
		const { onchange } = setup();
		await type('shop');
		await fireEvent.keyDown(box(), { key: 'ArrowDown' });

		await fireEvent.keyDown(box(), { key: 'Enter' });

		expect(onchange).toHaveBeenCalledWith(12);
		expect(screen.queryByRole('combobox')).toBeNull();
		expect(screen.getByRole('table', { name: 'The example entry' })).toHaveTextContent(
			'Spotify AB'
		);
	});

	it('picks a result with a click', async () => {
		find();
		const { onchange } = setup();
		await type('shop');

		await fireEvent.click(screen.getAllByRole('option')[0]);

		expect(onchange).toHaveBeenCalledWith(11);
	});

	it('never lets Enter submit anything, and leaves ⌘/Ctrl+Enter to the form', async () => {
		find();
		setup();
		await type('shop');

		const plain = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true });
		box().dispatchEvent(plain);
		expect(plain.defaultPrevented).toBe(true);

		await vi.advanceTimersByTimeAsync(0);
	});

	it('leaves ⌘/Ctrl+Enter alone: it saves the rule, not picks an example', async () => {
		find();
		const { onchange } = setup();
		await type('shop');

		const saving = new KeyboardEvent('keydown', {
			key: 'Enter',
			ctrlKey: true,
			bubbles: true,
			cancelable: true
		});
		box().dispatchEvent(saving);

		expect(saving.defaultPrevented).toBe(false);
		expect(onchange).not.toHaveBeenCalled();
	});

	it('closes the results with Esc and keeps the text', async () => {
		find();
		setup();
		await type('shop');

		await fireEvent.keyDown(box(), { key: 'Escape' });

		expect(screen.queryByRole('listbox')).toBeNull();
		expect(box()).toHaveValue('shop');
	});

	it('lists entries without a source transaction as disabled rows that cannot be picked', async () => {
		find([handmade]);
		const { onchange } = setup();

		await type('coffee');

		const option = screen.getByRole('option');
		expect(option).toHaveTextContent('No source transaction');
		expect(option).not.toHaveTextContent('Coffee at Starbucks');
		expect(option).toHaveAttribute('aria-disabled', 'true');
		expect(option).toHaveAttribute('aria-selected', 'false');
		await fireEvent.click(option);
		await fireEvent.keyDown(box(), { key: 'Enter' });
		expect(onchange).not.toHaveBeenCalled();
	});
});

describe('RuleExample: with an example', () => {
	async function opened(e = rewe, options: ConstructorParameters<typeof RuleExampleStore>[0] = {}) {
		vi.mocked(api.getEntry).mockResolvedValue(e);
		const view = setup({ initialId: e.id, ...options });
		await view.store.init();
		await vi.advanceTimersByTimeAsync(0);
		return view;
	}

	it('loads the entry the page opened with and shows its source fields, one row per field', async () => {
		await opened();

		expect(api.getEntry).toHaveBeenCalledWith(11);
		expect(screen.queryByRole('combobox')).toBeNull();
		const table = screen.getByRole('table', { name: 'The example entry' });
		const headers = within(table)
			.getAllByRole('columnheader')
			.map((h) => h.textContent);
		expect(headers).toEqual(['Field', 'Value']);
		const rowFor = (label: string) =>
			within(table).getByRole('rowheader', { name: label }).closest('tr')!;
		expect(rowFor('Counterparty name')).toHaveTextContent('REWE Markt GmbH');
		expect(rowFor('Purpose')).toHaveTextContent('sehr langen Verwendungszweck');
		expect(rowFor('Booking text')).toHaveTextContent('KARTENZAHLUNG');
		expect(rowFor('Counterparty IBAN or reference')).toHaveTextContent('None');
		expect(rowFor('Mandate reference')).toHaveTextContent('None');
	});

	it('lets a long purpose wrap rather than cut it', async () => {
		await opened();

		const cell = within(screen.getByRole('table')).getByText(/sehr langen Verwendungszweck/);
		expect(cell.className).toContain('whitespace-pre-wrap');
		expect(cell.className).not.toContain('truncate');
	});

	it('shows the date, the amount and the account', async () => {
		await opened();

		const table = screen.getByRole('table');
		expect(
			within(table).getByRole('rowheader', { name: 'Booked' }).closest('tr')
		).toHaveTextContent('Oct 9, 2026');
		expect(
			within(table).getByRole('rowheader', { name: 'Amount' }).closest('tr')
		).toHaveTextContent('−47.31');
		expect(
			within(table).getByRole('rowheader', { name: 'Account' }).closest('tr')
		).toHaveTextContent('Giro');
	});

	it('says plainly that an entry without a source transaction has none', async () => {
		await opened(handmade);

		expect(
			screen.getByText('This entry has no source transaction: rules read imported fields.')
		).toBeInTheDocument();
		expect(screen.queryByRole('rowheader', { name: 'Purpose' })).toBeNull();
	});

	it('changes: opens the find box, keeps the example, and cancel goes back', async () => {
		await opened();

		await fireEvent.click(screen.getByRole('button', { name: 'Change' }));
		expect(box()).toBeInTheDocument();
		expect(screen.getByRole('table')).toBeInTheDocument();

		await fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
		expect(screen.queryByRole('combobox')).toBeNull();
	});

	it('replaces the example with the next pick and reports it', async () => {
		find();
		const { onchange } = await opened();
		await fireEvent.click(screen.getByRole('button', { name: 'Change' }));

		await type('spot');
		await fireEvent.keyDown(box(), { key: 'ArrowDown' });
		await fireEvent.keyDown(box(), { key: 'Enter' });

		expect(onchange).toHaveBeenCalledWith(12);
		expect(screen.getByRole('table')).toHaveTextContent('Spotify AB');
	});

	it('clears: no table, the find box again, and null reported', async () => {
		const { onchange } = await opened();

		await fireEvent.click(screen.getByRole('button', { name: 'Clear' }));

		expect(onchange).toHaveBeenCalledWith(null);
		expect(screen.queryByRole('table')).toBeNull();
		expect(box()).toBeInTheDocument();
	});

	it('goes back to the example on Esc in the find box, once the results are closed', async () => {
		await opened();
		await fireEvent.click(screen.getByRole('button', { name: 'Change' }));

		await fireEvent.keyDown(box(), { key: 'Escape' });

		expect(screen.queryByRole('combobox')).toBeNull();
		expect(screen.getByRole('table')).toBeInTheDocument();
	});

	it('says so when the entry is gone, and offers the find box', async () => {
		vi.mocked(api.getEntry).mockRejectedValue(failure(404, 'not_found'));
		const { store } = setup({ initialId: 99 });
		await store.init();
		await vi.advanceTimersByTimeAsync(0);

		expect(
			screen.getByText('The example entry was not found. Choose another.')
		).toBeInTheDocument();
		expect(box()).toBeInTheDocument();
	});

	it('offers to try again when the entry could not be loaded', async () => {
		vi.mocked(api.getEntry).mockRejectedValueOnce(failure(0, 'network_error'));
		const { store } = setup({ initialId: 99 });
		await store.init();
		await vi.advanceTimersByTimeAsync(0);
		expect(screen.getByText('The example could not be loaded.')).toBeInTheDocument();

		vi.mocked(api.getEntry).mockResolvedValueOnce(rewe);
		await fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
		await vi.advanceTimersByTimeAsync(0);

		expect(screen.getByRole('table')).toBeInTheDocument();
	});
});
