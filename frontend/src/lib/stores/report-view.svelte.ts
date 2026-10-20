// One report as a computed view (patterns §7): it has no cursor to protect and nothing in it is
// removed under the user's hand, so a read after the ledger's change value moved, or after a
// control changed, replaces the figures when the answer arrives and shows nothing in between: the
// skeleton is for the first load only. The answer of the latest read wins; an older one is
// dropped. A read that fails keeps what is on screen when the controls did not change (the next
// change reads again); one that fails for new controls says so, since what is held answers
// another question.
import { ApiError } from '#lib/api/index.js';

type Status = 'loading' | 'ready' | 'error';

function failure(error: unknown): ApiError {
	return error instanceof ApiError
		? error
		: new ApiError(0, 'network_error', 'The server could not be reached.');
}

export class ReportView<P, T> {
	data = $state.raw<T | null>(null);
	status = $state<Status>('loading');
	error = $state.raw<ApiError | null>(null);

	readonly #fetch: (params: P, signal: AbortSignal) => Promise<T>;
	readonly #keyOf: (params: P) => string;
	#params: P | null = null;
	#shownKey: string | null = null;
	#generation = 0;
	#abort: AbortController | null = null;

	constructor(fetch: (params: P, signal: AbortSignal) => Promise<T>, keyOf: (params: P) => string) {
		this.#fetch = fetch;
		this.#keyOf = keyOf;
	}

	/** Read the answer for these controls. What is on screen stays until it arrives. */
	async load(params: P): Promise<void> {
		this.#params = params;
		const key = this.#keyOf(params);
		const generation = ++this.#generation;
		this.#abort?.abort();
		const abort = (this.#abort = new AbortController());
		try {
			const data = await this.#fetch(params, abort.signal);
			if (generation !== this.#generation) return;
			this.data = data;
			this.#shownKey = key;
			this.error = null;
			this.status = 'ready';
		} catch (error) {
			if (generation !== this.#generation) return;
			if (this.data !== null && this.#shownKey === key) return; // held: the next change reads again
			this.data = null;
			this.#shownKey = null;
			this.error = failure(error);
			this.status = 'error';
		}
	}

	/** Read again for the controls last read (the ledger's change value moved). */
	reload(): Promise<void> {
		return this.#params === null ? Promise.resolve() : this.load(this.#params);
	}

	/** An error's "Try again": back to the first-load state. */
	retry(): Promise<void> {
		if (this.status === 'error') this.status = 'loading';
		return this.reload();
	}

	dispose(): void {
		this.#generation++;
		this.#abort?.abort();
	}
}
