import { fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { entryForm } from '#lib/entry-form/controller.svelte.js';
import { authored, deleted, signedIn } from '#lib/entry-form/fixtures.js';
import { lookupsStore } from '#lib/stores/lookups.svelte.js';
import { registerUnitSource } from '#lib/units/sources.js';
import { apiError } from '#lib/units/fixtures.js';
import DeleteEntryDialog from './delete-entry-dialog.svelte';

// components never import the API, not even in tests: the mocks come from here
const api = vi.hoisted(() => ({ deleteSource: vi.fn() }));
vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	...api
}));
const panel = vi.hoisted(() => ({
	open: vi.fn(),
	close: vi.fn(),
	retry: vi.fn(),
	reload: vi.fn(),
	isOpen: true,
	unit: null as null | { anchor_entry_id: number; entries: { id: number }[] },
	unitId: 5 as number | null
}));
vi.mock('#lib/units/panel-instance.js', () => ({ unitPanel: panel }));

const target = { entry: authored(), sourceMinor: -1250 };

async function open() {
	const onclose = vi.fn();
	render(DeleteEntryDialog, { props: { open: true, target, onclose } });
	const dialog = await screen.findByRole('dialog', { name: 'Delete entry' });
	return { dialog, onclose };
}

const verb = (dialog: HTMLElement) =>
	within(dialog).getByRole('button', { name: 'Delete' }) as HTMLButtonElement;

let stop: () => void = () => {};

beforeEach(() => {
	vi.resetAllMocks();
	panel.isOpen = true;
	panel.unitId = 5;
	panel.unit = { anchor_entry_id: 5, entries: [{ id: 5 }] };
	lookupsStore.reset();
	signedIn();
});

afterEach(() => stop());

describe('DeleteEntryDialog', () => {
	it('names what goes in plain words, from a dry run, before Delete is available', async () => {
		let answer: (value: ReturnType<typeof deleted>) => void = () => {};
		vi.mocked(api.deleteSource).mockReturnValue(new Promise((resolve) => (answer = resolve)));
		const { dialog } = await open();

		expect(verb(dialog)).toBeDisabled();
		expect(within(dialog).getByText('Checking what would change…')).toBeInTheDocument();
		answer(deleted());
		expect(
			await within(dialog).findByText(
				'Removes 1 entry (confirmed), 2 tags, and sends 1 partner back to review.'
			)
		).toBeInTheDocument();
		expect(verb(dialog)).toBeEnabled();
		expect(vi.mocked(api.deleteSource).mock.calls[0][0]).toBe(50);
		expect(vi.mocked(api.deleteSource).mock.calls[0][1]).toMatchObject({ dryRun: true });
	});

	it('is a decision: the verb is Delete and focus starts on Cancel', async () => {
		vi.mocked(api.deleteSource).mockResolvedValue(deleted());
		const { dialog } = await open();

		await waitFor(() =>
			expect(within(dialog).getByRole('button', { name: 'Cancel' })).toHaveFocus()
		);
		expect(verb(dialog)).toBeInTheDocument();
	});

	it('deletes with the versions of the dry run, patches the rows, steps the panel on and says so', async () => {
		vi.mocked(api.deleteSource)
			.mockResolvedValueOnce(deleted())
			.mockResolvedValueOnce(
				deleted({ dry_run: false, settle: { error: null, touched_entry_ids: [] } })
			);
		const patch = vi.fn();
		stop = registerUnitSource({ patch, neighbour: (id, dir) => (dir === 1 ? 6 : null) });
		const notify = vi.fn();
		const unlisten = entryForm.listen({ notify });
		const { dialog, onclose } = await open();
		await within(dialog).findByText(/^Removes/);

		await fireEvent.click(verb(dialog));

		await waitFor(() => expect(onclose).toHaveBeenCalledOnce());
		expect(vi.mocked(api.deleteSource).mock.calls[1][1]).toMatchObject({
			versions: { 5: 2, 8: 4 }
		});
		expect(vi.mocked(api.deleteSource).mock.calls[1][1]).not.toMatchObject({ dryRun: true });
		expect(patch).toHaveBeenCalledWith(
			expect.objectContaining({ removed_entry_ids: [5], entries: expect.any(Array) })
		);
		expect(panel.open).toHaveBeenCalledWith(6, null);
		expect(notify).toHaveBeenCalledWith(
			expect.stringMatching(/^Deleted entry .*12\.50.*groceries\.$/),
			false
		);
		unlisten();
	});

	it('closes the panel when there is no neighbour to step to', async () => {
		vi.mocked(api.deleteSource)
			.mockResolvedValueOnce(deleted())
			.mockResolvedValueOnce(deleted({ dry_run: false }));
		stop = registerUnitSource({ patch: vi.fn(), neighbour: () => null });
		const { dialog, onclose } = await open();
		await within(dialog).findByText(/^Removes/);

		await fireEvent.click(verb(dialog));

		await waitFor(() => expect(onclose).toHaveBeenCalled());
		expect(panel.close).toHaveBeenCalled();
		expect(panel.open).not.toHaveBeenCalled();
	});

	it('on a version conflict says so and counts again', async () => {
		vi.mocked(api.deleteSource)
			.mockResolvedValueOnce(deleted())
			.mockRejectedValueOnce(apiError(409, 'conflict'))
			.mockResolvedValueOnce(
				deleted({
					counts: { ...deleted().counts, tag_memberships: 0, partners_returning_to_review: 0 }
				})
			);
		const { dialog, onclose } = await open();
		await within(dialog).findByText(/^Removes/);

		await fireEvent.click(verb(dialog));

		expect(await within(dialog).findByText(/changed since you opened it/)).toBeInTheDocument();
		await waitFor(() =>
			expect(within(dialog).getByText('Removes 1 entry (confirmed).')).toBeInTheDocument()
		);
		expect(onclose).not.toHaveBeenCalled();
	});

	it('offers Try again when the count could not be had, and cannot delete meanwhile', async () => {
		vi.mocked(api.deleteSource).mockRejectedValueOnce(apiError(0, 'network_error'));
		const { dialog } = await open();

		expect(await within(dialog).findByText(/could not be reached/)).toBeInTheDocument();
		expect(verb(dialog)).toBeDisabled();
		vi.mocked(api.deleteSource).mockResolvedValueOnce(deleted());
		await fireEvent.click(within(dialog).getByRole('button', { name: 'Try again' }));
		await waitFor(() => expect(verb(dialog)).toBeEnabled());
	});
});
