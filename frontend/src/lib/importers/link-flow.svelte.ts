// "Link account" (ux/views/importers.md): a form dialog. Once an account is chosen it shows the
// link's dry run, the warning of spec §5.4, and the verb is "Link". A file importer is never asked
// for a reference. The dry run is asked again for every account chosen; a late answer for an account
// no longer chosen is dropped.
import {
	classifyImporterError,
	linkAccount,
	type ImporterInstance,
	type LinkResult
} from '#lib/api/importers.js';
import { describeImporterError } from './messages.js';

export type LinkHost = {
	/** the account is linked; `instance` is the instance as it now stands */
	linked: (instance: ImporterInstance, accountId: number, settleFailed: boolean) => void;
	/** the instance is gone */
	gone: (instance: ImporterInstance) => void;
};

export class LinkAccountFlow {
	readonly #host: LinkHost;
	open = $state(false);
	instance = $state.raw<ImporterInstance | null>(null);
	accountId = $state<number | null>(null);
	preview = $state.raw<LinkResult | null>(null);
	checking = $state(false);
	busy = $state(false);
	/** why the preview or the link failed, in words */
	error = $state<string | null>(null);
	#token = 0;

	constructor(host: LinkHost) {
		this.#host = host;
	}

	readonly canLink = $derived(this.preview !== null && !this.checking && !this.busy);

	start(instance: ImporterInstance): void {
		this.#token++;
		this.instance = instance;
		this.accountId = null;
		this.preview = null;
		this.checking = false;
		this.busy = false;
		this.error = null;
		this.open = true;
	}

	/** An account was chosen: ask what linking it would do. */
	async choose(accountId: number): Promise<void> {
		const instance = this.instance;
		if (!instance) return;
		const token = ++this.#token;
		this.accountId = accountId;
		this.preview = null;
		this.error = null;
		this.checking = true;
		try {
			const out = await linkAccount(instance.id, accountId, { dryRun: true });
			if (token !== this.#token) return;
			this.preview = out;
		} catch (error) {
			if (token !== this.#token) return;
			this.error = describeImporterError(classifyImporterError(error));
		}
		this.checking = false;
	}

	async confirm(): Promise<void> {
		const instance = this.instance;
		const accountId = this.accountId;
		const preview = this.preview;
		if (!instance || accountId === null || !preview || !this.canLink) return;
		const token = ++this.#token;
		this.busy = true;
		this.error = null;
		try {
			const out = await linkAccount(instance.id, accountId);
			if (token !== this.#token) return;
			this.close();
			this.#host.linked(
				{
					...instance,
					accounts: [
						...instance.accounts.filter((a) => a.account_id !== accountId),
						{ account_id: accountId, external_ref: out.external_ref }
					]
				},
				accountId,
				!!out.settle?.error
			);
		} catch (error) {
			if (token !== this.#token) return;
			this.busy = false;
			const failure = classifyImporterError(error);
			if (failure.kind === 'not_found') {
				this.close();
				this.#host.gone(instance);
				return;
			}
			this.error = describeImporterError(failure);
		}
	}

	close(): void {
		this.#token++;
		this.open = false;
		this.busy = false;
		this.checking = false;
		this.preview = null;
		this.accountId = null;
		this.error = null;
	}
}
