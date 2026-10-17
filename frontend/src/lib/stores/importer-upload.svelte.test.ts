import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '#lib/api/http.js';
import { getRun, listInstances, uploadFile } from '#lib/api/importers.js';
import { instance, report, run, upload } from '#lib/importers/fixtures.js';
import { account } from '#lib/ledger/fixtures.js';
import { ImporterUploadStore } from './importer-upload.svelte.js';
import { lookupsStore } from './lookups.svelte.js';

vi.mock('#lib/api/importers.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/importers.js')>()),
	listInstances: vi.fn(),
	uploadFile: vi.fn(),
	getRun: vi.fn()
}));

const FILE = new File(['a;b'], 'export.csv', { type: 'text/csv' });

function linked(over: Parameters<typeof instance>[0] = {}) {
	return instance({ id: 1, accounts: [{ account_id: 7, external_ref: 'acct-7' }], ...over });
}

async function ready(
	over: { instance?: Parameters<typeof instance>[0]; account?: Parameters<typeof account>[0] } = {}
) {
	lookupsStore.reset();
	lookupsStore.loaded = true;
	lookupsStore.setAccounts([account({ id: 7, name: 'Giro', ...over.account })]);
	vi.mocked(listInstances).mockResolvedValue([linked(over.instance)]);
	const store = new ImporterUploadStore({ accountId: 7, instanceId: 1 });
	await store.init();
	return store;
}

beforeEach(() => {
	vi.resetAllMocks();
});

describe('ImporterUploadStore', () => {
	it('starts the dry run as soon as a file is chosen', async () => {
		vi.mocked(uploadFile).mockResolvedValue(upload());
		const store = await ready();

		await store.choose(FILE);

		expect(vi.mocked(uploadFile)).toHaveBeenCalledWith(1, {
			file: FILE,
			accountId: 7,
			dryRun: true
		});
		expect(store.phase).toBe('report');
		expect(store.dry?.dry_run).toBe(true);
		expect(store.uploadBlocked).toBeNull();
	});

	it('keeps the file for "Check again", with the instance as saved now', async () => {
		vi.mocked(uploadFile).mockResolvedValue(upload());
		const store = await ready();
		await store.choose(FILE);
		vi.mocked(listInstances).mockResolvedValue([linked({ label: 'Giro (edited)' })]);

		await store.check();

		expect(vi.mocked(uploadFile)).toHaveBeenCalledTimes(2);
		expect(vi.mocked(uploadFile).mock.calls[1][1].file).toBe(FILE);
		expect(store.instance?.label).toBe('Giro (edited)');
	});

	it('disables the upload, with the failure as its reason, when the dry run found one', async () => {
		vi.mocked(uploadFile).mockResolvedValue(
			upload({
				summary: {},
				report: report({ failure: 'no header' }),
				failure: { kind: 'parse_failed', rule: null, message: 'header not found' }
			})
		);
		const store = await ready();

		await store.choose(FILE);

		expect(store.uploadBlocked).toMatch(/adjust the profile/);
		await store.commit();
		expect(vi.mocked(uploadFile)).toHaveBeenCalledTimes(1);
	});

	it('uploads for real with the same file and shows the run as stored', async () => {
		vi.mocked(uploadFile)
			.mockResolvedValueOnce(upload())
			.mockResolvedValueOnce(upload({ run_id: 42, dry_run: false }));
		vi.mocked(getRun).mockResolvedValue(run({ id: 42 }));
		const store = await ready();
		await store.choose(FILE);

		await store.commit();

		expect(vi.mocked(uploadFile).mock.calls[1][1]).toMatchObject({ file: FILE, dryRun: false });
		expect(store.phase).toBe('done');
		expect(store.run?.covered_from).toBe('2026-03-03');
	});

	it('says a quiet line when the settle after the upload failed', async () => {
		vi.mocked(uploadFile)
			.mockResolvedValueOnce(upload())
			.mockResolvedValueOnce(
				upload({ run_id: 42, dry_run: false, settle: { touched_entry_ids: [], error: 'boom' } })
			);
		vi.mocked(getRun).mockRejectedValue(new ApiError(500, 'internal', 'x'));
		const store = await ready();
		await store.choose(FILE);

		await store.commit();

		expect(store.phase).toBe('done');
		expect(store.notice).toMatch(/stale/);
		// the run could not be read back: the summary is the upload's own answer
		expect(store.run?.status).toBe('ok');
	});

	it('stands a refusal of the request above the buttons and keeps the report', async () => {
		vi.mocked(uploadFile)
			.mockResolvedValueOnce(upload())
			.mockRejectedValueOnce(new ApiError(409, 'account_closed', 'closed'));
		const store = await ready();
		await store.choose(FILE);

		await store.commit();

		expect(store.phase).toBe('report');
		expect(store.refusal).toMatch(/closed/);
		expect(store.dry).not.toBeNull();
	});

	it('says a file over the limit as such, and has no report', async () => {
		vi.mocked(uploadFile).mockRejectedValue(new ApiError(413, 'file_too_large', 'big'));
		const store = await ready();

		await store.choose(FILE);

		expect(store.refusal).toMatch(/10 MiB/);
		expect(store.dry).toBeNull();
		expect(store.phase).toBe('choose');
	});

	it('is blocked up front for a closed account, a disabled instance or a link that is gone', async () => {
		expect((await ready({ account: { closed_on: '2026-01-01' } })).blocked).toEqual({
			kind: 'account_closed'
		});
		expect((await ready({ instance: { disabled: true } })).blocked).toEqual({
			kind: 'instance_disabled'
		});
		expect((await ready({ instance: { accounts: [] } })).blocked).toEqual({
			kind: 'account_not_linked'
		});
		expect((await ready()).blocked).toBeNull();
	});
});
