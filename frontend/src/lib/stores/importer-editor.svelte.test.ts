import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '#lib/api/http.js';
import {
	createInstance,
	listImporters,
	listInstances,
	updateInstance
} from '#lib/api/importers.js';
import { catalogEntry, instance } from '#lib/importers/fixtures.js';
import { ImporterEditorStore } from './importer-editor.svelte.js';

vi.mock('#lib/api/importers.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/importers.js')>()),
	createInstance: vi.fn(),
	updateInstance: vi.fn(),
	listInstances: vi.fn(),
	listImporters: vi.fn()
}));

const PRESET = {
	header_marker: ['Buchung', 'Betrag'],
	booked_on: 'Buchung',
	date_format: 'dd.MM.yyyy',
	amount: { column: 'Betrag', credit: null, debit: null }
};

beforeEach(() => {
	vi.resetAllMocks();
	vi.mocked(listImporters).mockResolvedValue([catalogEntry({ presets: { giro: PRESET } })]);
	vi.mocked(listInstances).mockResolvedValue([]);
});

async function adding() {
	const store = new ImporterEditorStore({ importer: 'csv' });
	await store.init();
	return store;
}

describe('ImporterEditorStore, adding', () => {
	it('opens an empty draft for the importer named', async () => {
		const store = await adding();

		expect(store.loadStatus).toBe('ready');
		expect(store.editing).toBe(false);
		expect(store.presetNames).toEqual(['giro']);
		expect(store.dirty).toBe(false);
	});

	it('says missing for an importer the deployment does not register', async () => {
		const store = new ImporterEditorStore({ importer: 'nope' });
		await store.init();

		expect(store.loadStatus).toBe('missing');
	});

	it('fills the form from a preset as a draft edit, nothing saved', async () => {
		const store = await adding();

		store.choosePreset('giro');

		expect(store.draft.bookedOn).toBe('Buchung');
		expect(store.draft.headerMarker).toBe('Buchung\nBetrag');
		expect(store.dirty).toBe(true);
		expect(createInstance).not.toHaveBeenCalled();
	});

	it('saves the label and the settings built from the form', async () => {
		vi.mocked(createInstance).mockResolvedValue(instance({ id: 9, label: 'Giro' }));
		const store = await adding();
		store.choosePreset('giro');
		store.label = 'Giro';

		const result = await store.save();

		expect(result).toMatchObject({ created: true, instance: { id: 9 } });
		const [importer, fields] = vi.mocked(createInstance).mock.calls[0];
		expect(importer).toBe('csv');
		expect(fields.label).toBe('Giro');
		expect(fields.settings).toMatchObject({
			header_marker: ['Buchung', 'Betrag'],
			booked_on: 'Buchung',
			amount: { column: 'Betrag', credit: null, debit: null }
		});
		expect(store.dirty).toBe(false);
	});

	it('puts the server’s refusal of a setting under its field', async () => {
		vi.mocked(createInstance).mockRejectedValue(
			new ApiError(422, 'invalid_profile', 'amount: give one signed column', {
				setting: 'amount.column'
			})
		);
		const store = await adding();
		store.label = 'Giro';

		const result = await store.save();

		expect(result).toBeNull();
		expect(store.errorFor('amount')).toBe('Give one signed column');
		expect(store.failure).toBeNull();
		expect(store.dirty).toBe(true);
	});

	it('says a refusal that no field shows as one line, and a blank label under the label', async () => {
		vi.mocked(createInstance).mockRejectedValueOnce(
			new ApiError(422, 'invalid_profile', 'profile: must be an object', { setting: 'profile' })
		);
		const store = await adding();
		store.label = 'Giro';
		await store.save();
		expect(store.failure).toMatch(/profile/);

		vi.mocked(createInstance).mockRejectedValueOnce(
			new ApiError(422, 'invalid_instance', 'an importer instance needs a label')
		);
		await store.save();
		expect(store.errorFor('label')).toBe('An importer instance needs a label');
		expect(store.failure).toBeNull();
	});
});

describe('ImporterEditorStore, a non-CSV adapter', () => {
	const FINTS = { url: 'https://b.example/fints', bank_code: '12345678', user_id: 'me' };

	async function addingFints() {
		vi.mocked(listImporters).mockResolvedValue([catalogEntry({ name: 'fints', kind: 'fetch' })]);
		const store = new ImporterEditorStore({ importer: 'fints' });
		await store.init();
		return store;
	}

	it('opens the adapter’s empty draft and saves its settings', async () => {
		const store = await addingFints();
		expect(store.draft).toEqual({ url: '', bankCode: '', userId: '', customerId: '' });

		store.label = 'Bank';
		store.draft.url = FINTS.url;
		store.draft.bankCode = FINTS.bank_code;
		store.draft.userId = FINTS.user_id;
		vi.mocked(createInstance).mockResolvedValue(instance({ id: 5, importer: 'fints' }));
		const result = await store.save();

		expect(result).toMatchObject({ created: true });
		expect(createInstance).toHaveBeenCalledWith('fints', { label: 'Bank', settings: FINTS });
	});

	it('stops at the client checks without calling the server', async () => {
		const store = await addingFints();
		store.label = 'Bank';

		expect(await store.save()).toBeNull();

		expect(createInstance).not.toHaveBeenCalled();
		expect(store.errorFor('url')).not.toBeNull();
		expect(store.saving).toBe(false);
	});

	it('puts the server’s refusal under the field its setting names', async () => {
		const store = await addingFints();
		store.label = 'Bank';
		Object.assign(store.draft, { url: FINTS.url, bankCode: '12345678', userId: 'me' });
		vi.mocked(createInstance).mockRejectedValueOnce(
			new ApiError(422, 'invalid_profile', 'bank_code: unknown bank', { setting: 'bank_code' })
		);

		await store.save();

		expect(store.errorFor('bank_code')).toBe('Unknown bank');
		expect(store.failure).toBeNull();
	});

	it('reads stored settings into the draft when editing', async () => {
		vi.mocked(listInstances).mockResolvedValue([
			instance({ id: 6, importer: 'fints', label: 'Bank', settings: FINTS })
		]);
		const store = new ImporterEditorStore({ instanceId: 6 });
		await store.init();

		expect(store.draft).toEqual({
			url: FINTS.url,
			bankCode: '12345678',
			userId: 'me',
			customerId: ''
		});
	});
});

describe('ImporterEditorStore, editing', () => {
	it('opens the stored settings and saves them back with the label', async () => {
		vi.mocked(listInstances).mockResolvedValue([
			instance({ id: 4, label: 'Giro', settings: PRESET })
		]);
		vi.mocked(updateInstance).mockResolvedValue(instance({ id: 4, label: 'Giro 2' }));
		const store = new ImporterEditorStore({ instanceId: 4 });
		await store.init();
		expect(store.draft.bookedOn).toBe('Buchung');
		expect(store.dirty).toBe(false);

		store.label = 'Giro 2';
		expect(store.dirty).toBe(true);
		const result = await store.save();

		expect(result).toMatchObject({ created: false });
		expect(vi.mocked(updateInstance).mock.calls[0][0]).toBe(4);
		expect(vi.mocked(updateInstance).mock.calls[0][1]).toMatchObject({ label: 'Giro 2' });
	});

	it('says missing for an instance that is gone', async () => {
		const store = new ImporterEditorStore({ instanceId: 77 });
		await store.init();

		expect(store.loadStatus).toBe('missing');
	});
});
