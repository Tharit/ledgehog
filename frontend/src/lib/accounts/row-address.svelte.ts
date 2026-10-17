// The row detail's address as state: which `?source=` the browser's address holds right now.
// SvelteKit's shallow routing (`pushState`, `replaceState`) changes the address bar but not `page.url`,
// so the page cannot read the address from `page.url`: like the unit panel (units/panel.svelte.ts) it
// reads the real address (`nav.url()`) after every Back, Forward and navigation (`sync`), and sets
// its own state when it opens or leaves a row, since the router may apply a push a moment later.
// Opening adds a history entry per open, closing takes them back.
import { sourceIdOf, withSource } from './address.js';
import { browserNav, type RowNav } from './row-nav.js';

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
		// the state is set here, not read back from the address: the router may apply a push a moment
		// later, and reading it at once would find the old address and open nothing (like the panel)
		this.id = id;
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
		if (this.#nav.url().searchParams.has('source') || this.id !== null) {
			this.#nav.replace(withSource(this.#nav.url(), null));
		}
		this.id = null;
	}
}
