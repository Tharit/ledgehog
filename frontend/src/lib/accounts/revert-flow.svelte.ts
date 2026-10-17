// "Revert…" on an account's latest successful run (spec §5.6, I30): the decision is the revert's
// dry run, what it would remove and unpair, and the real call carries the versions that dry run
// reported. The server's answer is only ids, so how many of the removed entries are confirmed is
// counted by reading them, when there are few enough to read; nothing else is computed here.
import { getEntry, revertRun, type ImportRun, type RevertResult } from '#lib/api/index.js';
import { classifyWriteError, type WriteFailure } from './errors.js';

/** the most removed entries read to count the confirmed ones */
export const COUNTED_REMOVED = 50;

export type RevertStatus = 'checking' | 'ready' | 'error';

export class RevertFlow {
	run = $state.raw<ImportRun | null>(null);
	status = $state<RevertStatus>('checking');
	preview = $state.raw<RevertResult | null>(null);
	/** how many of the removed entries are confirmed; null when they were too many to read */
	confirmed = $state<number | null>(null);
	failure = $state.raw<WriteFailure | null>(null);
	busy = $state(false);

	#generation = 0;
	#controller: AbortController | null = null;

	readonly canRevert = $derived(this.status === 'ready' && !this.busy);

	start(run: ImportRun): void {
		this.run = run;
		this.failure = null;
		this.busy = false;
		void this.check();
	}

	stop(): void {
		this.#controller?.abort();
		this.#controller = null;
		this.#generation++;
	}

	async check(): Promise<void> {
		const run = this.run;
		if (!run) return;
		this.stop();
		const controller = new AbortController();
		this.#controller = controller;
		const generation = ++this.#generation;
		this.status = 'checking';
		this.preview = null;
		this.confirmed = null;
		try {
			const out = await revertRun(run.id, { dryRun: true, signal: controller.signal });
			if (generation !== this.#generation) return;
			let confirmed: number | null = null;
			if (out.removed_entry_ids.length <= COUNTED_REMOVED) {
				const read = await Promise.allSettled(
					out.removed_entry_ids.map((id) => getEntry(id, controller.signal))
				);
				if (generation !== this.#generation) return;
				if (read.every((r) => r.status === 'fulfilled')) {
					confirmed = read.filter(
						(r) => r.status === 'fulfilled' && !r.value.review_flags.includes('unconfirmed')
					).length;
				}
			}
			this.preview = out;
			this.confirmed = confirmed;
			this.status = 'ready';
		} catch (error) {
			if (generation !== this.#generation) return;
			this.status = 'error';
			this.failure = classifyWriteError(error);
		}
	}

	/** The revert's answer, or null with the refusal in `failure`; a conflict checks again. */
	async confirm(): Promise<RevertResult | null> {
		const run = this.run;
		const preview = this.preview;
		if (!run || !preview || !this.canRevert) return null;
		this.busy = true;
		this.failure = null;
		try {
			return await revertRun(run.id, { expectedVersions: preview.versions });
		} catch (error) {
			const failure = classifyWriteError(error);
			if (failure.kind === 'conflict' && failure.reason !== 'not_revertible') {
				await this.check();
				this.failure = failure;
			} else {
				this.failure = failure;
			}
			return null;
		} finally {
			this.busy = false;
		}
	}
}
