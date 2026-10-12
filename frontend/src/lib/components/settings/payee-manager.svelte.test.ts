import { fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
/* eslint-disable no-restricted-imports -- the test stubs the API at its boundary */
import {
	ApiError,
	createPayee,
	deletePayee,
	listPayees,
	mergePayee,
	updatePayee
} from '#lib/api/index.js';
/* eslint-enable no-restricted-imports */
import { payee } from '#lib/ledger/fixtures.js';
import { PayeesStore } from '#lib/payees/store.svelte.js';
import type { Payee, PayeeDeleteOut, PayeeMergeOut } from '#lib/types/domain.js';
import PayeeManager from './payee-manager.svelte';

vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	listPayees: vi.fn(),
	createPayee: vi.fn(),
	updatePayee: vi.fn(),
	deletePayee: vi.fn(),
	mergePayee: vi.fn()
}));

const rewe = payee({ id: 1, name: 'REWE', note: 'weekly shop', icon: null, color: null });
const edeka = payee({ id: 2, name: 'EDEKA', note: null, icon: 'store', color: 'sage' });
const shell = payee({ id: 3, name: 'Shell', note: null, icon: null, color: 'ochre' });

async function setup(payees: Payee[] = [rewe, edeka, shell]) {
	vi.mocked(listPayees).mockResolvedValue(payees);
	const store = new PayeesStore();
	render(PayeeManager, { props: { store } });
	await waitFor(() => expect(store.status).toBe('ready'));
	return store;
}

const written = (p: Payee) => ({ payee: p, settle: { error: null, touched_entry_ids: [] } });

beforeEach(() => {
	vi.resetAllMocks();
});

describe('PayeeManager: the list', () => {
	it('shows name and note, "default" for a payee without its own look, and no document provider', async () => {
		await setup([{ ...rewe, document_provider: 'amazon' }, edeka]);

		const row = document.querySelector('[data-payee-id="1"]') as HTMLElement;
		expect(within(row).getByText('REWE')).toBeInTheDocument();
		expect(within(row).getByText('weekly shop')).toBeInTheDocument();
		expect(within(row).getByText('default')).toBeInTheDocument();
		expect(screen.queryByText(/amazon/)).toBeNull();
		const own = document.querySelector('[data-payee-id="2"]') as HTMLElement;
		expect(own.querySelector('[data-slot="look-hint"]')).toBeNull();
	});

	it('says that a payee is only for a merchant you want to report on', async () => {
		await setup();

		expect(
			screen.getByText(/Create a payee only for a merchant you want to report on/)
		).toBeInTheDocument();
	});

	it('draws the initial where there is no icon', async () => {
		await setup();

		const row = document.querySelector('[data-payee-id="1"]') as HTMLElement;
		expect(within(row).getByText('R')).toBeInTheDocument();
	});
});

describe('PayeeManager: empty', () => {
	it('explains the next step and offers Add payee', async () => {
		await setup([]);

		expect(screen.getByText('No payees yet')).toBeInTheDocument();
		expect(screen.getByText(/rules can then set it/)).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Add payee' })).toBeEnabled();
	});
});

describe('PayeeManager: create and edit', () => {
	it('creates a payee with its note', async () => {
		vi.mocked(createPayee).mockResolvedValue(
			written(rewe) as Awaited<ReturnType<typeof createPayee>>
		);
		await setup([]);

		await fireEvent.click(screen.getByRole('button', { name: 'Add payee' }));
		await fireEvent.input(screen.getByLabelText('Name of the new payee'), {
			target: { value: 'REWE' }
		});
		await fireEvent.input(screen.getByLabelText('Note on the new payee'), {
			target: { value: 'groceries' }
		});
		await fireEvent.click(screen.getByRole('button', { name: 'Create' }));

		await waitFor(() =>
			expect(createPayee).toHaveBeenCalledWith({ name: 'REWE', note: 'groceries' })
		);
		expect(listPayees).toHaveBeenCalledTimes(2);
	});

	it('shows a taken name beside the field', async () => {
		vi.mocked(createPayee).mockRejectedValue(
			new ApiError(409, 'conflict', 'x', { reason: 'duplicate_name' })
		);
		await setup([]);

		await fireEvent.click(screen.getByRole('button', { name: 'Add payee' }));
		await fireEvent.input(screen.getByLabelText('Name of the new payee'), {
			target: { value: 'REWE' }
		});
		await fireEvent.click(screen.getByRole('button', { name: 'Create' }));

		expect(await screen.findByRole('alert')).toHaveTextContent(
			'A payee named "REWE" already exists.'
		);
	});

	it('edits name and note and sends both', async () => {
		vi.mocked(updatePayee).mockResolvedValue(
			written(rewe) as Awaited<ReturnType<typeof updatePayee>>
		);
		await setup();

		await fireEvent.click(screen.getByRole('button', { name: 'Edit REWE' }));
		await fireEvent.input(screen.getByLabelText('Name of REWE'), {
			target: { value: 'REWE Markt' }
		});
		await fireEvent.input(screen.getByLabelText('Note on REWE'), { target: { value: '' } });
		await fireEvent.click(screen.getByRole('button', { name: 'Save' }));

		await waitFor(() =>
			expect(updatePayee).toHaveBeenCalledWith(1, { name: 'REWE Markt', note: null })
		);
	});

	it('changes the colour from the fixed set', async () => {
		vi.mocked(updatePayee).mockResolvedValue(
			written(rewe) as Awaited<ReturnType<typeof updatePayee>>
		);
		await setup();

		await fireEvent.click(screen.getByRole('button', { name: 'Change icon and colour of REWE' }));
		const colour = await screen.findByRole('group', { name: 'Colour' });
		await fireEvent.click(within(colour).getByRole('button', { name: 'plum' }));

		await waitFor(() => expect(updatePayee).toHaveBeenCalledWith(1, { color: 'plum' }));
	});
});

const deleteOut = (over: Partial<PayeeDeleteOut> = {}): PayeeDeleteOut => ({
	dry_run: true,
	deletable: true,
	deleted: false,
	deleted_rule_ids: [],
	held: { entries: 0 },
	payee: shell as PayeeDeleteOut['payee'] & Payee,
	rules: [],
	settle: null,
	...over
});

describe('PayeeManager: delete', () => {
	it('lists the rules the delete would take with it, then deletes on explicit confirm', async () => {
		vi.mocked(deletePayee).mockImplementation(async (_id, options) =>
			options?.dryRun
				? deleteOut({
						rules: [
							{ id: 9, name: 'Shell fuel', sets: 'payee', role: 'sets' },
							{ id: 10, name: 'Fuel', sets: 'category', role: 'condition' }
						]
					})
				: deleteOut({ dry_run: false, deleted: true, deleted_rule_ids: [9, 10] })
		);
		await setup();

		await fireEvent.click(screen.getByRole('button', { name: 'Delete Shell' }));

		const dialog = await screen.findByRole('dialog');
		expect(await within(dialog).findByText('Shell fuel (sets this payee)')).toBeInTheDocument();
		expect(within(dialog).getByText('Fuel (names this payee as a condition)')).toBeInTheDocument();
		await fireEvent.click(within(dialog).getByRole('button', { name: 'Delete' }));

		await waitFor(() => expect(deletePayee).toHaveBeenCalledWith(3));
		expect(await screen.findByText('Deleted Shell and 2 rules.')).toBeInTheDocument();
	});

	it('refuses with the entries held and offers Merge instead', async () => {
		vi.mocked(deletePayee).mockResolvedValue(
			deleteOut({ deletable: false, held: { entries: 12 } })
		);
		await setup();

		await fireEvent.click(screen.getByRole('button', { name: 'Delete Shell' }));

		const dialog = await screen.findByRole('dialog');
		expect(await within(dialog).findByText(/referenced by 12 entries/)).toBeInTheDocument();
		expect(within(dialog).queryByRole('button', { name: 'Delete' })).toBeNull();
		expect(within(dialog).getByRole('button', { name: 'Merge instead…' })).toBeInTheDocument();
	});
});

const mergeOut = (over: Partial<PayeeMergeOut> = {}): PayeeMergeOut => ({
	dry_run: true,
	source_id: 1,
	target: edeka as PayeeMergeOut['target'] & Payee,
	entry_count: 7,
	entry_ids: [],
	setting_rule_ids: [4],
	condition_rule_ids: [5, 6],
	document_provider_lost: false,
	source_document_provider: null,
	settle: null,
	...over
});

async function openMergeInto(name: RegExp) {
	await fireEvent.click(screen.getByRole('button', { name: 'Merge REWE into another payee' }));
	const dialog = await screen.findByRole('dialog');
	await fireEvent.click(within(dialog).getByRole('option', { name }));
	return dialog;
}

describe('PayeeManager: merge', () => {
	it('lists the entries and rules repointed and says the target keeps its attributes', async () => {
		vi.mocked(mergePayee).mockResolvedValue(mergeOut());
		await setup();

		const dialog = await openMergeInto(/EDEKA/);

		expect(await within(dialog).findByText('Repoints 7 entries')).toBeInTheDocument();
		expect(within(dialog).getByText('1 rule setting it repointed')).toBeInTheDocument();
		expect(
			within(dialog).getByText('2 rules naming it as a condition repointed')
		).toBeInTheDocument();
		expect(
			within(dialog).getByText('EDEKA keeps its own name, note, icon and colour.')
		).toBeInTheDocument();
		expect(mergePayee).toHaveBeenCalledWith(1, 2, { dryRun: true });
		expect(within(dialog).queryByRole('option', { name: /REWE/ })).toBeNull();
	});

	it('warns when the source document provider would be lost', async () => {
		vi.mocked(mergePayee).mockResolvedValue(
			mergeOut({ document_provider_lost: true, source_document_provider: 'amazon' })
		);
		await setup();

		const dialog = await openMergeInto(/EDEKA/);

		expect(await within(dialog).findByText(/"amazon"/)).toBeInTheDocument();
	});

	it('merges with the previewed count and says what happened', async () => {
		vi.mocked(mergePayee).mockImplementation(async (_id, _into, options) =>
			options?.dryRun ? mergeOut() : mergeOut({ dry_run: false })
		);
		await setup();
		const dialog = await openMergeInto(/EDEKA/);
		await within(dialog).findByText('Repoints 7 entries');

		await fireEvent.click(within(dialog).getByRole('button', { name: 'Merge' }));

		await waitFor(() => expect(mergePayee).toHaveBeenCalledWith(1, 2, { expectedCount: 7 }));
		expect(
			await screen.findByText('Merged REWE into EDEKA (7 entries, 3 rules).')
		).toBeInTheDocument();
	});

	it('re-runs the preview and says so when the count moved', async () => {
		let previews = 0;
		vi.mocked(mergePayee).mockImplementation(async (_id, _into, options) => {
			if (options?.dryRun) return mergeOut({ entry_count: previews++ === 0 ? 7 : 9 });
			throw new ApiError(409, 'conflict', 'x', {
				reason: 'filter_result_changed',
				expected: 7,
				actual: 9
			});
		});
		await setup();
		const dialog = await openMergeInto(/EDEKA/);
		await within(dialog).findByText('Repoints 7 entries');

		await fireEvent.click(within(dialog).getByRole('button', { name: 'Merge' }));

		expect(
			await within(dialog).findByText(/it now repoints 9 entries \(was 7\)/)
		).toBeInTheDocument();
		expect(within(dialog).getByText('Repoints 9 entries')).toBeInTheDocument();
	});
});
