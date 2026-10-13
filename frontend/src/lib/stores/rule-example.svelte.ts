// State of the rule editor's example (spec §5.9): the entry the user looks at while writing the
// conditions. It is found with a find box (the entries list's `q`, debounced) or arrives with the
// page (`?from=<id>`, read with `getEntry`). It never feeds the form and never changes what is
// saved. The address follows it (`onchange`), so a reload keeps the example. Page-scoped.

import { getEntry, listEntries, type Entry } from '#lib/api/index.js';
import { emptyFilter } from '#lib/ledger/filter.js';

/** the pause after the last keystroke before the search is asked for */
export const FIND_DEBOUNCE_MS = 300;
/** the results one search shows; the user narrows the text rather than paging */
export const FIND_LIMIT = 8;
/** the longest text the entries list accepts as `q` */
const MAX_QUERY = 200;

export type ExampleLoad = 'none' | 'loading' | 'ready' | 'missing' | 'error';
export type FindStatus = 'idle' | 'loading' | 'ready' | 'error';

export type RuleExampleOptions = {
	/** the entry the page opened with */
	initialId?: number | null;
	/** the example changed: the id, or null when it was cleared (the page puts it in the address) */
	onchange?: (id: number | null) => void;
	debounceMs?: number;
};

export class RuleExampleStore {
	readonly #initialId: number | null;
	readonly #onchange: (id: number | null) => void;
	readonly #debounce: number;
	#timer: ReturnType<typeof setTimeout> | null = null;
	#controller: AbortController | null = null;
	#seq = 0;

	/** the example, once loaded */
	entry = $state.raw<Entry | null>(null);
	loadStatus = $state<ExampleLoad>('none');
	/** the find box is showing: always without an example, on "Change" with one */
	finding = $state(false);
	/** the result list is showing under the find box */
	open = $state(false);
	query = $state('');
	results = $state.raw<Entry[]>([]);
	/** how many entries match the text, whatever the page */
	total = $state(0);
	findStatus = $state<FindStatus>('idle');
	/** the index of the highlighted result, -1 for none */
	highlighted = $state(-1);

	constructor({
		initialId = null,
		onchange,
		debounceMs = FIND_DEBOUNCE_MS
	}: RuleExampleOptions = {}) {
		this.#initialId = initialId;
		this.#onchange = onchange ?? (() => {});
		this.#debounce = debounceMs;
		this.finding = initialId === null;
	}

	/** The text the search is asked with: trimmed and cut to what the API takes; blank is none. */
	get searchText(): string {
		return this.query.trim().slice(0, MAX_QUERY);
	}

	/** Load the example the page opened with. A failure leaves the find box, with a line saying so. */
	async init(): Promise<void> {
		if (this.#initialId === null) return;
		this.loadStatus = 'loading';
		try {
			const entry = await getEntry(this.#initialId);
			this.entry = entry;
			this.loadStatus = 'ready';
			this.finding = false;
		} catch (error) {
			const notFound = (error as { status?: number } | null)?.status === 404;
			this.loadStatus = notFound ? 'missing' : 'error';
			this.finding = true;
		}
	}

	/** The user typed: search after the pause. Blank text shows nothing and asks for nothing. */
	setQuery(text: string): void {
		this.query = text;
		this.open = true;
		this.#cancel();
		const seq = ++this.#seq;
		if (this.searchText === '') {
			this.results = [];
			this.total = 0;
			this.highlighted = -1;
			this.findStatus = 'idle';
			return;
		}
		this.findStatus = 'loading';
		this.#timer = setTimeout(() => void this.#search(seq), this.#debounce);
	}

	/** Ask again for the text as it stands (after a failure). */
	retry(): void {
		this.#cancel();
		const seq = ++this.#seq;
		if (this.searchText === '') return;
		this.findStatus = 'loading';
		void this.#search(seq);
	}

	async #search(seq: number): Promise<void> {
		this.#timer = null;
		const controller = new AbortController();
		this.#controller = controller;
		try {
			// derived entries (opening, valuation, reconciliation) have nothing a rule could read
			const page = await listEntries(
				{ ...emptyFilter(), q: this.searchText, type: ['flow', 'transfer'] },
				{ limit: FIND_LIMIT, signal: controller.signal }
			);
			if (seq !== this.#seq) return;
			this.results = page.entries;
			this.total = page.total;
			this.highlighted = page.entries.length > 0 ? 0 : -1;
			this.findStatus = 'ready';
		} catch {
			if (seq !== this.#seq) return;
			this.results = [];
			this.total = 0;
			this.highlighted = -1;
			this.findStatus = 'error';
		}
	}

	/** Move the highlight by one result; it stops at both ends. */
	move(delta: number): void {
		if (this.results.length === 0) return;
		this.open = true;
		const next =
			this.highlighted < 0 ? (delta > 0 ? 0 : this.results.length - 1) : this.highlighted + delta;
		this.highlighted = Math.min(this.results.length - 1, Math.max(0, next));
	}

	/** Choose an entry (the highlighted one by default) as the example. */
	pick(entry: Entry | undefined = this.results[this.highlighted]): boolean {
		if (!entry) return false;
		this.#cancel();
		this.#seq++;
		this.entry = entry;
		this.loadStatus = 'ready';
		this.finding = false;
		this.open = false;
		this.#reset();
		this.#onchange(entry.id);
		return true;
	}

	/** Open the find box to choose another example; the current one stays until one is chosen. */
	change(): void {
		this.finding = true;
		this.open = false;
		this.#reset();
	}

	/** Esc: close the results; with an example in place, close the find box too and keep it. */
	escape(): void {
		if (this.open && this.results.length > 0) {
			this.open = false;
			return;
		}
		if (this.entry) {
			this.cancelFind();
		} else {
			this.open = false;
		}
	}

	/** Leave the find box without choosing, back to the example. */
	cancelFind(): void {
		if (!this.entry) return;
		this.#cancel();
		this.#seq++;
		this.finding = false;
		this.open = false;
		this.#reset();
	}

	/** Remove the example: nothing is shown, the find box is back. */
	clear(): void {
		this.#cancel();
		this.#seq++;
		this.entry = null;
		this.loadStatus = 'none';
		this.finding = true;
		this.open = false;
		this.#reset();
		this.#onchange(null);
	}

	#reset(): void {
		this.query = '';
		this.results = [];
		this.total = 0;
		this.highlighted = -1;
		this.findStatus = 'idle';
	}

	#cancel(): void {
		if (this.#timer !== null) clearTimeout(this.#timer);
		this.#timer = null;
		this.#controller?.abort();
		this.#controller = null;
	}

	dispose(): void {
		this.#seq++;
		this.#cancel();
	}
}
