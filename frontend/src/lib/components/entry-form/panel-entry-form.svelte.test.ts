// The layout-level pieces together: the work panel's `⋯` menu reaches the entry form's dialogs.
import { fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { entryForm } from '#lib/entry-form/controller.svelte.js';
import { authored, deleted, edited, signedIn } from '#lib/entry-form/fixtures.js';
import { lookupsStore } from '#lib/stores/lookups.svelte.js';
import { unitPanel } from '#lib/units/panel-instance.js';
import { registerUnitSource } from '#lib/units/sources.js';
import { preview, unit } from '#lib/units/fixtures.js';
import UnitPanelView from '#lib/components/units/unit-panel.svelte';
import EntryFormDialogs from './entry-form-dialogs.svelte';

// components never import the API, not even in tests: the mocks come from here
const api = vi.hoisted(() => ({
	getUnit: vi.fn(),
	listRules: vi.fn(),
	previewUnit: vi.fn(),
	commitUnit: vi.fn(),
	updateSource: vi.fn(),
	deleteSource: vi.fn()
}));
vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	...api
}));

const shown = unit({ anchor_entry_id: 5, entries: [authored()] });
let stop: () => void = () => {};

async function mount() {
	render(UnitPanelView, {
		props: {
			panel: unitPanel,
			lookups: lookupsStore.lookups,
			locale: 'en',
			onEditEntry: (id: number) => {
				const entry = unitPanel.unit?.entries.find((e) => e.id === id);
				if (entry) entryForm.openEdit(entry);
			},
			onDeleteEntry: (id: number) => {
				const entry = unitPanel.unit?.entries.find((e) => e.id === id);
				if (entry) entryForm.openDelete(entry);
			}
		}
	});
	render(EntryFormDialogs);
	unitPanel.open(5);
	const panel = await screen.findByRole('dialog', { name: 'groceries' });
	await waitFor(() => expect(unitPanel.flow.previewStatus).toBe('ready'));
	return panel;
}

async function openMenu(panel: HTMLElement) {
	await fireEvent.keyDown(
		within(panel).getByRole('button', { name: 'More actions for this unit' }),
		{
			key: 'Enter'
		}
	);
	return screen.findByRole('menu');
}

beforeEach(() => {
	vi.resetAllMocks();
	lookupsStore.reset();
	signedIn();
	api.listRules.mockResolvedValue([]);
	api.getUnit.mockResolvedValue(shown);
	api.previewUnit.mockImplementation(async () => preview(shown));
	api.updateSource.mockResolvedValue(edited());
	api.deleteSource.mockResolvedValue(deleted());
});

afterEach(() => {
	stop();
	stop = () => {};
	entryForm.close();
	unitPanel.flow.discard();
	unitPanel.close();
});

describe('the panel and the entry form together', () => {
	it('Edit entry opens the edit dialog with the entry values', async () => {
		const panel = await mount();
		const menu = await openMenu(panel);
		const item = within(menu).getByRole('menuitem', { name: /Edit entry/ });
		expect(item).not.toHaveAttribute('aria-disabled', 'true');

		await fireEvent.click(item);

		const dialog = await screen.findByRole('dialog', { name: 'Edit entry' });
		expect((within(dialog).getByLabelText('Amount') as HTMLInputElement).value).toBe('12.50');
		expect((within(dialog).getByLabelText('Date') as HTMLInputElement).value).toBe('2026-10-09');
	});

	it('is disabled while the draft is dirty, and says why', async () => {
		const panel = await mount();
		unitPanel.flow.setField(5, 'category', 11);
		const menu = await openMenu(panel);

		const item = within(menu).getByRole('menuitem', { name: /Edit entry/ });
		expect(item).toHaveAttribute('aria-disabled', 'true');
		expect(item).toHaveTextContent('Commit or discard your changes first');
	});

	it('Delete entry closes the panel when nothing is left to step to', async () => {
		const panel = await mount();
		const menu = await openMenu(panel);
		await fireEvent.click(within(menu).getByRole('menuitem', { name: /Delete entry/ }));
		const dialog = await screen.findByRole('dialog', { name: 'Delete entry' });
		const verb = within(dialog).getByRole('button', { name: 'Delete' });
		await waitFor(() => expect(verb).toBeEnabled());

		await fireEvent.click(verb);

		await waitFor(() => expect(unitPanel.isOpen).toBe(false));
		expect(api.deleteSource).toHaveBeenCalledTimes(2);
	});

	it('Delete entry steps the panel to the neighbour unit when the list has one', async () => {
		const next = unit({ anchor_entry_id: 6 });
		api.getUnit.mockImplementation(async (id: number) => (id === 6 ? next : shown));
		stop = registerUnitSource({
			neighbour: (id, dir) => (id === 5 && dir === 1 ? 6 : null),
			patch: () => {}
		});
		const panel = await mount();
		const menu = await openMenu(panel);
		await fireEvent.click(within(menu).getByRole('menuitem', { name: /Delete entry/ }));
		const dialog = await screen.findByRole('dialog', { name: 'Delete entry' });
		const verb = within(dialog).getByRole('button', { name: 'Delete' });
		await waitFor(() => expect(verb).toBeEnabled());

		await fireEvent.click(verb);

		await waitFor(() => expect(unitPanel.unitId).toBe(6));
		expect(unitPanel.isOpen).toBe(true);
	});
});
