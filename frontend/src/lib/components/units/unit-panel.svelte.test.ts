import { fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { account, category, entry, payee, tag } from '#lib/ledger/fixtures.js';
import { buildLookups } from '#lib/ledger/lookups.js';
import { rule, source } from '#lib/rules/fixtures.js';
import { ruleNames } from '#lib/stores/rule-names.svelte.js';
import { apiError, unit } from '#lib/units/fixtures.js';
import { UnitPanel, type PanelNav } from '#lib/units/panel.svelte.js';
import { registerUnitSource } from '#lib/units/sources.js';
import UnitPanelView from './unit-panel.svelte';

// components never import the API, not even in tests: the mocks come from here
const api = vi.hoisted(() => ({ getUnit: vi.fn(), listRules: vi.fn() }));
vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	...api
}));
const { getUnit, listRules } = api;

const lookups = buildLookups({
	accounts: [account({ id: 1, name: 'Giro' }), account({ id: 2, name: 'Savings' })],
	categories: [category({ id: 10, name: 'Groceries' })],
	payees: [payee({ id: 20, name: 'REWE' })],
	tags: [tag({ id: 30, name: 'Lisbon trip' })]
});

function nav(start = '/ledger'): PanelNav {
	const stack = [start];
	let at = 0;
	return {
		url: () => new URL(stack[at], 'http://x.test'),
		push: (url) => {
			stack.splice(at + 1);
			stack.push(url);
			at++;
		},
		replace: (url) => (stack[at] = url),
		back: () => at--
	};
}

async function openPanel(shown: ReturnType<typeof unit>, id = shown.anchor_entry_id) {
	vi.mocked(getUnit).mockResolvedValue(shown);
	const panel = new UnitPanel(nav());
	render(UnitPanelView, { props: { panel, lookups, locale: 'en' } });
	panel.open(id);
	const dialog = await screen.findByRole('dialog');
	await waitFor(() => expect(panel.status).toBe('ready'));
	return { panel, dialog };
}

beforeEach(() => {
	vi.resetAllMocks();
	ruleNames.reset();
	vi.mocked(listRules).mockResolvedValue([rule({ id: 3, name: 'Rewe' })]);
});

describe('UnitPanel: a flow unit', () => {
	it('is a modal dialog labelled by the unit title, with the state under it', async () => {
		const { dialog } = await openPanel(
			unit({
				anchor_entry_id: 1,
				entries: [entry({ id: 1, unit_key: 1, display_text: 'REWE Markt Berlin' })]
			})
		);

		expect(dialog).toHaveAccessibleName('REWE Markt Berlin');
		expect(dialog).toHaveAttribute('aria-modal', 'true');
		expect(within(dialog).getByText('Proposals to check')).toBeInTheDocument();
	});

	it('starts with focus on the panel itself, not on a field, so the step keys work at once', async () => {
		const { dialog } = await openPanel(unit());

		await waitFor(() => expect(dialog).toHaveFocus());
	});

	it('shows each value with its basis; proposals are italic, decided values are not', async () => {
		const { dialog } = await openPanel(unit());

		const history = within(dialog).getByText('history: 3 of 4 since Mar 2026');
		expect(history).toHaveAttribute('data-proposal', 'true');
		expect(history).toHaveClass('italic');
		const rule = await within(dialog).findByRole('link', { name: 'rule: Rewe' });
		expect(rule).toHaveAttribute('href', '/settings/rules/3');
		expect(rule.closest('[data-slot="evidence"]')).not.toHaveAttribute('data-proposal');
		// the proposed category is italic too; the decided payee is not
		expect(within(dialog).getByText('Groceries')).toHaveClass('italic');
		expect(within(dialog).getByText('REWE')).not.toHaveClass('italic');
	});

	it('says a rule is deleted when the loaded list lacks it', async () => {
		vi.mocked(listRules).mockResolvedValue([]);
		const { dialog } = await openPanel(unit());
		expect(await within(dialog).findByText('rule deleted')).toBeInTheDocument();
	});

	it('shows the source strip: counterparty, purpose, booking text, instructed amount', async () => {
		const { dialog } = await openPanel(
			unit({
				anchor_entry_id: 1,
				entries: [
					entry({
						id: 1,
						unit_key: 1,
						source_transaction_id: 5,
						source: source({
							counterparty_name: 'REWE Markt',
							purpose: 'Card payment 0815',
							booking_text: 'Kartenzahlung',
							instructed_amount: { amount: -5000, currency: 'USD' }
						})
					})
				]
			})
		);

		const strip = within(dialog).getByRole('region', { name: 'Source transaction' });
		expect(strip).toHaveTextContent('REWE Markt');
		expect(strip).toHaveTextContent('Card payment 0815');
		expect(strip).toHaveTextContent('Kartenzahlung');
		expect(strip).toHaveTextContent('USD');
	});

	it('shows the tags read-only and a disabled Commit with its reason', async () => {
		const { dialog } = await openPanel(
			unit({
				anchor_entry_id: 1,
				entries: [entry({ id: 1, unit_key: 1, tag_ids: [30] })]
			})
		);

		expect(within(dialog).getByText('Lisbon trip')).toBeInTheDocument();
		expect(within(dialog).getByRole('button', { name: 'Commit' })).toBeDisabled();
	});

	it('has its own keyboard help: [ ] and Esc, opened by the button or by ? inside the panel', async () => {
		const { dialog } = await openPanel(unit());
		const button = within(dialog).getByRole('button', { name: /Keyboard shortcuts/ });

		await fireEvent.click(button);
		const help = within(dialog).getByRole('region', { name: 'Keyboard shortcuts' });
		expect(help).toHaveTextContent('Previous unit');
		expect(help).toHaveTextContent('Next unit');
		expect(help).toHaveTextContent('Esc');
		expect(help).not.toHaveTextContent('Tag the row'); // the list's keys are not the panel's

		await fireEvent.keyDown(dialog, { key: 'Escape' });
		expect(within(dialog).queryByRole('region', { name: 'Keyboard shortcuts' })).toBeNull();
		await fireEvent.keyDown(dialog, { key: '?' });
		expect(within(dialog).getByRole('region', { name: 'Keyboard shortcuts' })).toBeInTheDocument();
	});

	it('Esc closes the help alone: the panel stays open', async () => {
		const { panel, dialog } = await openPanel(unit());
		await fireEvent.keyDown(dialog, { key: '?' });

		await fireEvent.keyDown(dialog, { key: 'Escape' });

		expect(panel.isOpen).toBe(true);
	});

	it('shows the model rationale on demand', async () => {
		const { dialog } = await openPanel(
			unit({
				anchor_entry_id: 1,
				entries: [
					entry({
						id: 1,
						unit_key: 1,
						derivation: { category: { pass: 'llm', basis: { rationale: 'Looks like groceries' } } }
					})
				]
			})
		);

		expect(within(dialog).getByText('suggested by the model')).toBeInTheDocument();
		expect(screen.queryByText('Looks like groceries')).toBeNull();
		await fireEvent.click(within(dialog).getByRole('button', { name: 'Show rationale' }));
		expect(await screen.findByText('Looks like groceries')).toBeInTheDocument();
	});
});

describe('UnitPanel: other units', () => {
	it('shows a split as one block per entry under its one source', async () => {
		const src = source({ counterparty_name: 'Amazon' });
		const { dialog } = await openPanel(
			unit({
				anchor_entry_id: 1,
				entries: [
					entry({
						id: 1,
						unit_key: 1,
						source: src,
						source_transaction_id: 5,
						display_text: 'Amazon'
					}),
					entry({
						id: 2,
						unit_key: 1,
						source: src,
						source_transaction_id: 5,
						display_text: 'Amazon'
					})
				]
			})
		);

		expect(dialog).toHaveAccessibleName('Amazon (split in 2)');
		expect(within(dialog).getAllByRole('region', { name: /^Entry / })).toHaveLength(2);
		expect(within(dialog).getAllByRole('region', { name: 'Source transaction' })).toHaveLength(1);
	});

	it('shows both legs of a pair and each one’s partner', async () => {
		const { dialog } = await openPanel(
			unit({
				anchor_entry_id: 1,
				state: { confirmed: true, reasons: [] },
				entries: [
					entry({
						id: 1,
						unit_key: 1,
						type: 'transfer',
						account_id: 1,
						counter_account_id: 2,
						counterpart_entry_id: 2,
						amount: { amount: -5000, currency: 'EUR' },
						partner: {
							entry_id: 2,
							account_id: 2,
							booked_on: '2026-10-10',
							amount: { amount: 5000, currency: 'EUR' }
						}
					}),
					entry({
						id: 2,
						unit_key: 1,
						type: 'transfer',
						account_id: 2,
						counter_account_id: 1,
						counterpart_entry_id: 1,
						amount: { amount: 5000, currency: 'EUR' },
						partner: {
							entry_id: 1,
							account_id: 1,
							booked_on: '2026-10-09',
							amount: { amount: -5000, currency: 'EUR' }
						}
					})
				]
			})
		);

		expect(dialog).toHaveAccessibleName('Transfer Giro → Savings');
		expect(within(dialog).getByText('Confirmed')).toBeInTheDocument();
		expect(within(dialog).getAllByRole('region', { name: /^Entry / })).toHaveLength(2);
		expect(within(dialog).getAllByText('Partner leg')).toHaveLength(2);
	});

	it('says "Entered by hand" for an authored entry and shows no source columns', async () => {
		const { dialog } = await openPanel(
			unit({
				anchor_entry_id: 1,
				entries: [
					entry({ id: 1, unit_key: 1, authored: true, display_text: 'Flea market', derivation: {} })
				]
			})
		);

		expect(within(dialog).getByRole('region', { name: 'Entered by hand' })).toHaveTextContent(
			'Entered by hand'
		);
		expect(within(dialog).queryByText('Counterparty')).toBeNull();
	});
});

describe('UnitPanel: states', () => {
	it('shows a skeleton while loading', async () => {
		vi.mocked(getUnit).mockReturnValue(new Promise(() => {}));
		const panel = new UnitPanel(nav());
		render(UnitPanelView, { props: { panel, lookups } });
		panel.open(1);

		const dialog = await screen.findByRole('dialog');
		expect(dialog.querySelectorAll('[data-skeleton]').length).toBeGreaterThan(0);
		expect(dialog).toHaveTextContent('Loading the unit…');
	});

	it('offers Try again when the load failed', async () => {
		vi.mocked(getUnit).mockRejectedValueOnce(apiError(0, 'network_error'));
		const panel = new UnitPanel(nav());
		render(UnitPanelView, { props: { panel, lookups } });
		panel.open(1);
		await screen.findByRole('dialog');
		await screen.findByText('The unit could not be loaded');

		vi.mocked(getUnit).mockResolvedValueOnce(unit());
		await fireEvent.click(screen.getByRole('button', { name: 'Try again' }));

		await waitFor(() => expect(panel.status).toBe('ready'));
	});

	it('says "This entry has no review" for a 404, with Close, and mentions the balance record', async () => {
		vi.mocked(getUnit).mockRejectedValue(apiError(404, 'not_found'));
		const panel = new UnitPanel(nav());
		render(UnitPanelView, { props: { panel, lookups } });
		panel.open(1);
		const dialog = await screen.findByRole('dialog');

		const notice = await within(dialog).findByText(/Derived from a balance record/);
		expect(notice).toBeInTheDocument();
		expect(dialog).toHaveAccessibleName('This entry has no review');
		const close = within(dialog.querySelector('[data-slot="no-review"]') as HTMLElement).getByRole(
			'button',
			{ name: 'Close' }
		);
		await fireEvent.click(close);

		await waitFor(() => expect(panel.isOpen).toBe(false));
		await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
	});
});

describe('UnitPanel: keys', () => {
	it('] and [ step through the list the panel was opened from', async () => {
		const { panel, dialog } = await openPanel(unit({ anchor_entry_id: 4 }));
		const neighbour = vi.fn((id: number, dir: -1 | 1) => (id === 4 ? (dir === 1 ? 9 : 2) : null));
		const off = registerUnitSource({ neighbour, patch: () => {} });
		vi.mocked(getUnit).mockResolvedValue(unit({ anchor_entry_id: 9 }));

		await fireEvent.keyDown(dialog, { key: ']' });

		await waitFor(() => expect(panel.unitId).toBe(9));
		expect(getUnit).toHaveBeenLastCalledWith(9, expect.any(AbortSignal));

		vi.mocked(getUnit).mockResolvedValue(unit({ anchor_entry_id: 2 }));
		neighbour.mockImplementation((id, dir) => (id === 9 && dir === -1 ? 2 : null));
		await fireEvent.keyDown(dialog, { key: '[' });
		await waitFor(() => expect(panel.unitId).toBe(2));
		off();
	});

	it('leaves the keys to a field when focus is in one', async () => {
		const { panel, dialog } = await openPanel(unit({ anchor_entry_id: 4 }));
		const input = document.createElement('input');
		dialog.append(input);
		const step = vi.spyOn(panel, 'step');

		await fireEvent.keyDown(input, { key: ']' });

		expect(step).not.toHaveBeenCalled();
	});

	it('shows where the unit is in the list when the source knows', async () => {
		vi.mocked(getUnit).mockResolvedValue(unit({ anchor_entry_id: 4 }));
		const off = registerUnitSource({
			neighbour: () => null,
			patch: () => {},
			position: () => ({ index: 12, total: 214 })
		});
		const panel = new UnitPanel(nav());
		render(UnitPanelView, { props: { panel, lookups } });
		panel.open(4);

		const dialog = await screen.findByRole('dialog');
		expect(await within(dialog).findByText('12 of 214')).toBeInTheDocument();
		off();
	});

	it('announces stepping politely', async () => {
		const { dialog } = await openPanel(unit());
		expect(dialog.querySelector('[aria-live="polite"]')).not.toBeNull();
	});

	it('closes from the close button and removes the address parameter', async () => {
		const { panel, dialog } = await openPanel(unit());

		await fireEvent.click(within(dialog).getAllByRole('button', { name: 'Close' })[0]);

		await waitFor(() => expect(panel.isOpen).toBe(false));
	});
});
