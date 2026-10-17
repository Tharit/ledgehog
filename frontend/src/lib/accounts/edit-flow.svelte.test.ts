import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, updateAccount } from '#lib/api/index.js';
import { account } from '#lib/ledger/fixtures.js';
import { EditAccountFlow } from './edit-flow.svelte.js';

vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	updateAccount: vi.fn()
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
