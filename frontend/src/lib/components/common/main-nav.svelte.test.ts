import { render, screen, within } from '@testing-library/svelte';
import { createRawSnippet } from 'svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { session } from '#lib/stores/session.svelte.js';
import Layout from '../../../routes/+layout.svelte';

// components never import the API, not even in tests: the mocks come from here
const api = vi.hoisted(() => ({
	me: vi.fn(),
	getConfig: vi.fn(),
	readChanges: vi.fn(),
	getQueueCounts: vi.fn()
}));
vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	...api
}));
vi.mock('$app/navigation', () => ({
	afterNavigate: vi.fn(),
	beforeNavigate: vi.fn(),
	goto: vi.fn(),
	pushState: vi.fn(),
	replaceState: vi.fn()
}));
const route = vi.hoisted(() => ({ page: { url: new URL('http://localhost/') } }));
vi.mock('$app/state', () => ({ page: route.page }));

const children = createRawSnippet(() => ({ render: () => '<p>page content</p>' }));

beforeEach(() => {
	vi.resetAllMocks();
	session.status = 'loading';
	api.me.mockResolvedValue({ id: 1, login: 'ada', display_name: 'Ada' });
	api.getConfig.mockResolvedValue({
		base_currency: 'EUR',
		timezone: 'UTC',
		locale: 'en',
		max_rate_age_days: 7,
		matching_window_days: 7,
		document_window_back_days: 60,
		document_window_ahead_days: 7
	});
	api.readChanges.mockResolvedValue({
		ledger: 'b:1',
		documents: 'b:1',
		accounts: {},
		active_task: null,
		model_pending: 0,
		model_pending_lines: 0
	});
	api.getQueueCounts.mockResolvedValue({ count: 0, pending_review: 0, needs_account: 0 });
});

async function mainNav(path: string) {
	route.page.url = new URL(`http://localhost${path}`);
	render(Layout, { props: { data: {}, params: {}, children } });
	return within(await screen.findByRole('navigation', { name: 'Main' }));
}

describe('the main navigation: the model is looking', () => {
	const pending = (n: number, lines = 0) =>
		api.readChanges.mockResolvedValue({
			ledger: 'b:1',
			documents: 'b:1',
			accounts: {},
			active_task: null,
			model_pending: n,
			model_pending_lines: lines
		});

	it('shows the same mark on Documents for lines, and Review keeps counting entries only', async () => {
		pending(2, 5);
		const nav = await mainNav('/');

		const mark = await nav.findByRole('img', { name: 'The model is looking at 5 lines' });
		expect(nav.getByRole('link', { name: /Documents/ })).toContainElement(mark);
		const review = await nav.findByRole('img', { name: 'The model is looking at 2 entries' });
		expect(nav.getByRole('link', { name: /Review/ })).toContainElement(review);
	});

	it('says "1 line" for one', async () => {
		pending(0, 1);
		const nav = await mainNav('/');
		expect(
			await nav.findByRole('img', { name: 'The model is looking at 1 line' })
		).toBeInTheDocument();
	});

	it('shows an activity mark on Review with the count in its tooltip, even at a count of zero', async () => {
		pending(3);
		const nav = await mainNav('/');

		const mark = await nav.findByRole('img', { name: 'The model is looking at 3 entries' });
		expect(mark).toHaveAttribute('title', 'The model is looking at 3 entries');
		expect(nav.getByRole('link', { name: /Review/ })).toContainElement(mark);
		expect(
			nav.getByRole('link', { name: /Review/ }).querySelector('[data-slot="nav-count"]')
		).toBeNull();
		expect(mark).toHaveClass('motion-reduce:animate-none');
	});

	it('says "1 entry" for one', async () => {
		pending(1);
		const nav = await mainNav('/');

		expect(
			await nav.findByRole('img', { name: 'The model is looking at 1 entry' })
		).toBeInTheDocument();
	});

	it('shows no mark while the model has nothing pending', async () => {
		pending(0);
		const nav = await mainNav('/');
		await nav.findByRole('link', { name: /Review/ });

		expect(nav.queryByRole('img', { name: /The model is looking/ })).toBeNull();
	});
});

describe('the main navigation', () => {
	it('starts with the Overview, ahead of the Ledger', async () => {
		const nav = await mainNav('/');

		const links = nav.getAllByRole('link');
		expect(links.slice(0, 2).map((a) => [a.textContent?.trim(), a.getAttribute('href')])).toEqual([
			['Overview', '/'],
			['Ledger', '/ledger']
		]);
	});

	it('marks the Overview on the landing page only', async () => {
		const nav = await mainNav('/');

		expect(nav.getByRole('link', { name: 'Overview' })).toHaveAttribute('aria-current', 'page');
		expect(nav.getByRole('link', { name: 'Ledger' })).not.toHaveAttribute('aria-current');
	});

	it('does not mark the Overview on another page', async () => {
		const nav = await mainNav('/ledger');

		expect(nav.getByRole('link', { name: 'Overview' })).not.toHaveAttribute('aria-current');
		expect(nav.getByRole('link', { name: 'Ledger' })).toHaveAttribute('aria-current', 'page');
	});
});
