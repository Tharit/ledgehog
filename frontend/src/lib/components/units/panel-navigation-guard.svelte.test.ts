import { render, screen } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { UnitPanel } from '#lib/units/panel.svelte.js';
import PanelNavigationGuard from './panel-navigation-guard.svelte';

type Navigation = { cancel: () => void; to: { url: URL } | null; willUnload: boolean };

const nav = vi.hoisted(() => ({
	callback: null as null | ((navigation: Navigation) => void),
	goto: vi.fn()
}));

vi.mock('$app/navigation', () => ({
	beforeNavigate: (callback: (navigation: Navigation) => void) => {
		nav.callback = callback;
	},
	goto: nav.goto
}));

function navigate(to: string | null = 'http://localhost/settings', willUnload = false) {
	const cancel = vi.fn();
	nav.callback!({ cancel, to: to === null ? null : { url: new URL(to) }, willUnload });
	return cancel;
}

/** A panel whose draft is (or is not) dirty, without loading a unit. */
function panel(dirty: boolean) {
	const p = new UnitPanel({
		url: () => new URL('http://x.test/'),
		push() {},
		replace() {},
		back() {}
	});
	Object.defineProperty(p.flow, 'isDirty', { get: () => dirty });
	return p;
}

beforeEach(() => {
	nav.callback = null;
	nav.goto.mockReset();
	nav.goto.mockResolvedValue(undefined);
});

describe('PanelNavigationGuard', () => {
	it('lets a clean panel go', () => {
		render(PanelNavigationGuard, { props: { panel: panel(false) } });
		expect(navigate()).not.toHaveBeenCalled();
	});

	it('stops a navigation away from a dirty draft and asks through the panel', () => {
		const p = panel(true);
		render(PanelNavigationGuard, { props: { panel: p } });

		const cancel = navigate();

		expect(cancel).toHaveBeenCalledOnce();
		expect(p.leave).not.toBeNull();
		expect(nav.goto).not.toHaveBeenCalled();
	});

	it('goes where it was going once the user discards', async () => {
		const p = panel(true);
		render(PanelNavigationGuard, { props: { panel: p } });
		navigate('http://localhost/settings/tags');

		p.confirmLeave();
		await Promise.resolve();

		expect(nav.goto).toHaveBeenCalledWith(new URL('http://localhost/settings/tags'));
	});

	it('leaves closing the tab to the browser’s own question', () => {
		const p = panel(true);
		render(PanelNavigationGuard, { props: { panel: p } });

		const cancel = navigate(null, true);

		expect(cancel).toHaveBeenCalledOnce();
		expect(p.leave).toBeNull();
		expect(screen.queryByRole('dialog')).toBeNull();
	});
});
