import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '#lib/api/http.js';
import {
	deleteInstance,
	listImporters,
	listInstances,
	resetInstance,
	unlinkAccount,
	updateInstance
} from '#lib/api/importers.js';
import { catalogEntry, instance } from '#lib/importers/fixtures.js';
import { ImporterListStore } from './importer-list.svelte.js';

vi.mock('#lib/api/importers.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/importers.js')>()),
	listInstances: vi.fn(),
	listImporters: vi.fn(),
	updateInstance: vi.fn(),
	deleteInstance: vi.fn(),
	resetInstance: vi.fn(),
	unlinkAccount: vi.fn()
}));

const SETTLED = { settle: { touched_entry_ids: [], error: null } };

beforeEach(() => {
	vi.resetAllMocks();
	vi.mocked(listImporters).mockResolvedValue([catalogEntry()]);
	vi.mocked(listInstances).mockResolvedValue([
		instance({ id: 1, label: 'Giro', accounts: [{ account_id: 7, external_ref: 'acct-7' }] }),
		instance({ id: 2, label: 'Card' })
	]);
});

async function loaded() {
	const store = new ImporterListStore();
	await store.load();
	return store;
}

describe('ImporterListStore', () => {
	it('loads the instances and the catalog', async () => {
		const store = await loaded();

		expect(store.status).toBe('ready');
		expect(store.instances.map((i) => i.label)).toEqual(['Giro', 'Card']);
		expect(store.catalog.map((c) => c.name)).toEqual(['csv']);
	});

	it('stands the list when only the catalog could not be loaded', async () => {
		vi.mocked(listImporters).mockRejectedValue(new ApiError(500, 'internal', 'x'));
		const store = await loaded();

		expect(store.status).toBe('ready');
		expect(store.catalog).toEqual([]);
	});

	it('shows an error state, with the failure, when the instances could not be loaded', async () => {
		vi.mocked(listInstances).mockRejectedValue(new ApiError(0, 'network_error', 'x'));
		const store = await loaded();

		expect(store.status).toBe('error');
		expect(store.error).toEqual({ kind: 'network' });
	});

	it('disables and enables in place, and says nothing', async () => {
		vi.mocked(updateInstance).mockResolvedValue(instance({ id: 2, label: 'Card', disabled: true }));
		const store = await loaded();

		await store.setDisabled(store.instances[1], true);

		expect(vi.mocked(updateInstance)).toHaveBeenCalledWith(2, { disabled: true });
		expect(store.instances[1].disabled).toBe(true);
		expect(store.notice).toBeNull();
	});

	it('says a failed Disable as an error notice', async () => {
		vi.mocked(updateInstance).mockRejectedValue(new ApiError(0, 'network_error', 'x'));
		const store = await loaded();

		await store.setDisabled(store.instances[0], true);

		expect(store.notice?.error).toBe(true);
		expect(store.instances[0].disabled).toBe(false);
	});

	it('deletes after the decision and says the links went with it', async () => {
		vi.mocked(deleteInstance).mockResolvedValue(SETTLED);
		const store = await loaded();

		store.decision.start('delete', store.instances[1]);
		await store.decision.confirm();

		expect(vi.mocked(deleteInstance)).toHaveBeenCalledWith(2);
		expect(store.instances.map((i) => i.id)).toEqual([1]);
		expect(store.notice?.text).toBe('Importer “Card” was deleted, with its links.');
		expect(store.decision.open).toBe(false);
	});

	it('keeps the decision open with the pointer when the server refuses a delete (instance_has_runs)', async () => {
		vi.mocked(deleteInstance).mockRejectedValue(new ApiError(409, 'instance_has_runs', 'runs'));
		const store = await loaded();

		store.decision.start('delete', store.instances[0]);
		await store.decision.confirm();

		expect(store.decision.open).toBe(true);
		expect(store.decision.error).toBe('This importer has runs; disable it instead.');
		expect(store.instances).toHaveLength(2);
	});

	it('resets, keeping the settings, and replaces the row', async () => {
		vi.mocked(resetInstance).mockResolvedValue(instance({ id: 2, label: 'Card' }));
		const store = await loaded();

		store.decision.start('reset', store.instances[1]);
		await store.decision.confirm();

		expect(store.notice?.text).toMatch(/was reset/);
		expect(store.instances).toHaveLength(2);
	});

	it('unlinks an account and says its coverage stays', async () => {
		vi.mocked(unlinkAccount).mockResolvedValue(SETTLED);
		const store = await loaded();

		store.decision.start('unlink', store.instances[0], 7);
		await store.decision.confirm();

		expect(vi.mocked(unlinkAccount)).toHaveBeenCalledWith(1, 7);
		expect(store.instances[0].accounts).toEqual([]);
		expect(store.notice?.text).toMatch(/coverage and rows stay/);
	});

	it('drops a row whose instance was already gone', async () => {
		vi.mocked(deleteInstance).mockRejectedValue(new ApiError(404, 'not_found', 'gone'));
		const store = await loaded();

		store.decision.start('delete', store.instances[1]);
		await store.decision.confirm();

		expect(store.instances.map((i) => i.id)).toEqual([1]);
		expect(store.decision.open).toBe(false);
	});
});
