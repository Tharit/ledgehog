import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
// the test stubs the API at its boundary (the one place a component test may name it)
// eslint-disable-next-line no-restricted-imports
import { ApiError } from '#lib/api/http.js';
// eslint-disable-next-line no-restricted-imports
import { getRun, listInstances, uploadFile } from '#lib/api/importers.js';
import { instance, report, run, upload } from '#lib/importers/fixtures.js';
import { account } from '#lib/ledger/fixtures.js';
import { lookupsStore } from '#lib/stores/lookups.svelte.js';
import UploadPage from './upload-page.svelte';

vi.mock('#lib/api/importers.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/importers.js')>()),
	listInstances: vi.fn(),
	uploadFile: vi.fn(),
	getRun: vi.fn()
}));

const FILE = new File(['a;b'], 'export.csv', { type: 'text/csv' });

beforeEach(() => {
	vi.resetAllMocks();
	lookupsStore.reset();
	lookupsStore.loaded = true;
	lookupsStore.setAccounts([account({ id: 7, name: 'Main giro', currency: 'EUR' })]);
	vi.mocked(listInstances).mockResolvedValue([
		instance({ id: 1, label: 'Giro', accounts: [{ account_id: 7, external_ref: 'acct-7' }] })
	]);
});

async function opened() {
	render(UploadPage, { props: { accountId: 7, instanceId: 1 } });
	await screen.findByText('Main giro · Giro');
}

async function choose() {
	await fireEvent.change(screen.getByLabelText('File'), { target: { files: [FILE] } });
}

describe('UploadPage', () => {
	it('names the account and the instance, and asks for the file', async () => {
		await opened();

		expect(screen.getByRole('heading', { name: 'Upload a file' })).toBeInTheDocument();
		expect(screen.getByText(/up to 10 MiB/)).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Upload' })).toBeDisabled();
	});

	it('checks the file at once, shows the report, and uploads with the same file', async () => {
		vi.mocked(uploadFile)
			.mockResolvedValueOnce(
				upload({
					report: report({
						rows_read: 4,
						emitted: 3,
						skipped: { count: 1, examples: [{ row: 9, reason: 'no booking date' }] }
					})
				})
			)
			.mockResolvedValueOnce(upload({ run_id: 42, dry_run: false }));
		vi.mocked(getRun).mockResolvedValue(run({ id: 42 }));
		await opened();

		await choose();

		expect(await screen.findByText('Rows read')).toBeInTheDocument();
		expect(screen.getByText('line 9: no booking date')).toBeInTheDocument();
		expect(vi.mocked(uploadFile).mock.calls[0][1]).toMatchObject({ dryRun: true, accountId: 7 });
		await fireEvent.click(screen.getByRole('button', { name: 'Upload' }));

		expect(await screen.findByText('The file was uploaded')).toBeInTheDocument();
		expect(vi.mocked(uploadFile).mock.calls[1][1]).toMatchObject({ dryRun: false, file: FILE });
		expect(screen.getByRole('link', { name: 'Back to the account' })).toHaveAttribute(
			'href',
			'/accounts/7'
		);
	});

	it('opens the profile in a new tab and checks again on the same file', async () => {
		vi.mocked(uploadFile).mockResolvedValue(upload());
		await opened();
		await choose();
		await screen.findByText('Rows read');

		const edit = screen.getByRole('link', { name: 'Edit profile' });
		expect(edit).toHaveAttribute('href', '/settings/importers/1');
		expect(edit).toHaveAttribute('target', '_blank');
		await fireEvent.click(screen.getByRole('button', { name: 'Check again' }));

		await waitFor(() => expect(vi.mocked(uploadFile)).toHaveBeenCalledTimes(2));
		expect(vi.mocked(uploadFile).mock.calls[1][1].file).toBe(FILE);
	});

	it('shows a failure the real run would end in in place of the counts, and cannot upload', async () => {
		vi.mocked(uploadFile).mockResolvedValue(
			upload({
				summary: {},
				report: report({ header_line: null, columns: [], failure: 'x' }),
				failure: { kind: 'contract_violation', rule: 'currency_mismatch', message: 'x' }
			})
		);
		await opened();

		await choose();

		expect(await screen.findByText(/Uploading this file would fail/)).toBeInTheDocument();
		expect(screen.getByText(/currency column and the row filters/)).toBeInTheDocument();
		expect(screen.queryByText('Rows read')).toBeNull();
		expect(screen.getByRole('button', { name: 'Upload' })).toBeDisabled();
	});

	it('stands a refusal of the request above the buttons', async () => {
		vi.mocked(uploadFile).mockRejectedValue(new ApiError(413, 'file_too_large', 'big'));
		await opened();

		await choose();

		expect(await screen.findByRole('alert')).toHaveTextContent(/larger than 10 MiB/);
	});

	it('says an account that is closed before any file is chosen', async () => {
		lookupsStore.setAccounts([account({ id: 7, name: 'Main giro', closed_on: '2026-01-01' })]);
		await opened();

		expect(screen.getByRole('alert')).toHaveTextContent(/closed/);
		expect(screen.getByLabelText('File')).toBeDisabled();
	});
});

describe('UploadPage for a camt importer', () => {
	const XML = new File(['<AccountMovementCamt/>'], 'export.xml', { type: 'text/xml' });

	async function openedCamt() {
		vi.mocked(listInstances).mockResolvedValue([
			instance({
				id: 1,
				importer: 'camt',
				label: 'Loan',
				accounts: [{ account_id: 7, external_ref: 'acct-7' }]
			})
		]);
		render(UploadPage, { props: { accountId: 7, instanceId: 1 } });
		await screen.findByText('Main giro · Loan');
	}

	it('offers neither Edit profile nor Check again, and reads the report without the CSV fields', async () => {
		vi.mocked(uploadFile).mockResolvedValue(
			upload({
				report: report({
					header_line: null,
					encoding: null,
					delimiter: null,
					columns: [],
					rows_read: 3,
					emitted: 1,
					filtered: { count: 1, examples: [{ row: 3, reason: 'pending entry: never imported' }] },
					sample: [
						{ row: 1, booked_on: '2026-03-28', amount_minor: -1000, cells: ['Acme', 'Rent'] }
					],
					format: 'OLB XML, camt.052'
				})
			})
		);
		await openedCamt();

		expect(screen.getByLabelText('File')).toHaveAttribute(
			'accept',
			'.xml,text/xml,application/xml'
		);
		await fireEvent.change(screen.getByLabelText('File'), { target: { files: [XML] } });

		expect(await screen.findByText('Rows read')).toBeInTheDocument();
		expect(screen.getByText('Pending, not imported')).toBeInTheDocument();
		expect(screen.getByText('entry 3: pending entry: never imported')).toBeInTheDocument();
		expect(screen.getByText('Acme | Rent')).toBeInTheDocument();
		expect(screen.getByText('Read as OLB XML, camt.052')).toBeInTheDocument();
		expect(screen.queryByLabelText('Warnings')).toBeNull();
		expect(screen.queryByText('Header row')).toBeNull();
		expect(screen.queryByRole('link', { name: 'Edit profile' })).toBeNull();
		expect(screen.queryByRole('button', { name: 'Check again' })).toBeNull();
	});
});
