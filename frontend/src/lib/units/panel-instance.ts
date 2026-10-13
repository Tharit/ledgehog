// THE panel: one store for the whole app, mounted once in the root layout (components/units).
// Lists open it with `unitPanel.open(id)`. Its navigation is the browser's history until the
// layout hands it the router's (`setPanelNav`), so tests and early callers need no router.
import { session } from '#lib/stores/session.svelte.js';
import { UnitPanel, type PanelNav } from './panel.svelte.js';

let router: PanelNav | null = null;

/** The layout gives the panel SvelteKit's shallow routing, so the router's history stays in step. */
export function setPanelNav(nav: PanelNav | null): void {
	router = nav;
}

const browser: PanelNav = {
	url: () => new URL(location.href),
	push: (url) => history.pushState(null, '', url),
	replace: (url) => history.replaceState(null, '', url),
	back: () => history.back()
};

const delegate: PanelNav = {
	url: () => (router ?? browser).url(),
	push: (url) => (router ?? browser).push(url),
	replace: (url) => (router ?? browser).replace(url),
	back: () => (router ?? browser).back()
};

export const unitPanel = new UnitPanel(delegate, () => session.config?.locale ?? 'en');
