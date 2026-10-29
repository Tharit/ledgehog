import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import { REPORT_TABS } from '#lib/reports/params.js';
import SectionTabs from './section-tabs.svelte';

describe('SectionTabs', () => {
	it('links the three reports and marks the current one', () => {
		render(SectionTabs, {
			props: { tabs: REPORT_TABS, label: 'Reports', currentPath: '/reports/over-time' }
		});

		const nav = screen.getByRole('navigation', { name: 'Reports' });
		expect([...nav.querySelectorAll('a')].map((a) => a.getAttribute('href'))).toEqual([
			'/reports/by-category',
			'/reports/over-time',
			'/reports/balances'
		]);
		expect(screen.getByRole('link', { name: 'Over time' })).toHaveAttribute('aria-current', 'page');
		expect(screen.getByRole('link', { name: 'Balances' })).not.toHaveAttribute('aria-current');
	});

	it('carries the shared query onto every tab', () => {
		render(SectionTabs, {
			props: {
				tabs: REPORT_TABS,
				label: 'Reports',
				currentPath: '/reports/by-category',
				query: 'from=2026-01-01&to=2026-02-01&tag_id=4'
			}
		});

		expect(screen.getByRole('link', { name: 'Balances' })).toHaveAttribute(
			'href',
			'/reports/balances?from=2026-01-01&to=2026-02-01&tag_id=4'
		);
	});

	it('marks an exact tab current on its own path alone', () => {
		const tabs = [
			{ href: '/accounts/5', label: 'Transactions', exact: true },
			{ href: '/accounts/5/runs', label: 'Runs' }
		];
		const { unmount } = render(SectionTabs, {
			props: { tabs, label: 'Account', currentPath: '/accounts/5/runs' }
		});
		expect(screen.getByRole('link', { name: 'Runs' })).toHaveAttribute('aria-current', 'page');
		expect(screen.getByRole('link', { name: 'Transactions' })).not.toHaveAttribute('aria-current');
		unmount();
		render(SectionTabs, { props: { tabs, label: 'Account', currentPath: '/accounts/5' } });
		expect(screen.getByRole('link', { name: 'Transactions' })).toHaveAttribute(
			'aria-current',
			'page'
		);
	});
});
