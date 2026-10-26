import { cleanup, render, screen, waitFor, within } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { account, category, entry, payee } from '#lib/ledger/fixtures.js';
import { buildLookups } from '#lib/ledger/lookups.js';
import { source } from '#lib/rules/fixtures.js';
import { lookupsStore } from '#lib/stores/lookups.svelte.js';
import { ruleNames } from '#lib/stores/rule-names.svelte.js';
import {
	apiError,
	consequence,
	preview,
	previewRowOf,
	problem,
	transferOut,
	unit
} from '#lib/units/fixtures.js';
import { UnitPanel, type PanelNav } from '#lib/units/panel.svelte.js';
import UnitPanelView from './unit-panel.svelte';

// components never import the API, not even in tests: the mocks come from here
const api = vi.hoisted(() => ({
	getUnit: vi.fn(),
	listRules: vi.fn(),
	previewUnit: vi.fn(),
	commitUnit: vi.fn()
}));
vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	...api
}));
const { getUnit, listRules, previewUnit } = api;

const lookups = buildLookups({
	accounts: [
		account({ id: 1, name: 'Giro' }),
		account({ id: 3, name: 'Amazon clearing', kind: 'clearance', synced: false })
	],
	categories: [category({ id: 10, name: 'Groceries' })],
	payees: [payee({ id: 20, name: 'REWE' })],
	tags: []
});

function nav(): PanelNav {
	const stack = ['/review'];
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

const eur = (amount: number) => ({ amount, currency: 'EUR' });

// the entry a document booked on the clearance account (spec §5.8)
const documentBooking = (id: number, text: string, amount: number) =>
	entry({
		id,
		unit_key: 1,
		type: 'flow',
		account_id: 3,
		amount: eur(amount),
		category_id: 10,
		source_transaction_id: 40,
		source: source({
			amount: eur(-3000),
			counterparty_name: 'Amazon',
			booking: {
				kind: 'document',
				id: 31,
				provider: 'amazon',
				external_id: '304-1',
				account_id: null
			}
		}),
		origin: 'booking',
		source_text: text,
		review_flags: ['unconfirmed'],
		derivation: { type: { pass: 'booking', basis: {} } }
	});

async function open(shown: ReturnType<typeof unit>, answer = preview(shown)) {
	vi.mocked(getUnit).mockResolvedValue(shown);
	vi.mocked(previewUnit).mockResolvedValue(answer);
	const panel = new UnitPanel(nav());
	render(UnitPanelView, { props: { panel, lookups, locale: 'en' } });
	panel.open(shown.anchor_entry_id);
	const dialog = await screen.findByRole('dialog', { name: /./ });
	await waitFor(() => expect(panel.flow.previewStatus).toBe('ready'));
	return { panel, dialog };
}

beforeEach(() => {
	vi.resetAllMocks();
	ruleNames.reset();
	// the panel's flow asks the shared lookups for an account's kind
	lookupsStore.lookups = lookups;
	lookupsStore.loaded = true;
	vi.mocked(listRules).mockResolvedValue([]);
});
afterEach(() => cleanup());

describe('the panel on a document booking (spec §5.8)', () => {
	const booked = () =>
		unit({
			anchor_entry_id: 1,
			booking: { kind: 'document' },
			entries: [documentBooking(1, 'USB cable', -1500), documentBooking(2, 'Book', -1500)]
		});

	it('says where it came from and links the document', async () => {
		const { dialog } = await open(booked());

		const link = within(dialog).getByRole('link', { name: 'Booked from amazon order 304-1' });
		expect(link).toHaveAttribute('href', '/documents/31');
		expect(link).toHaveAttribute('target', '_blank');
	});

	it('offers no partner, no conversion and no split, and no amount to change', async () => {
		const { dialog } = await open(booked());

		expect(within(dialog).queryByRole('radio', { name: 'Transfer' })).toBeNull();
		expect(within(dialog).queryByRole('radio', { name: 'Flow' })).toBeNull();
		expect(within(dialog).queryByRole('button', { name: 'Split entry' })).toBeNull();
		expect(dialog.querySelector('[data-slot="partner"]')).toBeNull();
		expect(dialog.querySelector('[data-slot="amount-field"]')).toBeNull();
		expect(within(dialog).queryByRole('button', { name: 'Remove split' })).toBeNull();
		for (const text of within(dialog).getAllByText('Flow'))
			expect(text.closest('[role="radiogroup"]')).toBeNull();
	});

	it('keeps payee, category, description, note and tags editable, and says the type is from its document', async () => {
		const { dialog } = await open(booked());

		expect(within(dialog).getAllByRole('textbox', { name: 'Description' })).toHaveLength(2);
		expect(within(dialog).getAllByRole('textbox', { name: 'Note' })).toHaveLength(2);
		expect(within(dialog).getAllByRole('button', { name: /Category/ }).length).toBeGreaterThan(0);
		expect(within(dialog).getAllByRole('button', { name: /Payee/ }).length).toBeGreaterThan(0);
		expect(within(dialog).getAllByText('from its document')).toHaveLength(2);
	});

	it('says a draft that changes what is fixed is refused, in words', async () => {
		const shown = booked();
		vi.mocked(getUnit).mockResolvedValue(shown);
		vi.mocked(previewUnit).mockRejectedValue(
			apiError(422, 'invalid_draft', { code: 'booking_fixed', entry_id: 1, field: 'type' })
		);
		const panel = new UnitPanel(nav());
		render(UnitPanelView, { props: { panel, lookups, locale: 'en' } });
		panel.open(1);
		await screen.findByRole('dialog', { name: /./ });

		await waitFor(() => expect(panel.flow.previewStatus).toBe('error'));
		expect(
			screen.getByText(/A booking’s type, amount and split are its source’s/)
		).toBeInTheDocument();
	});
});

describe('the panel on a charge to a clearance account', () => {
	const charge = entry({
		id: 1,
		unit_key: 1,
		type: 'transfer',
		account_id: 1,
		counter_account_id: 3,
		amount: eur(-3000),
		source_transaction_id: 5,
		source: source({ amount: eur(-3000) }),
		derivation: { type: { pass: 'user' }, counter_account: { pass: 'user' } }
	});

	const withGhost = () => {
		const shown = unit({ anchor_entry_id: 1, entries: [charge] });
		const out = preview(shown);
		out.rows[0].transfer = transferOut({
			state: 'paired',
			partner: {
				entry_id: -9,
				account_id: 3,
				booked_on: '2026-10-10',
				amount: eur(3000),
				description: null
			}
		});
		out.rows[0].derivation = { counterpart: { pass: 'booking', basis: {} } };
		out.rows.push(
			previewRowOf(
				entry({
					id: -9,
					unit_key: 1,
					type: 'transfer',
					account_id: 3,
					counter_account_id: 1,
					amount: eur(3000),
					source_transaction_id: -9,
					derivation: {
						type: { pass: 'booking', basis: {} },
						counter_account: { pass: 'booking', basis: {} },
						counterpart: { pass: 'booking', basis: {} }
					}
				}),
				{
					original: true,
					in_unit: true,
					booking_for: 1,
					booking: { kind: 'transfer', id: 1 },
					transfer: transferOut({ state: 'paired' })
				}
			)
		);
		return { shown, out };
	};

	it('shows the booking settling will make as a dashed, read-only ghost on the clearance account', async () => {
		const { shown, out } = withGhost();
		const { dialog } = await open(shown, out);

		const ghost = dialog.querySelector('[data-ghost]') as HTMLElement;
		expect(ghost).not.toBeNull();
		expect(
			within(ghost).getByText('booked from this charge', { selector: '[data-slot="ghost-hint"]' })
		).toBeInTheDocument();
		expect(within(ghost).getByText('Amazon clearing')).toBeInTheDocument();
		const block = ghost.querySelector('[data-slot="counter-leg-block"]') as HTMLElement;
		expect(block).toHaveClass('border-dashed');
		expect(block.querySelector('[data-slot="counter-leg-provenance"]')).toHaveTextContent(
			'booked from this charge'
		);
		expect(within(ghost).queryByRole('textbox')).toBeNull();
	});

	it('says on the charge’s pair that the counter-leg is booked on the clearance account', async () => {
		const { shown, out } = withGhost();
		const { dialog } = await open(shown, out);

		expect(dialog.querySelector('[data-slot="partner"]')).toHaveTextContent(
			'counter-leg booked on Amazon clearing'
		);
	});

	it('words the problems of a clearance account', async () => {
		const { shown, out } = withGhost();
		out.problems = [
			problem('clearance_transfer', { entry_id: 1, field: 'type' }),
			problem('currency_rule', {
				entry_id: 1,
				field: 'counter_account',
				detail: { required: 'USD', actual: 'EUR' }
			})
		];
		const { dialog } = await open(shown, out);

		const list = within(dialog).getByRole('list', { name: 'Problems' });
		expect(list).toHaveTextContent(
			'An entry on a clearance account is a transfer only as a booking.'
		);
		expect(list).toHaveTextContent(
			'A clearance account takes only charges in its own currency (EUR)'
		);
	});

	it('lists a booking settling removes as a deleted consequence', async () => {
		const { shown, out } = withGhost();
		out.consequences = [
			consequence(
				'deleted',
				previewRowOf(documentBooking(7, 'Old order', -900), {
					in_unit: false,
					booking: { kind: 'document', id: 31 }
				})
			)
		];
		const { dialog } = await open(shown, out);

		const deleted = dialog.querySelector('[data-slot="consequences"][data-kind="deleted"]');
		expect(deleted).toHaveTextContent('Old order');
		expect(deleted).toHaveTextContent('Booked');
	});
});
