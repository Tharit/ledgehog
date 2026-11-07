import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { account } from '#lib/ledger/fixtures.js';
import { buildLookups } from '#lib/ledger/lookups.js';
import { ruleNames } from '#lib/stores/rule-names.svelte.js';
import type { UnitDraftRequest } from '#lib/units/types.js';
import { committed, joinedScene } from '#lib/units/fixtures.js';
import { registerUnitSource } from '#lib/units/sources.js';
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
const { getUnit, listRules, previewUnit, commitUnit } = api;

const lookups = buildLookups({
	accounts: [account({ id: 1, name: 'Giro' }), account({ id: 2, name: 'Savings' })],
	categories: [],
	payees: [],
	tags: []
});

function nav(): PanelNav {
	const stack = ['/review'];
	let at = 0;
	return {
		url: () => new URL(stack[at], 'http://x.test'),
		push: (url) => {
			stack.push(url);
			at++;
		},
		replace: (url) => (stack[at] = url),
		back: () => at--
	};
}

async function openJoined(proposal = true) {
	const scene = joinedScene(proposal);
	vi.mocked(getUnit).mockResolvedValue(scene.loaded);
	vi.mocked(previewUnit).mockImplementation(async () => scene.joinedPreview());
	const panel = new UnitPanel(nav());
	render(UnitPanelView, { props: { panel, lookups, locale: 'en' } });
	panel.open(1);
	const dialog = await screen.findByRole('dialog', { name: /./ });
	await waitFor(() => expect(panel.flow.previewStatus).toBe('ready'));
	await waitFor(() => expect(dialog.querySelector('[data-entry-id="2"]')).not.toBeNull());
	return { panel, dialog };
}

const block = (dialog: HTMLElement, id: number) =>
	dialog.querySelector<HTMLElement>(`[data-entry-id="${id}"]`)!;
const requests = () => vi.mocked(previewUnit).mock.calls.map((c) => c[0] as UnitDraftRequest);
const lastRequest = () => requests().at(-1)!;

beforeEach(() => {
	vi.resetAllMocks();
	ruleNames.reset();
	vi.mocked(listRules).mockResolvedValue([]);
});
afterEach(() => cleanup());

describe('the partner’s side of a unit', () => {
	it('shows a joined leg’s partner as a pointer only: no other partner to choose', async () => {
		const { dialog } = await openJoined();
		const partner = block(dialog, 2).querySelector('[data-slot="partner"]')!;
		expect(partner).toHaveAttribute('data-joined');
		expect(partner).toHaveTextContent('Paired with the entry below');
		expect(partner).toHaveTextContent('proposed: exact match');
		expect(within(block(dialog, 2)).queryByRole('button', { name: /partner/i })).toBeNull();
		expect(block(dialog, 2).querySelector('[data-picker="partner"]')).toBeNull();
		// the side the panel was opened on keeps its picker
		expect(block(dialog, 1).querySelector('[data-picker="partner"]')).not.toBeNull();
	});

	it('shows its type and counter account as the pair’s, not to be edited', async () => {
		const { dialog } = await openJoined();
		const joined = within(block(dialog, 2));
		expect(block(dialog, 2).querySelector('[data-slot="pair-type"]')).toHaveTextContent('Transfer');
		expect(joined.queryByRole('button', { name: 'Flow' })).toBeNull();
		expect(joined.queryByRole('group', { name: 'Type' })).toBeNull();
		expect(block(dialog, 2).querySelector('[data-slot="pair-counter-account"]')).not.toBeNull();
		expect(joined.queryByRole('button', { name: 'Counter account' })).toBeNull();
		// the loaded leg keeps its controls
		expect(within(block(dialog, 1)).getByRole('group', { name: 'Type' })).toBeInTheDocument();
		// its other fields stay open
		expect(joined.getByLabelText('Note')).toBeInTheDocument();
	});

	it('keeps the partner of a user’s own pick pointer-only too', async () => {
		const { dialog, panel } = await openJoined();
		panel.flow.pickPartner(1, 2);
		await waitFor(() => expect(panel.flow.previewStatus).toBe('ready'));
		const partner = block(dialog, 2).querySelector('[data-slot="partner"]')!;
		expect(partner).toHaveAttribute('data-joined');
		expect(partner).toHaveTextContent('picked by you');
		expect(block(dialog, 2).querySelector('[data-picker="partner"]')).toBeNull();
	});
});

describe('editing the partner of a proposal', () => {
	it('pins the pair and keeps the proposal’s look: no "Reset to proposal"', async () => {
		const { dialog } = await openJoined();
		await fireEvent.input(within(block(dialog, 2)).getByLabelText('Note'), {
			target: { value: 'for the trip' }
		});
		await waitFor(() =>
			expect(lastRequest().entries).toEqual([
				{ id: 1, pairing: { mode: 'pick', partner_entry_id: 2 } },
				{ id: 2, note: 'for the trip' }
			])
		);
		await waitFor(() => expect(dialog.textContent).toContain('proposed: exact match'));
		const leg = block(dialog, 1).querySelector('[data-slot="partner"]')!;
		expect(
			within(leg as HTMLElement).queryByRole('button', { name: 'Reset to proposal' })
		).toBeNull();
		expect(leg).toHaveTextContent('proposed: exact match');
		expect(
			within(leg as HTMLElement).getByRole('button', { name: 'Choose partner…' })
		).toBeEnabled();
	});

	it('tells which changes were dropped when the leg is paired with another partner', async () => {
		const { dialog, panel } = await openJoined();
		await fireEvent.input(within(block(dialog, 2)).getByLabelText('Note'), {
			target: { value: 'x' }
		});
		await waitFor(() => expect(panel.flow.previewStatus).toBe('ready'));
		await fireEvent.click(block(dialog, 1).querySelector<HTMLElement>('[data-picker="partner"]')!);
		const list = await screen.findByRole('listbox', { name: 'Partner candidates' });
		await fireEvent.click(list.querySelector<HTMLElement>('[data-offer="4"]')!);
		await waitFor(() =>
			expect(dialog.textContent).toContain(
				'Your changes to The partner were dropped: it is no longer part of this unit.'
			)
		);
		expect(lastRequest().entries).toEqual([
			{ id: 1, pairing: { mode: 'pick', partner_entry_id: 4 } }
		]);
	});
});

describe('the keys on a partner’s block', () => {
	it('x turns nothing on the partner’s side into a flow', async () => {
		const { dialog } = await openJoined();
		const before = requests().length;
		await fireEvent.keyDown(block(dialog, 2), { key: 'x' });
		await new Promise((resolve) => setTimeout(resolve, 50));
		expect(requests().length).toBe(before);
		expect(block(dialog, 2).querySelector('[data-slot="pair-type"]')).toHaveTextContent('Transfer');
	});

	it('p on a partner’s block opens the partner list of the side the panel was opened on', async () => {
		const { dialog } = await openJoined();
		await fireEvent.keyDown(block(dialog, 2), { key: 'p' });
		expect(await screen.findByRole('listbox', { name: 'Partner candidates' })).toBeInTheDocument();
	});

	it('p on the loaded leg opens its own list', async () => {
		const { dialog } = await openJoined();
		await fireEvent.keyDown(block(dialog, 1), { key: 'p' });
		expect(await screen.findByRole('listbox', { name: 'Partner candidates' })).toBeInTheDocument();
	});
});

describe('after a commit', () => {
	it('moves on past the partner that settling pairs with the unit: it was part of what was committed', async () => {
		const { dialog, panel } = await openJoined();
		const neighbour = vi.fn((id: number, dir: -1 | 1) =>
			dir !== 1 ? null : id === 1 ? 2 : id === 2 ? 9 : null
		);
		const off = registerUnitSource({ neighbour, patch: () => {} });
		const { loaded } = joinedScene();
		vi.mocked(commitUnit).mockResolvedValue(committed(loaded));
		vi.mocked(getUnit).mockImplementation(async (id: number) => ({
			...loaded,
			anchor_entry_id: id
		}));

		await fireEvent.keyDown(dialog, { key: 'Enter', ctrlKey: true });

		await waitFor(() => expect(panel.unitId).toBe(9));
		off();
	});
});
