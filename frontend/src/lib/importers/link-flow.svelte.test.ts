import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '#lib/api/http.js';
import { linkAccount } from '#lib/api/importers.js';
import { instance, link } from './fixtures.js';
import { LinkAccountFlow } from './link-flow.svelte.js';

vi.mock('#lib/api/importers.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/importers.js')>()),
	linkAccount: vi.fn()
}));

function setup() {
	const host = { linked: vi.fn(), gone: vi.fn() };
	const flow = new LinkAccountFlow(host);
	flow.start(instance({ id: 3, label: 'Giro' }));
	return { flow, host };
}

beforeEach(() => vi.resetAllMocks());

describe('LinkAccountFlow', () => {
	it('asks for the link’s dry run once an account is chosen, and links with the verb', async () => {
		vi.mocked(linkAccount)
			.mockResolvedValueOnce(link({ user_authored_count: 14 }))
			.mockResolvedValueOnce(link({ dry_run: false, external_ref: 'acct-7' }));
		const { flow, host } = setup();
		expect(flow.canLink).toBe(false);

		await flow.choose(7);

		expect(vi.mocked(linkAccount)).toHaveBeenCalledWith(3, 7, { dryRun: true });
		expect(flow.preview?.user_authored_count).toBe(14);
		expect(flow.canLink).toBe(true);

		await flow.confirm();

		expect(vi.mocked(linkAccount).mock.calls[1]).toEqual([3, 7, {}]);
		expect(host.linked).toHaveBeenCalledOnce();
		const [now, accountId] = host.linked.mock.calls[0];
		expect(accountId).toBe(7);
		expect(now.accounts).toEqual([{ account_id: 7, external_ref: 'acct-7' }]);
		expect(flow.open).toBe(false);
	});

	it('drops a late answer for an account no longer chosen', async () => {
		let release: (value: ReturnType<typeof link>) => void = () => {};
		vi.mocked(linkAccount)
			.mockReturnValueOnce(new Promise((resolve) => (release = resolve)))
			.mockResolvedValueOnce(link({ account_id: 8 }));
		const { flow } = setup();

		const first = flow.choose(7);
		await flow.choose(8);
		release(link({ account_id: 7, user_authored_count: 99 }));
		await first;

		expect(flow.preview?.account_id).toBe(8);
	});

	it('says the server’s refusal in the dialog and links nothing', async () => {
		vi.mocked(linkAccount)
			.mockResolvedValueOnce(link())
			.mockRejectedValueOnce(new ApiError(409, 'already_linked', 'x'));
		const { flow, host } = setup();
		await flow.choose(7);

		await flow.confirm();

		expect(flow.error).toBe('This account is already linked to this importer.');
		expect(flow.open).toBe(true);
		expect(host.linked).not.toHaveBeenCalled();
	});

	it('with the account fixed by discovery: shows the dry run at once and sends the discovered reference with both calls', async () => {
		vi.mocked(linkAccount)
			.mockResolvedValueOnce(link({ account_id: 7, user_authored_count: 3 }))
			.mockResolvedValueOnce(link({ dry_run: false, external_ref: 'DE01' }));
		const host = { linked: vi.fn(), gone: vi.fn() };
		const flow = new LinkAccountFlow(host);

		flow.start(instance({ id: 3, label: 'Testbank' }), {
			accountId: 7,
			name: 'Giro',
			externalRef: 'DE01'
		});
		await vi.waitFor(() => expect(flow.canLink).toBe(true));

		expect(flow.accountId).toBe(7);
		expect(vi.mocked(linkAccount).mock.calls[0]).toEqual([
			3,
			7,
			{ dryRun: true, externalRef: 'DE01' }
		]);
		expect(flow.preview?.user_authored_count).toBe(3);

		await flow.confirm();

		expect(vi.mocked(linkAccount).mock.calls[1]).toEqual([3, 7, { externalRef: 'DE01' }]);
		expect(host.linked).toHaveBeenCalledOnce();
		expect(host.linked.mock.calls[0][0].accounts).toEqual([
			{ account_id: 7, external_ref: 'DE01' }
		]);
	});

	it('says why the preview failed, without a verb to press', async () => {
		vi.mocked(linkAccount).mockRejectedValue(new ApiError(409, 'account_closed', 'x'));
		const { flow } = setup();

		await flow.choose(7);

		expect(flow.error).toMatch(/closed/);
		expect(flow.canLink).toBe(false);
	});
});
