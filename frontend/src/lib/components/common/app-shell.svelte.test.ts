import { fireEvent, render, screen } from '@testing-library/svelte';
import ListIcon from '@lucide/svelte/icons/list';
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
