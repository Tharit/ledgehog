// Finding a document by hand for the panel's document field (spec §5.8; documents view): the
// documents of one provider not yet fully charged, searched by text. A short list for a popover,
// not a page: the newest first, `total` says when more exist. The latest search wins.
import { ApiError, listDocuments } from '#lib/api/index.js';
import type { DocumentRow } from '#lib/types/domain.js';

export type FinderStatus = 'idle' | 'loading' | 'ready' | 'error';

/** how many documents the popover lists */
export const FINDER_LIMIT = 20;
/** how long typing rests before the search is asked for */
export const FINDER_DELAY_MS = 250;

export class DocumentFinder {
	documents = $state.raw<readonly DocumentRow[]>([]);
	total = $state(0);
	status = $state<FinderStatus>('idle');
	error = $state.raw<ApiError | null>(null);

	#timer: ReturnType<typeof setTimeout> | null = null;
	#controller: AbortController | null = null;
	#generation = 0;

	/** Search `provider`'s documents not fully charged for `text`; `immediate` skips the typing delay. */
	search(provider: string, text: string, immediate = false): void {
		this.#cancel();
		this.status = 'loading';
		const generation = ++this.#generation;
		const run = () => void this.#run(provider, text, generation);
		if (immediate) run();
		else this.#timer = setTimeout(run, FINDER_DELAY_MS);
	}

	async #run(provider: string, text: string, generation: number): Promise<void> {
		const controller = new AbortController();
		this.#controller = controller;
		try {
			const page = await listDocuments(
				{ provider: [provider], q: text.trim(), fully_charged: false },
				{ limit: FINDER_LIMIT, signal: controller.signal }
			);
			if (generation !== this.#generation) return;
			this.documents = page.documents;
			this.total = page.total;
			this.error = null;
			this.status = 'ready';
		} catch (error) {
			if (generation !== this.#generation) return;
			this.error =
				error instanceof ApiError
					? error
					: new ApiError(0, 'network_error', 'The server could not be reached.');
			this.status = 'error';
		}
	}

	#cancel(): void {
		if (this.#timer !== null) clearTimeout(this.#timer);
		this.#timer = null;
		this.#controller?.abort();
		this.#controller = null;
	}

	/** Nothing may land any more (the popover closed, the panel moved on). */
	dispose(): void {
		this.#generation++;
		this.#cancel();
		this.status = 'idle';
	}
}
