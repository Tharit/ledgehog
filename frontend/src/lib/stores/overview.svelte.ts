// The Overview (`/`): a computed view (patterns §7). It has no cursor to protect and nothing in it
// is removed under the user's hand, so a read after the ledger's change value moved replaces the
// figures when the answer arrives and shows nothing in between: the skeleton is for the first load
// only. Two reads side by side, the Overview's own and the top expense categories of the month,
// which is the By category report's answer with `top`, so the card and the report cannot disagree.
import { ApiError, getByCategory, getOverview } from '#lib/api/index.js';
import { todayIso } from '#lib/format/index.js';
import { monthStart } from '#lib/reports/figures.js';
import type { ByCategory, Overview } from '#lib/reports/types.js';
import { session } from './session.svelte.js';

type Status = 'loading' | 'ready' | 'error';

/** the largest top-level categories the card draws; the rest is "Other" */
export const TOP_CATEGORIES = 5;

function failure(error: unknown): ApiError {
	return error instanceof ApiError
		? error
		: new ApiError(0, 'network_error', 'The server could not be reached.');
}

export class OverviewStore {
	overview = $state.raw<Overview | null>(null);
	byCategory = $state.raw<ByCategory | null>(null);
	status = $state<Status>('loading');
	categoriesStatus = $state<Status>('loading');
	error = $state.raw<ApiError | null>(null);

	readonly locale = $derived(session.config?.locale ?? 'en');

	#generation = 0;

	/**
	 * Read both answers. What is on screen stays until they arrive; a read that fails after a
	 * success leaves the figures held (the next change reads again), one that fails first says so.
	 */
	async load(): Promise<void> {
		const generation = ++this.#generation;
		const today = todayIso(session.config?.timezone ?? 'UTC');
		const [overview, categories] = await Promise.allSettled([
			getOverview(),
			getByCategory({
				from: monthStart(today),
				to: today,
				kind: 'expense',
				top: TOP_CATEGORIES
			})
		]);
		if (generation !== this.#generation) return;

		if (overview.status === 'fulfilled') {
			this.overview = overview.value;
			this.error = null;
			this.status = 'ready';
		} else if (this.overview === null) {
			this.error = failure(overview.reason);
			this.status = 'error';
		}

		if (categories.status === 'fulfilled') {
			this.byCategory = categories.value;
			this.categoriesStatus = 'ready';
		} else if (this.byCategory === null) {
			this.categoriesStatus = 'error';
		}
	}

	/** Back to the first-load state (an error's "Try again"). */
	retry(): Promise<void> {
		if (this.status === 'error') this.status = 'loading';
		if (this.categoriesStatus === 'error') this.categoriesStatus = 'loading';
		return this.load();
	}

	dispose(): void {
		this.#generation++;
	}
}
