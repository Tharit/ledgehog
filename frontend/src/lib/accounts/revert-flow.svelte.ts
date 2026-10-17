// "Revert…" on an account's latest successful run (spec §5.6, I30): the decision is the revert's
// dry run, what it would remove and unpair (with the confirmed ones counted by the server), and the
// real call carries the versions that dry run reported; nothing is computed here.
import { revertRun, type ImportRun, type RevertResult } from '#lib/api/index.js';
import { classifyWriteError, type WriteFailure } from './errors.js';

export type RevertStatus = 'checking' | 'ready' | 'error';

export class RevertFlow {
	run = $state.raw<ImportRun | null>(null);
	status = $state<RevertStatus>('checking');
	preview = $state.raw<RevertResult | null>(null);
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
		try {
			const out = await revertRun(run.id, { dryRun: true, signal: controller.signal });
			if (generation !== this.#generation) return;
			this.preview = out;
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
