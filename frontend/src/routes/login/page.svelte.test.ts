import { render, screen, waitFor } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getConfig } from '#lib/api/index.js';
import Page from './+page.svelte';

const route = vi.hoisted(() => ({ page: { url: new URL('http://localhost/login') } }));
vi.mock('$app/state', () => ({ page: route.page }));
vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	getConfig: vi.fn()
}));

const config = (oidc_offered: boolean, oidc_enforced: boolean) =>
	({ oidc_offered, oidc_enforced }) as never;

beforeEach(() => {
	vi.resetAllMocks();
	route.page.url = new URL('http://localhost/login');
	vi.mocked(getConfig).mockResolvedValue(config(false, false));
});

describe('login page', () => {
	it('shows the decorative mascot above the login form', () => {
		const { container } = render(Page);

		const img = container.querySelector('img');
		expect(img).toHaveAttribute('src', '/brand/mascot.png');
		expect(img).toHaveAttribute('alt', '');
		expect(img).toHaveAttribute('width', '128');
		expect(img).toHaveAttribute('height', '135');

		const heading = screen.getByRole('heading', { name: 'Ledgehog' });
		expect(img!.compareDocumentPosition(heading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
	});

	it('offers only the password form when OIDC is not configured', async () => {
		render(Page);

		await waitFor(() => expect(getConfig).toHaveBeenCalled());
		expect(screen.queryByRole('link', { name: 'Log in with SSO' })).not.toBeInTheDocument();
		expect(screen.getByLabelText('Password')).toBeInTheDocument();
	});

	it('offers SSO beside the password form when OIDC is offered', async () => {
		vi.mocked(getConfig).mockResolvedValue(config(true, false));
		render(Page);

		expect(await screen.findByRole('link', { name: 'Log in with SSO' })).toHaveAttribute(
			'href',
			'/api/session/oidc'
		);
		expect(screen.getByLabelText('Password')).toBeInTheDocument();
	});

	it('offers only SSO when OIDC is enforced', async () => {
		vi.mocked(getConfig).mockResolvedValue(config(true, true));
		render(Page);

		await screen.findByRole('link', { name: 'Log in with SSO' });
		await waitFor(() => expect(screen.queryByLabelText('Password')).not.toBeInTheDocument());
	});

	it('keeps the password form when the configuration cannot be read', async () => {
		vi.mocked(getConfig).mockRejectedValue(new Error('down'));
		render(Page);

		await waitFor(() => expect(getConfig).toHaveBeenCalled());
		expect(screen.getByLabelText('Password')).toBeInTheDocument();
	});

	it.each([
		['oidc_not_allowed', 'Your account is not allowed to use Ledgehog.'],
		['oidc_disabled', 'This account is disabled.'],
		['oidc_unverified', 'The identity provider has not verified your e-mail address.'],
		['oidc_unavailable', 'The identity provider could not be reached.'],
		['oidc_failed', 'Signing in with SSO did not work. Please try again.'],
		['something_new', 'Something went wrong.']
	])('shows the reason a sign-in was refused: %s', (code, words) => {
		route.page.url = new URL(`http://localhost/login?error=${code}`);
		render(Page);

		expect(screen.getByRole('alert')).toHaveTextContent(words);
	});

	it('shows no alert without a refusal', () => {
		render(Page);

		expect(screen.queryByRole('alert')).not.toBeInTheDocument();
	});
});
