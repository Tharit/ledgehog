// The row detail and the mark-as-duplicate decision together, wired as the account page wires them:
// the detail is replaced by the decision, never comes back after a marking, returns after a Cancel,
// and can always be closed, however its read is going.
import { fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AccountDialogs } from '#lib/accounts/page-dialogs.svelte.js';
import { RowAddress } from '#lib/accounts/row-address.svelte.js';
import { RowDetail } from '#lib/accounts/row-detail.svelte.js';
import { provenance, sourceRow } from '#lib/accounts/fixtures.js';
import { entry, account } from '#lib/ledger/fixtures.js';
import { AccountPageStore } from '#lib/stores/account-page.svelte.js';
import { AccountRunsStore } from '#lib/stores/account-runs.svelte.js';
import Harness from './account-dialogs.harness.svelte';

const api = vi.hoisted(() => ({
	getProvenance: vi.fn(),
	getStatement: vi.fn(),
	getEntry: vi.fn(),
	markDuplicate: vi.fn(),
	listAccounts: vi.fn(),
	listRuns: vi.fn(),
	listInstances: vi.fn(),
	listImporters: vi.fn()
}));
vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	...api
}));

function preview(id: number) {
	return {
		dry_run: true,
		source_transaction_id: id,
		of: 0,
		removed_entry_ids: [10],
		partner_entry_ids: [],
		partners: [],
		freed_document_ids: [],
		repointed_source_ids: [],
		derived_changes: [],
		units: [],
		settle: null,
		versions: [{ entry_id: 10, version: 1 }]
	};
}

function setup() {
	const view = new AccountPageStore();
	view.accountId = 1;
	view.account = account({ id: 1 });
	view.status = 'ready';
	const runs = new AccountRunsStore();
	const detail = new RowDetail();
	const dialogs = new AccountDialogs();
	const address = new RowAddress();
	render(Harness, { props: { view, runs, detail, dialogs, address } });
	const open = () => {
		address.open(5);
		void detail.show(5);
	};
	return { view, detail, dialogs, address, open };
}

const detailDialog = () => screen.queryByRole('dialog', { name: 'Source transaction' });
const markDialog = () => screen.queryByRole('dialog', { name: 'Mark as duplicate of…' });

beforeEach(() => {
	history.replaceState(null, '', '/accounts/1');
	vi.resetAllMocks();
	api.getProvenance.mockImplementation(async (id: number) => provenance({ id, account_id: 1 }));
	api.getStatement.mockResolvedValue({
		items: [
			sourceRow({ id: 5, booked_on: '2026-10-10' }),
			sourceRow({ id: 3, booked_on: '2026-10-08' })
		],
		total: 2,
		limit: 500,
		offset: 0
	});
	api.getEntry.mockResolvedValue(entry({ id: 10 }));
	api.listAccounts.mockResolvedValue([account({ id: 1 })]);
	api.listRuns.mockResolvedValue([]);
	api.markDuplicate.mockImplementation(async (id: number, _of: number, o?: { dryRun?: boolean }) =>
		o?.dryRun ? preview(id) : { ...preview(id), dry_run: false }
	);
});
afterEach(() => history.replaceState(null, '', '/'));

async function toMarkDialog(s: ReturnType<typeof setup>) {
	s.open();
	const detail = await screen.findByRole('dialog', { name: 'Source transaction' });
	await fireEvent.click(
		await within(detail).findByRole('button', { name: 'Mark as duplicate of…' })
	);
	const mark = await screen.findByRole('dialog', { name: 'Mark as duplicate of…' });
	await fireEvent.click(await within(mark).findByRole('radio', { name: /Oct 8, 2026/ }));
	return mark;
}

describe('the row detail and the marking', () => {
	it('after a marking the detail does not come back, ?source= is cleared and a notice confirms', async () => {
		const s = setup();
		const mark = await toMarkDialog(s);
		await waitFor(() =>
			expect(within(mark).getByRole('button', { name: 'Mark as duplicate' })).toBeEnabled()
		);

		await fireEvent.click(within(mark).getByRole('button', { name: 'Mark as duplicate' }));

		await waitFor(() => expect(markDialog()).not.toBeInTheDocument());
		expect(detailDialog()).not.toBeInTheDocument();
		expect(s.address.id).toBeNull();
		expect(s.detail.id).toBeNull();
		expect(location.search).toBe('');
		await waitFor(() =>
			expect(s.view.notice?.text).toMatch(/^Marked as a duplicate of Oct 8, 2026 · −40\.00\./)
		);
		expect(detailDialog()).not.toBeInTheDocument();
	});

	it('Cancel in the decision returns to the row detail', async () => {
		const s = setup();
		const mark = await toMarkDialog(s);

		await fireEvent.click(within(mark).getByRole('button', { name: 'Cancel' }));

		await waitFor(() => expect(markDialog()).not.toBeInTheDocument());
		expect(await screen.findByRole('dialog', { name: 'Source transaction' })).toBeInTheDocument();
		expect(s.address.id).toBe(5);
	});

	it('the detail can be closed while its read has not answered', async () => {
		api.getProvenance.mockReturnValue(new Promise(() => {}));
		const s = setup();
		s.open();
		const dialog = await screen.findByRole('dialog', { name: 'Source transaction' });
		expect(within(dialog).getByText('Loading the row…')).toBeInTheDocument();

		await fireEvent.click(within(dialog).getAllByRole('button', { name: 'Close' })[0]);

		await waitFor(() => expect(detailDialog()).not.toBeInTheDocument());
		expect(s.address.id).toBeNull();
		expect(s.detail.status).toBe('idle');
	});

	it('the detail can be closed after its read failed', async () => {
		api.getProvenance.mockRejectedValue(new Error('x'));
		const s = setup();
		s.open();
		const dialog = await screen.findByRole('dialog', { name: 'Source transaction' });
		await within(dialog).findByText('The row could not be loaded.');

		await fireEvent.click(within(dialog).getAllByRole('button', { name: 'Close' })[0]);

		await waitFor(() => expect(detailDialog()).not.toBeInTheDocument());
	});
});
