// The row detail's address as state: which `?source=` the browser's address holds right now.
// SvelteKit's shallow routing (`pushState`, `replaceState`) changes the address bar but not `page.url`,
// so the page cannot read the address from `page.url`: like the unit panel (units/panel.svelte.ts) it
// reads the real address (`nav.url()`) after every change it makes and after every Back, Forward and
// navigation (`sync`). Opening adds a history entry per open, closing takes them back.
import { sourceIdOf, withSource } from './address.js';

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

export class RowAddress {
	/** the row the address names, or null */
	id = $state<number | null>(null);

	#nav: RowNav;
	#pushed = 0;

	constructor(nav: RowNav = browserNav) {
		this.#nav = nav;
	}

	/** Read the address again: on load, after Back or Forward, after a navigation. */
	sync(): void {
		this.id = sourceIdOf(this.#nav.url());
		if (this.id === null) this.#pushed = 0;
	}

	/** Open a row's detail: a history entry of its own. */
	open(id: number): void {
		if (id === this.id) return;
		this.#nav.push(withSource(this.#nav.url(), id));
		this.#pushed += 1;
		this.sync();
	}

	/** The user closed it: take back the entries opening added, else just drop the parameter. */
	close(): void {
		if (this.#pushed > 0) {
			const steps = this.#pushed;
			this.#pushed = 0;
			this.#nav.back(steps);
			// Back is under way (a popstate follows); the dialog goes at once
			this.id = null;
		} else this.leave();
	}

	/** Leave for the work panel or another dialog: the address changes at once. */
	leave(): void {
		this.#pushed = 0;
		if (this.#nav.url().searchParams.has('source')) {
			this.#nav.replace(withSource(this.#nav.url(), null));
		}
		this.sync();
	}
}
