// How the row detail reaches the browser's address and history (see row-address.svelte.ts); the
// page gives it SvelteKit's shallow routing, tests the browser's own.
export type RowNav = {
	url: () => URL;
	push: (url: string) => void;
	replace: (url: string) => void;
	back: (steps: number) => void;
};

export const browserNav: RowNav = {
	url: () => new URL(location.href),
	push: (url) => history.pushState(null, '', url),
	replace: (url) => history.replaceState(null, '', url),
	back: (steps) => history.go(-steps)
};
