// A report page's wiring (patterns §7): the controller on the router and the clock, the answer read
// again when the address changes and when the ledger's change value moves. Call while a component
// initialises.
import { goto } from '$app/navigation';
import { page } from '$app/state';
import { onDestroy, untrack } from 'svelte';
import { todayIso } from '#lib/format/index.js';
import type { ReportId, ReportParams } from '#lib/reports/params.js';
import { lookupsStore } from './lookups.svelte.js';
import { refetchOnChange } from './new-data.svelte.js';
import { ReportController } from './report-page.svelte.js';
import { session } from './session.svelte.js';

const today = () => todayIso(session.config?.timezone ?? 'UTC');

export function useReport<T>(
	id: ReportId,
	fetcher: (params: ReportParams, signal: AbortSignal) => Promise<T>
) {
	const controller = new ReportController(id, fetcher, {
		search: () => page.url.search,
		navigate: (path) => void goto(path, { replaceState: true }),
		today,
		pathname: () => page.url.pathname
	});

	$effect(() => {
		// reads the address and the clock: a change of either reads the answer again
		const params = controller.params;
		untrack(() => void controller.view.load(params));
	});
	void lookupsStore.ensure();
	refetchOnChange('ledger', () => void controller.view.reload());
	onDestroy(() => controller.dispose());

	return {
		view: controller.view,
		get params() {
			return controller.params;
		},
		get today() {
			return today();
		},
		get locale() {
			return session.config?.locale ?? 'en';
		},
		change: (patch: Partial<ReportParams>) => controller.change(patch)
	};
}
