// The decisions about an instance that ask first (patterns §11.2): Delete…, Reset… and Unlink….
// One flow for the three, shared by the list and the instance page; the host says what happens once
// the write is done. The server's refusal (an instance that has runs, a link already gone) stands
// in the dialog as an error and nothing is written (patterns §11.5).
import {
	classifyImporterError,
	deleteInstance,
	resetInstance,
	unlinkAccount,
	type ImporterInstance
} from '#lib/api/importers.js';
import { describeImporterError } from './messages.js';

export type DecisionKind = 'delete' | 'reset' | 'unlink';

export type DecisionHost = {
	/** the write is done; `instance` is the instance as it now stands (null once deleted) */
	done: (
		kind: DecisionKind,
		instance: ImporterInstance,
		now: ImporterInstance | null,
		accountId: number | null,
		settleFailed: boolean
	) => void;
	/** the instance or the link was already gone */
	gone: (kind: DecisionKind, instance: ImporterInstance) => void;
};

export class InstanceDecisionFlow {
	readonly #host: DecisionHost;
	open = $state(false);
	kind = $state<DecisionKind>('delete');
	instance = $state.raw<ImporterInstance | null>(null);
	accountId = $state<number | null>(null);
	busy = $state(false);
	/** why the last attempt failed, in words */
	error = $state<string | null>(null);
	#token = 0;

	constructor(host: DecisionHost) {
		this.#host = host;
	}

	start(kind: DecisionKind, instance: ImporterInstance, accountId: number | null = null): void {
		this.#token++;
		this.kind = kind;
		this.instance = instance;
		this.accountId = accountId;
		this.error = null;
		this.busy = false;
		this.open = true;
	}

	async confirm(): Promise<void> {
		const instance = this.instance;
		if (!instance || this.busy) return;
		const kind = this.kind;
		const accountId = this.accountId;
		const token = this.#token;
		this.busy = true;
		this.error = null;
		try {
			let now: ImporterInstance | null = null;
			let settleFailed = false;
			if (kind === 'delete') {
				const out = await deleteInstance(instance.id);
				settleFailed = !!out.settle?.error;
			} else if (kind === 'reset') {
				now = await resetInstance(instance.id);
			} else if (accountId !== null) {
				const out = await unlinkAccount(instance.id, accountId);
				settleFailed = !!out.settle?.error;
				now = {
					...instance,
					accounts: instance.accounts.filter((a) => a.account_id !== accountId)
				};
			}
			if (token !== this.#token) return;
			this.close();
			this.#host.done(kind, instance, now, accountId, settleFailed);
		} catch (error) {
			if (token !== this.#token) return;
			this.busy = false;
			const failure = classifyImporterError(error);
			if (failure.kind === 'not_found') {
				this.close();
				this.#host.gone(kind, instance);
				return;
			}
			this.error = describeImporterError(failure);
		}
	}

	close(): void {
		this.#token++;
		this.open = false;
		this.busy = false;
		this.error = null;
	}
}
