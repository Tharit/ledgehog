import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, getConfig, login, logout, me } from '#lib/api/index.js';
import { session } from './session.svelte.js';

vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	me: vi.fn(),
	login: vi.fn(),
	logout: vi.fn(),
	getConfig: vi.fn()
}));

const user = { id: 1, login: 'ada', display_name: 'Ada' };
const config = { base_currency: 'EUR', timezone: 'Europe/Berlin', locale: 'de' };

beforeEach(() => {
	vi.resetAllMocks();
	session.expire();
});

describe('session store', () => {
	it('starts authenticated with the user and the configuration', async () => {
		vi.mocked(me).mockResolvedValue(user);
		vi.mocked(getConfig).mockResolvedValue(config as never);

		await session.start();

		expect(session.status).toBe('authenticated');
		expect(session.user).toEqual(user);
		expect(session.config).toEqual(config);
	});

	it('starts anonymous when there is no session', async () => {
		vi.mocked(me).mockRejectedValue(new ApiError(401, 'unauthenticated', 'Not signed in.'));

		await session.start();

		expect(session.status).toBe('anonymous');
		expect(session.user).toBeNull();
	});

	it('starts in error when the server cannot be reached, and keeps the reason', async () => {
		vi.mocked(me).mockRejectedValue(
			new ApiError(0, 'network_error', 'The server could not be reached.')
		);

		await session.start();

		expect(session.status).toBe('error');
		expect(session.error?.code).toBe('network_error');
	});

	it('signs in, loading the configuration', async () => {
		vi.mocked(login).mockResolvedValue(user);
		vi.mocked(getConfig).mockResolvedValue(config as never);

		await session.signIn('ada', 'pw');

		expect(login).toHaveBeenCalledWith('ada', 'pw');
		expect(session.status).toBe('authenticated');
		expect(session.user?.display_name).toBe('Ada');
	});

	it('leaves the store anonymous and throws when the credentials are wrong', async () => {
		vi.mocked(login).mockRejectedValue(new ApiError(401, 'invalid_credentials', 'Wrong.'));

		await expect(session.signIn('ada', 'bad')).rejects.toMatchObject({
			code: 'invalid_credentials'
		});
		expect(session.status).toBe('anonymous');
	});

	it('signs out into anonymous', async () => {
		vi.mocked(me).mockResolvedValue(user);
		vi.mocked(getConfig).mockResolvedValue(config as never);
		vi.mocked(logout).mockResolvedValue(undefined);
		await session.start();

		await session.signOut();

		expect(session.status).toBe('anonymous');
		expect(session.user).toBeNull();
		expect(session.config).toBeNull();
	});
});
