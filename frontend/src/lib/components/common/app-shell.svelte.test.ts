import { fireEvent, render, screen } from '@testing-library/svelte';
import ListIcon from '@lucide/svelte/icons/list';
import SettingsIcon from '@lucide/svelte/icons/settings';
import { createRawSnippet } from 'svelte';
import { describe, expect, it, vi } from 'vitest';
import AppShell from './app-shell.svelte';

const content = createRawSnippet(() => ({ render: () => '<p>page content</p>' }));
const items = [{ href: '/ledger', label: 'Ledger', icon: ListIcon }];

function shell(currentPath: string, onlogout = vi.fn()) {
	render(AppShell, { props: { items, currentPath, userName: 'Ada', onlogout, children: content } });
	return onlogout;
}

describe('AppShell', () => {
	it('shows the wordmark, the page and the user', () => {
		shell('/ledger');

		expect(screen.getByText('Ledgehog')).toBeInTheDocument();
		expect(screen.getByText('page content')).toBeInTheDocument();
		expect(screen.getByText('Ada')).toBeInTheDocument();
	});

	it('shows the decorative app icon beside the wordmark', () => {
		const { container } = render(AppShell, {
			props: {
				items,
				currentPath: '/ledger',
				userName: 'Ada',
				onlogout: vi.fn(),
				children: content
			}
		});

		const icon = container.querySelector('aside img');
		expect(icon).toHaveAttribute('src', '/brand/app-icon-dark.png');
		expect(icon).toHaveAttribute('alt', '');
		expect(icon).toHaveAttribute('width', '28');
		expect(screen.queryByRole('img')).toBeNull();
	});

	it('lists only the navigation items it is given', () => {
		shell('/ledger');

		const nav = screen.getByRole('navigation', { name: 'Main' });
		expect(nav.querySelectorAll('a')).toHaveLength(1);
		expect(screen.getByRole('link', { name: 'Ledger' })).toHaveAttribute('href', '/ledger');
	});

	it('marks the current route, also below it', () => {
		shell('/ledger/42');

		expect(screen.getByRole('link', { name: 'Ledger' })).toHaveAttribute('aria-current', 'page');
	});

	it('marks no item on another route', () => {
		shell('/settings');

		expect(screen.getByRole('link', { name: 'Ledger' })).not.toHaveAttribute('aria-current');
	});

	it('calls onlogout from the log out button', async () => {
		const onlogout = shell('/ledger');

		await fireEvent.click(screen.getByRole('button', { name: 'Log out' }));

		expect(onlogout).toHaveBeenCalledOnce();
	});
});

describe('AppShell: footer navigation', () => {
	const footerItems = [
		{ href: '/settings', label: 'Settings', icon: SettingsIcon, match: '/settings' }
	];

	function withFooter(currentPath: string) {
		render(AppShell, {
			props: {
				items,
				footerItems,
				currentPath,
				userName: 'Ada',
				onlogout: vi.fn(),
				children: content
			}
		});
	}

	it('keeps Settings out of the main navigation, below it', () => {
		withFooter('/ledger');

		const main = screen.getByRole('navigation', { name: 'Main' });
		expect(main.querySelectorAll('a')).toHaveLength(1);
		const secondary = screen.getByRole('navigation', { name: 'Secondary' });
		expect(secondary).toContainElement(screen.getByRole('link', { name: 'Settings' }));
		expect(screen.getByRole('link', { name: 'Settings' })).toHaveAttribute('href', '/settings');
		expect(main.compareDocumentPosition(secondary) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
	});

	it('marks Settings under any of its screens, and not the ledger', () => {
		withFooter('/settings/rules/12');

		expect(screen.getByRole('link', { name: 'Settings' })).toHaveAttribute('aria-current', 'page');
		expect(screen.getByRole('link', { name: 'Ledger' })).not.toHaveAttribute('aria-current');
	});

	it('leaves Settings unmarked in the ledger, which stays marked', () => {
		withFooter('/ledger');

		expect(screen.getByRole('link', { name: 'Settings' })).not.toHaveAttribute('aria-current');
		expect(screen.getByRole('link', { name: 'Ledger' })).toHaveAttribute('aria-current', 'page');
	});

	it('has no secondary navigation without footer items', () => {
		shell('/ledger');

		expect(screen.queryByRole('navigation', { name: 'Secondary' })).toBeNull();
	});
});

describe('AppShell: the status line of an item', () => {
	function withStatus(status?: string, busy = false) {
		render(AppShell, {
			props: {
				items: [...items, { href: '/sync', label: 'Sync', icon: ListIcon, status, busy }],
				currentPath: '/ledger',
				userName: 'Ada',
				onlogout: vi.fn(),
				children: content
			}
		});
	}

	it('shows a second line and a spinner while the task runs', () => {
		withStatus('Syncing…', true);

		const link = screen.getByRole('link', { name: /^Sync/ });
		expect(link).toHaveTextContent('Syncing…');
		expect(link.querySelector('[data-slot="nav-spinner"]')).not.toBeNull();
	});

	it('shows the line of a finished task without a spinner', () => {
		withStatus('Finished · 3 ok, 1 failed');

		const link = screen.getByRole('link', { name: /^Sync/ });
		expect(link).toHaveTextContent('Finished · 3 ok, 1 failed');
		expect(link.querySelector('[data-slot="nav-spinner"]')).toBeNull();
	});

	it('shows no second line for an item without a status', () => {
		withStatus();

		expect(
			screen.getByRole('link', { name: 'Sync' }).querySelector('[data-slot="nav-status"]')
		).toBeNull();
	});
});

describe('AppShell: the count of an item', () => {
	function withCount(count?: number) {
		render(AppShell, {
			props: {
				items: [...items, { href: '/review', label: 'Review', icon: ListIcon, count }],
				currentPath: '/ledger',
				userName: 'Ada',
				onlogout: vi.fn(),
				children: content
			}
		});
	}

	it('shows the number beside the label as a count chip, in the neutral stone', () => {
		withCount(12);

		const count = screen
			.getByRole('link', { name: /^Review/ })
			.querySelector('[data-slot="nav-count"]');
		expect(count).toHaveTextContent('12');
		const chip = count!.querySelector('[data-slot="count-chip"]')!;
		expect(chip).toHaveClass('h-5', 'rounded-sm', 'tabular-nums');
		expect(chip).toHaveStyle({ '--chip-fg': 'var(--dim-stone)' });
	});

	it('shows nothing at zero, and nothing without a count', () => {
		withCount(0);
		expect(
			screen.getByRole('link', { name: 'Review' }).querySelector('[data-slot="nav-count"]')
		).toBeNull();
	});

	it('shows nothing for an item that has no count', () => {
		withCount();
		expect(
			screen.getByRole('link', { name: 'Review' }).querySelector('[data-slot="nav-count"]')
		).toBeNull();
	});
});
