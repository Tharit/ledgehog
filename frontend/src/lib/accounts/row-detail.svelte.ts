// The row detail (ux/views/account.md): the provenance of one source transaction, read by its id
// (`GET /api/ledger/sources/{id}`), a duplicate included. Addressed by `?source=`, so it is loaded
// for whatever id the address names, whatever page of the statement the row is on.
import { ApiError, getProvenance } from '#lib/api/index.js';
import type { Provenance } from '#lib/types/domain.js';

export class RowDetail {
	id = $state<number | null>(null);
	provenance = $state.raw<Provenance | null>(null);
	status = $state<'idle' | 'loading' | 'ready' | 'missing' | 'error'>('idle');

	#controller: AbortController | null = null;
	#generation = 0;

	/** Show the row `id`, or nothing for null. The same id again does nothing. */
	async show(id: number | null): Promise<void> {
		if (id === this.id && (id === null || this.status !== 'error')) return;
		this.#controller?.abort();
		this.id = id;
		const generation = ++this.#generation;
		if (id === null) {
			this.provenance = null;
			this.status = 'idle';
			return;
		}
		const controller = new AbortController();
		this.#controller = controller;
		this.provenance = null;
		this.status = 'loading';
		try {
			const found = await getProvenance(id, controller.signal);
			if (generation !== this.#generation) return;
			this.provenance = found;
			this.status = 'ready';
		} catch (error) {
			if (generation !== this.#generation) return;
			this.status = error instanceof ApiError && error.code === 'not_found' ? 'missing' : 'error';
		}
	}

	/** Read the open row again (a write moved it: marked, cleared, edited). */
	async reload(): Promise<void> {
		const id = this.id;
		if (id === null) return;
		this.#controller?.abort();
		const controller = new AbortController();
		this.#controller = controller;
		const generation = ++this.#generation;
		try {
			const found = await getProvenance(id, controller.signal);
			if (generation !== this.#generation) return;
			this.provenance = found;
			this.status = 'ready';
		} catch (error) {
			if (generation !== this.#generation) return;
			this.status = error instanceof ApiError && error.code === 'not_found' ? 'missing' : 'error';
		}
	}

	dispose(): void {
		this.#controller?.abort();
		this.#generation++;
	}
}
