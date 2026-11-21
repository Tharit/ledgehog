import { tick } from 'svelte';
import { trackTemplate } from '#lib/ledger/column-sizing.js';
import { sizingColumns, type Column } from './columns.js';

// Measures what the rows of one or several grids hold and yields the grid-template-columns value
// that sizes the columns by it (patterns §4.1: "columns are as wide as what they hold"). The
// grids that share one set of widths (the review queue's sections) each take `attach`; every cell
// of a column, header cells included, carries `data-col="<column id>"` and counts, so a column is
// never narrower than its label. Call `remeasure()` when the rows held change; resizes and the
// loading of fonts are watched here.

const ROW_PADDING = 24; // px-3 on both sides of a row
const GAP = 12; // gap-x-3 between tracks

export class ColumnSizer {
	/** the widest cell per column id, px; null until the first measurement */
	measured = $state<Record<string, number> | null>(null);
	/** the width of the narrowest grid, px; 0 before there is one */
	width = $state(0);

	readonly #columns: () => readonly Column[];
	// plain bookkeeping, never read by a template or a derived
	// eslint-disable-next-line svelte/prefer-svelte-reactivity
	readonly #roots = new Set<HTMLElement>();
	readonly #observer =
		typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(() => this.#resize());
	#version = 0;

	constructor(columns: () => readonly Column[]) {
		this.#columns = columns;
	}

	/** the grid-template-columns value; undefined while nothing is measured (use the static one) */
	readonly template = $derived.by(() => {
		const measured = this.measured;
		const columns = this.#columns();
		if (!measured || this.width <= 0) return undefined;
		const available = this.width - ROW_PADDING - GAP * (columns.length - 1);
		return trackTemplate(available, sizingColumns(columns, measured));
	});

	/** An attachment (`{@attach sizer.attach}`): this grid takes part in the measuring. */
	attach = (root: HTMLElement) => {
		this.#roots.add(root);
		this.#observer?.observe(root);
		this.#resize();
		this.remeasure();
		return () => {
			this.#roots.delete(root);
			this.#observer?.unobserve(root);
			this.#resize();
		};
	};

	/** Measure again once the DOM has the new rows, and again when the fonts are in. */
	remeasure() {
		const version = ++this.#version;
		const run = () => {
			if (version === this.#version) this.#measure();
		};
		void tick().then(run);
		void document.fonts?.ready.then(run);
	}

	#resize() {
		const widths = [...this.#roots].map((root) => root.clientWidth);
		this.width = widths.length > 0 ? Math.min(...widths) : 0;
	}

	#measure() {
		if (this.#roots.size === 0) return;
		// cells are as wide as their content for an instant, in one synchronous pass: no paint
		for (const root of this.#roots) root.setAttribute('data-measuring', '');
		const next: Record<string, number> = {};
		let any = false;
		for (const root of this.#roots) {
			for (const cell of root.querySelectorAll<HTMLElement>('[data-col]')) {
				const id = cell.dataset.col!;
				next[id] = Math.max(next[id] ?? 0, Math.ceil(cell.getBoundingClientRect().width));
				any = true;
			}
		}
		for (const root of this.#roots) root.removeAttribute('data-measuring');
		this.measured = any ? next : null;
	}
}
