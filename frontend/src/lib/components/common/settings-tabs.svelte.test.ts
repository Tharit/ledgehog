import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import SettingsTabs, { SETTINGS_TABS } from './settings-tabs.svelte';

function tabs(currentPath: string) {
	render(SettingsTabs, { props: { currentPath } });
}

describe('SettingsTabs', () => {
	it('links Categories, Payees, Tags and Rules', () => {
		tabs('/settings/rules');

		const nav = screen.getByRole('navigation', { name: 'Settings sections' });
		expect(nav.querySelectorAll('a')).toHaveLength(4);
		expect(screen.getByRole('link', { name: 'Categories' })).toHaveAttribute(
			'href',
			'/settings/categories'
		);
		expect(screen.getByRole('link', { name: 'Payees' })).toHaveAttribute(
			'href',
			'/settings/payees'
		);
		expect(screen.getByRole('link', { name: 'Tags' })).toHaveAttribute('href', '/settings/tags');
		expect(screen.getByRole('link', { name: 'Rules' })).toHaveAttribute('href', '/settings/rules');
		expect(SETTINGS_TABS.map((t) => t.label)).toEqual(['Categories', 'Payees', 'Tags', 'Rules']);
	});

	it('marks the current tab, also below it (the rule editor)', () => {
		tabs('/settings/rules/12');

		expect(screen.getByRole('link', { name: 'Rules' })).toHaveAttribute('aria-current', 'page');
		expect(screen.getByRole('link', { name: 'Payees' })).not.toHaveAttribute('aria-current');
	});

	it('marks none on another route', () => {
		tabs('/settings');

		expect(screen.getAllByRole('link').filter((a) => a.hasAttribute('aria-current'))).toHaveLength(
			0
		);
	});
});
