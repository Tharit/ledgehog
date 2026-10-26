import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, updateAccount } from '#lib/api/index.js';
import { account } from '#lib/ledger/fixtures.js';
import { EditAccountFlow } from './edit-flow.svelte.js';

vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	updateAccount: vi.fn(),
	listDocumentProviders: vi.fn().mockResolvedValue([])
}));

beforeEach(() => vi.resetAllMocks());

describe('EditAccountFlow external reference', () => {
	it('sends the trimmed reference, and null when it is cleared', async () => {
		vi.mocked(updateAccount).mockResolvedValue({
			account: account({ id: 3 }),
			settle: { error: null, touched_entry_ids: [] }
		});
		const flow = new EditAccountFlow();
		flow.start(account({ id: 3, external_ref: null }));
		flow.externalRef = '  DE02 1234 ';

		await flow.submit();
		expect(updateAccount).toHaveBeenLastCalledWith(3, { external_ref: 'DE02 1234' });

		flow.start(account({ id: 3, external_ref: 'de021234' }));
		flow.externalRef = '  ';
		await flow.submit();
		expect(updateAccount).toHaveBeenLastCalledWith(3, { external_ref: null });
	});

	it('says a duplicate reference under that field, routed by the reason', async () => {
		vi.mocked(updateAccount).mockRejectedValue(
			new ApiError(409, 'conflict', 'whatever', { reason: 'duplicate_external_ref' })
		);
		const flow = new EditAccountFlow();
		flow.start(account({ id: 3, external_ref: null }));
		flow.externalRef = 'DE02';

		expect(await flow.submit()).toBeNull();

		expect(flow.errors.externalRef).toBe('Another account already uses this bank reference.');
		expect(flow.failure).toBeNull();
	});
});

describe('EditAccountFlow providers', () => {
	const clearing = (providers: string[]) =>
		account({ id: 4, kind: 'clearance', providers, name: 'Amazon clearing' });

	it('sends the whole list when it changed, and nothing when only its order did', async () => {
		vi.mocked(updateAccount).mockResolvedValue({
			account: clearing(['amazon', 'paypal']),
			settle: { error: null, touched_entry_ids: [] }
		});
		const flow = new EditAccountFlow();
		flow.start(clearing(['amazon']));
		flow.providers = ['amazon', 'paypal'];

		await flow.submit();
		expect(updateAccount).toHaveBeenLastCalledWith(4, { providers: ['amazon', 'paypal'] });

		flow.start(clearing(['amazon', 'paypal']));
		flow.providers = ['paypal', 'amazon'];
		expect(flow.changes).toEqual({});
	});

	it('sends no providers for an account that is not a clearance account', () => {
		const flow = new EditAccountFlow();
		flow.start(account({ id: 3 }));
		flow.providers = ['amazon'];

		expect(flow.changes).toEqual({});
	});

	it('says a taken provider under the Providers field, naming the account', async () => {
		vi.mocked(updateAccount).mockRejectedValue(
			new ApiError(409, 'conflict', 'x', {
				reason: 'provider_taken',
				provider: 'paypal',
				account: { id: 9, name: 'PayPal clearing' }
			})
		);
		const flow = new EditAccountFlow();
		flow.start(clearing(['amazon']));
		flow.providers = ['amazon', 'paypal'];

		expect(await flow.submit()).toBeNull();

		expect(flow.errors.providers).toContain('PayPal clearing');
		expect(flow.failure).toBeNull();
	});
});
