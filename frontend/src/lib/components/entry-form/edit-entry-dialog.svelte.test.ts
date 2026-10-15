import { fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { EDIT_WARNING } from '#lib/entry-form/effects.js';
import { authored, edited, signedIn } from '#lib/entry-form/fixtures.js';
import { lookupsStore } from '#lib/stores/lookups.svelte.js';
import { apiError } from '#lib/units/fixtures.js';
import EditEntryDialog from './edit-entry-dialog.svelte';

// components never import the API, not even in tests: the mocks come from here
const api = vi.hoisted(() => ({ updateSource: vi.fn() }));
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
	unit: null,
	unitId: 5
}));
vi.mock('#lib/units/panel-instance.js', () => ({ unitPanel: panel }));

const target = { entry: authored(), sourceMinor: -1250 };

async function open() {
	const onclose = vi.fn();
	render(EditEntryDialog, { props: { open: true, target, onclose } });
	const dialog = await screen.findByRole('dialog', { name: 'Edit entry' });
	return { dialog, onclose };
}

const field = (dialog: HTMLElement, label: string) =>
	within(dialog).getByLabelText(label) as HTMLInputElement;
const save = (dialog: HTMLElement) =>
	within(dialog).getByRole('button', { name: 'Save' }) as HTMLButtonElement;

const call = (n: number) =>
	vi.mocked(api.updateSource).mock.calls[n] as unknown as [
		number,
		Record<string, unknown>,
		{ dryRun?: boolean; versions?: Record<number, number> }
	];

beforeEach(() => {
	vi.resetAllMocks();
	panel.isOpen = true;
	lookupsStore.reset();
	signedIn();
});

describe('EditEntryDialog', () => {
	it('is prefilled from the transaction, with the account fixed and the static warning above Save', async () => {
		const { dialog } = await open();

		expect(field(dialog, 'Date').value).toBe('2026-10-09');
		expect(field(dialog, 'Amount').value).toBe('\u221212.50');
		expect(within(dialog).queryByRole('radio')).toBeNull();
		expect(field(dialog, 'Purpose').value).toBe('groceries');
		expect(within(dialog).getByText('Cash')).toBeInTheDocument();
		expect(within(dialog).queryByRole('combobox')).toBeNull();
		const warning = within(dialog).getByText(EDIT_WARNING);
		const footer = save(dialog).closest('[data-slot="dialog-footer"]') as HTMLElement;
		expect(warning.compareDocumentPosition(footer) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
		expect(within(dialog).queryByRole('button', { name: 'Add' })).toBeNull();
	});

	it('flips an entry to money in with a typed plus, sending the signed amount only', async () => {
		vi.mocked(api.updateSource).mockResolvedValue(edited());
		const { dialog } = await open();

		await fireEvent.input(field(dialog, 'Amount'), { target: { value: '+12.50' } });

		await waitFor(() => expect(api.updateSource).toHaveBeenCalled());
		expect(call(0)[1]).toEqual({ amount: 1250 });
	});

	it('asks for a sign and sends nothing when it is missing', async () => {
		const { dialog } = await open();

		await fireEvent.input(field(dialog, 'Amount'), { target: { value: '12.50' } });

		expect(
			await within(dialog).findByText('Add a sign: \u2212 for money out, + for money in')
		).toBeInTheDocument();
		expect(api.updateSource).not.toHaveBeenCalled();
	});

	it('links the hint to the amount field', async () => {
		const { dialog } = await open();

		const amount = field(dialog, 'Amount');
		const hint = within(dialog).getByText('\u2212 money out, + money in');
		expect(amount.getAttribute('aria-describedby')).toContain(hint.id);
	});

	it('cannot be saved while nothing is changed, and asks nothing of the server', async () => {
		const { dialog } = await open();

		expect(save(dialog)).toBeDisabled();
		expect(api.updateSource).not.toHaveBeenCalled();
	});

	it('runs a dry run of just the change, and enables Save once it answered', async () => {
		vi.mocked(api.updateSource).mockResolvedValue(edited());
		const { dialog } = await open();

		await fireEvent.input(field(dialog, 'Amount'), { target: { value: '\u221220' } });

		expect(save(dialog)).toBeDisabled();
		await waitFor(() => expect(save(dialog)).toBeEnabled());
		expect(call(0)[0]).toBe(50);
		expect(call(0)[1]).toEqual({ amount: -2000 });
		expect(call(0)[2].dryRun).toBe(true);
	});

	it('lists what the dry run says the edit would do', async () => {
		vi.mocked(api.updateSource).mockResolvedValue(
			edited({
				collapsed_entry_ids: [6, 7],
				deleted_entry_ids: [6, 7],
				unpaired_entry_ids: [9],
				returned_to_review_ids: [5]
			})
		);
		const { dialog } = await open();

		await fireEvent.input(field(dialog, 'Amount'), { target: { value: '\u221220' } });

		expect(
			await within(dialog).findByText('2 split entries are collapsed into the original.')
		).toBeInTheDocument();
		expect(
			within(dialog).getByText('1 entry loses its counterpart; the transfer pair is broken.')
		).toBeInTheDocument();
		expect(within(dialog).getByText('1 entry returns to review.')).toBeInTheDocument();
	});

	it('sends a changed date and a cleared purpose, nothing else', async () => {
		vi.mocked(api.updateSource).mockResolvedValue(edited());
		const { dialog } = await open();

		await fireEvent.input(field(dialog, 'Date'), { target: { value: '2026-10-01' } });
		await fireEvent.input(field(dialog, 'Purpose'), { target: { value: '' } });

		await waitFor(() => expect(api.updateSource).toHaveBeenCalled());
		const last = vi.mocked(api.updateSource).mock.calls.length - 1;
		expect(call(last)[1]).toEqual({ booked_on: '2026-10-01', purpose: null });
	});

	it('saves with the versions of the dry run, then closes', async () => {
		vi.mocked(api.updateSource)
			.mockResolvedValueOnce(
				edited({
					versions: [
						{ entry_id: 5, version: 3 },
						{ entry_id: 9, version: 8 }
					]
				})
			)
			.mockResolvedValueOnce(edited({}, false));
		const { dialog, onclose } = await open();
		await fireEvent.input(field(dialog, 'Amount'), { target: { value: '\u221220' } });
		await waitFor(() => expect(save(dialog)).toBeEnabled());

		await fireEvent.click(save(dialog));

		await waitFor(() => expect(onclose).toHaveBeenCalledOnce());
		expect(call(1)[2].dryRun).toBeFalsy();
		expect(call(1)[2].versions).toEqual({ 5: 3, 9: 8 });
		expect(call(1)[1]).toEqual({ amount: -2000 });
		// the open unit is read again
		expect(panel.reload).toHaveBeenCalled();
	});

	it('on a version conflict says so, reads the unit again and checks the consequences again', async () => {
		vi.mocked(api.updateSource)
			.mockResolvedValueOnce(edited())
			.mockRejectedValueOnce(
				Object.assign(apiError(409, 'conflict'), { details: { entry_ids: [5] } })
			)
			.mockResolvedValueOnce(edited({ versions: [{ entry_id: 5, version: 4 }] }));
		const { dialog, onclose } = await open();
		await fireEvent.input(field(dialog, 'Amount'), { target: { value: '\u221220' } });
		await waitFor(() => expect(save(dialog)).toBeEnabled());

		await fireEvent.click(save(dialog));

		expect(await within(dialog).findByText(/changed since you opened it/)).toBeInTheDocument();
		await waitFor(() => expect(api.updateSource).toHaveBeenCalledTimes(3));
		expect(call(2)[2].dryRun).toBe(true);
		expect(panel.reload).toHaveBeenCalled();
		expect(onclose).not.toHaveBeenCalled();
		await waitFor(() => expect(save(dialog)).toBeEnabled());
		expect(field(dialog, 'Amount').value).toBe('\u221220');
	});

	it('says under the field what it cannot read, and does not ask the server', async () => {
		const { dialog } = await open();

		await fireEvent.input(field(dialog, 'Amount'), { target: { value: '\u2212abc' } });

		expect(await within(dialog).findByText('This is not an amount.')).toBeInTheDocument();
		expect(save(dialog)).toBeDisabled();
		expect(api.updateSource).not.toHaveBeenCalled();
	});

	it('says an entry that is gone, and cannot be saved', async () => {
		vi.mocked(api.updateSource).mockRejectedValue(apiError(404, 'not_found'));
		const { dialog } = await open();

		await fireEvent.input(field(dialog, 'Amount'), { target: { value: '\u221220' } });

		expect(await within(dialog).findByText('This entry no longer exists.')).toBeInTheDocument();
		expect(save(dialog)).toBeDisabled();
	});
});
