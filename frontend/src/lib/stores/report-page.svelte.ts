// What every report page does the same way: its controls are the URL (a report can be bookmarked and
// shared) and a change of them reads the answer again (patterns §7). The controller holds that with
// the address and the clock as dependencies; `useReport` (report-route) wires it to the router.
import { parseParams, toQuery, type ReportId, type ReportParams } from '#lib/reports/params.js';
import { ReportView } from './report-view.svelte.js';

export type ReportDeps = {
	/** the address' query string */
	search: () => string;
	/** go to a path with a query (replacing the history entry) */
	navigate: (path: string) => void;
	today: () => string;
	pathname: () => string;
};

export class ReportController<T> {
	readonly view: ReportView<ReportParams, T>;
	readonly #id: ReportId;
	readonly #deps: ReportDeps;

	constructor(
		id: ReportId,
		fetcher: (params: ReportParams, signal: AbortSignal) => Promise<T>,
		deps: ReportDeps
	) {
		this.#id = id;
		this.#deps = deps;
		this.view = new ReportView<ReportParams, T>(fetcher, (p) => JSON.stringify(p));
	}

	/** The controls the address says. */
	get params(): ReportParams {
		return parseParams(this.#deps.search(), this.#id, this.#deps.today());
	}

	/** Read the answer for the controls the address says now. */
	sync(): Promise<void> {
		return this.view.load(this.params);
	}

	/** Change some controls: the address is the controls, so this is a navigation. */
	change(patch: Partial<ReportParams>): void {
		const query = toQuery({ ...this.params, ...patch }, this.#id, this.#deps.today()).toString();
		this.#deps.navigate(`${this.#deps.pathname()}${query ? `?${query}` : ''}`);
	}

	dispose(): void {
		this.view.dispose();
	}
}
