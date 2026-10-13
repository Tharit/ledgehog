// The delete decision: a dry run says what goes, the real delete carries the versions it reported.
import { ApiError, deleteSource } from '#lib/api/index.js';
import type { SourceDeleteOut } from '#lib/api/types.js';
import type { Entry } from '#lib/types/domain.js';
import type { FlowFeedback } from './add-flow.svelte.js';
import { entryForm } from './controller.svelte.js';
import { summarizeDelete } from './effects.js';
import { classifyEntryError } from './errors.js';

export type DeleteStatus = 'checking' | 'ready' | 'error';

function asApiError(error: unknown): ApiError {
	return error instanceof ApiError
		? error
		: new ApiError(0, 'network_error', 'The server could not be reached.');
}

function versionsOf(out: SourceDeleteOut): Record<number, number> {
	const versions: Record<number, number> = {};
	for (const e of [...out.removed, ...out.partners]) versions[e.id] = e.version;
	return versions;
}

export class DeleteFlow {
	entry = $state.raw<Entry | null>(null);
	status = $state<DeleteStatus>('checking');
	/** "Removes 1 entry (confirmed), 2 tags, and sends 1 partner back to review." */
	summary = $state<string | null>(null);
	feedback = $state.raw<FlowFeedback | null>(null);
	busy = $state(false);
	gone = $state(false);

	#versions: Record<number, number> = {};
	#generation = 0;
	#controller: AbortController | null = null;

	readonly canDelete = $derived(this.status === 'ready' && !this.busy && !this.gone);

	start(entry: Entry): void {
		this.entry = entry;
		this.feedback = null;
		this.busy = false;
		this.gone = false;
		void this.check();
	}

	stop(): void {
		this.#controller?.abort();
		this.#controller = null;
		this.#generation++;
	}

	async check(): Promise<void> {
		const entry = this.entry;
		if (!entry || entry.source_transaction_id === null) return;
		this.stop();
		const controller = new AbortController();
		this.#controller = controller;
		const generation = ++this.#generation;
		this.status = 'checking';
		this.summary = null;
		try {
			const out = await deleteSource(entry.source_transaction_id, {
				dryRun: true,
				signal: controller.signal
			});
			if (generation !== this.#generation) return;
			this.#versions = versionsOf(out);
			this.summary = summarizeDelete(out.counts);
			this.status = 'ready';
		} catch (error) {
			if (generation !== this.#generation) return;
			this.status = 'error';
			this.#reject(asApiError(error));
		}
	}

	retry(): void {
		this.feedback = null;
		void this.check();
	}

	/** True when it was deleted. */
	async confirm(): Promise<boolean> {
		const entry = this.entry;
		if (!entry || entry.source_transaction_id === null || !this.canDelete) return false;
		this.busy = true;
		this.feedback = null;
		try {
			const out = await deleteSource(entry.source_transaction_id, { versions: this.#versions });
			this.busy = false;
			entryForm.deleted(out, entry);
			return true;
		} catch (error) {
			this.busy = false;
			const failure = classifyEntryError(asApiError(error));
			if (failure.kind === 'conflict') {
				entryForm.refreshPanel();
				await this.check();
				this.feedback = {
					kind: 'conflict',
					text: 'This entry changed since you opened it. What would be removed is checked again above.'
				};
				return false;
			}
			this.#reject(asApiError(error));
			return false;
		}
	}

	#reject(error: ApiError): void {
		const failure = classifyEntryError(error);
		if (failure.kind === 'gone') this.gone = true;
		this.feedback = {
			kind: 'error',
			text: failure.text,
			retryable: failure.kind === 'error' ? failure.retryable : false
		};
	}
}
