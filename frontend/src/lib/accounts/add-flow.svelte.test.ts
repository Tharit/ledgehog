import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, createAccount, listDocumentProviders } from '#lib/api/index.js';
import { account } from '#lib/ledger/fixtures.js';
import { buildLookups } from '#lib/ledger/lookups.js';
import { lookupsStore } from '#lib/stores/lookups.svelte.js';
import { session } from '#lib/stores/session.svelte.js';
import { AddAccountFlow, knownCurrencies } from './add-flow.svelte.js';

vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	createAccount: vi.fn(),
	listDocumentProviders: vi.fn()
}));

const written = (over = {}) => ({
	account: account({ id: 8, name: 'Cash USD', currency: 'USD', kind: 'cash', sort_order: 5 }),
	settle: { error: null, touched_entry_ids: [] },
	...over
});

beforeEach(() => {
	vi.resetAllMocks();
	session.config = {
		base_currency: 'EUR',
		timezone: 'UTC',
		locale: 'en',
		max_rate_age_days: 7,
		matching_window_days: 7,
		oidc_offered: false,
		oidc_enforced: false
	};
	lookupsStore.lookups = buildLookups({
		accounts: [
			account({ id: 1, currency: 'EUR', sort_order: 0 }),
			account({ id: 2, name: 'Dollar', currency: 'USD', sort_order: 4 })
		]
	});
	lookupsStore.loaded = true;
});

describe('knownCurrencies', () => {
	it('lists the base currency first, then the accounts’, each once', () => {
		expect(
			knownCurrencies('EUR', [
				account({ currency: 'USD' }),
				account({ currency: 'CHF' }),
				account({ currency: 'EUR' }),
				account({ currency: 'USD' })
			])
		).toEqual(['EUR', 'CHF', 'USD']);
	});
});

describe('AddAccountFlow.start', () => {
	it('defaults to a cash account in the base currency, not locked', () => {
		const flow = new AddAccountFlow();

		flow.start();

		expect(flow).toMatchObject({ name: '', kind: 'cash', currency: 'EUR', locked: false });
		expect(flow.currencies).toEqual(['EUR', 'USD']);
		expect(flow.canSubmit).toBe(false);
	});

	it('locks a currency that is given and takes the kind given', () => {
		const flow = new AddAccountFlow();

		flow.start({ currency: 'GBP', kind: 'card' });

		expect(flow).toMatchObject({ kind: 'card', currency: 'GBP', locked: true });
	});

	it('forgets an earlier draft and its errors', async () => {
		const flow = new AddAccountFlow();
		flow.start();
		flow.name = 'x';
		vi.mocked(createAccount).mockRejectedValue(new ApiError(0, 'network_error', 'x'));
		await flow.submit();

		flow.start();

		expect(flow).toMatchObject({ name: '', failure: null, errors: {} });
	});
});

describe('AddAccountFlow.submit', () => {
	it('posts the trimmed name, kind and currency, after the accounts held', async () => {
		vi.mocked(createAccount).mockResolvedValue(written());
		const flow = new AddAccountFlow();
		flow.start({ currency: 'USD' });
		flow.name = '  Cash USD ';

		const added = await flow.submit();

		expect(createAccount).toHaveBeenCalledWith({
			name: 'Cash USD',
			kind: 'cash',
			currency: 'USD',
			providers: [],
			sort_order: 5
		});
		expect(added?.id).toBe(8);
		expect(flow.busy).toBe(false);
	});

	it('sends the trimmed external reference and omits a blank one', async () => {
		vi.mocked(createAccount).mockResolvedValue(written());
		const flow = new AddAccountFlow();
		flow.start({ currency: 'USD' });
		flow.name = 'Visa';
		flow.externalRef = '  DE02 1234 ';

		await flow.submit();
		expect(createAccount).toHaveBeenLastCalledWith(
			expect.objectContaining({ external_ref: 'DE02 1234' })
		);

		flow.externalRef = '  ';
		await flow.submit();
		expect(vi.mocked(createAccount).mock.lastCall![0]).not.toHaveProperty('external_ref');
	});

	it('says a duplicate external reference under that field', async () => {
		vi.mocked(createAccount).mockRejectedValue(
			new ApiError(409, 'conflict', 'x', { reason: 'duplicate_external_ref' })
		);
		const flow = new AddAccountFlow();
		flow.start();
		flow.name = 'a';
		flow.externalRef = 'DE02';

		expect(await flow.submit()).toBeNull();

		expect(flow.errors.externalRef).toBeTruthy();
		expect(flow.failure).toBeNull();
	});

	it('adds the account to the shared lookups', async () => {
		vi.mocked(createAccount).mockResolvedValue(written());
		const flow = new AddAccountFlow();
		flow.start({ currency: 'USD' });
		flow.name = 'Cash USD';

		await flow.submit();

		expect(lookupsStore.lookups.accounts.get(8)?.name).toBe('Cash USD');
		expect(lookupsStore.lookups.accounts.size).toBe(3);
	});

	it('does nothing without a name', async () => {
		const flow = new AddAccountFlow();
		flow.start();
		flow.name = '   ';

		expect(await flow.submit()).toBeNull();
		expect(createAccount).not.toHaveBeenCalled();
	});

	it('says a validation refusal under the name and adds nothing', async () => {
		vi.mocked(createAccount).mockRejectedValue(
			new ApiError(422, 'validation_error', 'x', [{ message: 'must not be blank' }])
		);
		const flow = new AddAccountFlow();
		flow.start();
		flow.name = 'a';

		expect(await flow.submit()).toBeNull();

		expect(flow.errors.name).toBeTruthy();
		expect(flow.failure).toBeNull();
		expect(lookupsStore.lookups.accounts.size).toBe(2);
	});

	it('says an unknown currency under the currency', async () => {
		vi.mocked(createAccount).mockRejectedValue(
			new ApiError(422, 'validation_error', 'x', { reason: 'unknown_currency' })
		);
		const flow = new AddAccountFlow();
		flow.start({ currency: 'ZZZ' });
		flow.name = 'a';

		await flow.submit();

		expect(flow.errors.currency).toBe('This currency is not known.');
	});

	it('says a refusal that belongs to no field in the dialog', async () => {
		vi.mocked(createAccount).mockRejectedValue(new ApiError(0, 'network_error', 'x'));
		const flow = new AddAccountFlow();
		flow.start();
		flow.name = 'a';

		await flow.submit();

		expect(flow.failure).toMatch(/could not be reached/);
		expect(flow.errors).toEqual({});
	});

	it('adds a clearance account with its providers and its start, and not before it has a start', async () => {
		vi.mocked(createAccount).mockResolvedValue(written());
		vi.mocked(listDocumentProviders).mockResolvedValue(['amazon', 'paypal']);
		const flow = new AddAccountFlow();
		flow.start();
		flow.name = 'Amazon clearing';
		flow.kind = 'clearance';
		flow.providers = ['amazon'];
		await vi.waitFor(() => expect(flow.suggestions).toEqual(['amazon', 'paypal']));

		expect(flow.canSubmit).toBe(false);
		expect(await flow.submit()).toBeNull();
		flow.startDate = '2026-09-30';
		expect(flow.canSubmit).toBe(true);
		await flow.submit();

		expect(createAccount).toHaveBeenCalledWith(
			expect.objectContaining({
				kind: 'clearance',
				providers: ['amazon'],
				start_date: '2026-09-30'
			})
		);
	});

	it('sends no providers and no start for any other kind', async () => {
		vi.mocked(createAccount).mockResolvedValue(written());
		const flow = new AddAccountFlow();
		flow.start();
		flow.name = 'Cash';
		flow.providers = ['amazon'];
		flow.startDate = '2026-09-30';

		await flow.submit();

		const body = vi.mocked(createAccount).mock.calls[0][0];
		expect(body.providers).toEqual([]);
		expect(body).not.toHaveProperty('start_date');
	});

	it('names the account that holds a provider under the Providers field', async () => {
		vi.mocked(createAccount).mockRejectedValue(
			new ApiError(409, 'conflict', 'x', {
				reason: 'provider_taken',
				provider: 'amazon',
				account: { id: 4, name: 'Amazon clearing' }
			})
		);
		const flow = new AddAccountFlow();
		flow.start();
		flow.name = 'Second';
		flow.kind = 'clearance';
		flow.startDate = '2026-09-30';
		flow.providers = ['amazon'];

		await flow.submit();

		expect(flow.errors.providers).toContain('Amazon clearing');
		expect(flow.failure).toBeNull();
	});
});
