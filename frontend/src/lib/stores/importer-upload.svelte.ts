// State of the upload page (ux/views/importers.md "Uploading a file"): one page, three steps. Choosing
// a file starts the dry run at once; "Check again" reruns it on the same file with the profile as it
// is saved now (the page keeps the file, so adjusting a profile never means choosing it again);
// "Upload" runs the real operation with the same file. A refusal of the request itself stands above
// the buttons (patterns §11.5). Page-scoped.
import {
	classifyImporterError,
	getRun,
	listInstances,
	uploadFile,
	type ImporterError,
	type ImporterInstance,
	type UploadResult
} from '#lib/api/importers.js';
import { describeImporterError } from '#lib/importers/messages.js';
import { dryRunAsRun, type RunSummaryInput } from '#lib/importers/run.js';
import { SETTLE_STALE } from '#lib/ledger/errors.js';
import type { Account } from '#lib/types/domain.js';
import { lookupsStore } from './lookups.svelte.js';
import { session } from './session.svelte.js';

export type UploadLoad = 'loading' | 'ready' | 'missing' | 'error';
/** where the page stands: nothing chosen, checking, the report, uploading, or the run summary */
export type UploadPhase = 'choose' | 'checking' | 'report' | 'uploading' | 'done';

export class ImporterUploadStore {
	readonly accountId: number;
	readonly instanceId: number;

	loadStatus = $state<UploadLoad>('loading');
	loadError = $state.raw<ImporterError | null>(null);
	instance = $state.raw<ImporterInstance | null>(null);
	phase = $state<UploadPhase>('choose');
	file = $state.raw<File | null>(null);
	/** the dry run's answer: the report, the run as it would stand, or the failure it would end in */
	dry = $state.raw<UploadResult | null>(null);
	/** the real upload's answer */
	result = $state.raw<UploadResult | null>(null);
	/** the run as stored, for the summary after an upload */
	run = $state.raw<RunSummaryInput | null>(null);
	/** a refusal of the request itself, or a failure of the real run; shown above the buttons */
	refusal = $state<string | null>(null);
	/** a quiet line after the upload (a settle that failed) */
	notice = $state<string | null>(null);

	#token = 0;

	constructor({ accountId, instanceId }: { accountId: number; instanceId: number }) {
		this.accountId = accountId;
		this.instanceId = instanceId;
	}

	readonly locale = $derived(session.config?.locale ?? 'en');
	get account(): Account | null {
		return lookupsStore.lookups.accounts.get(this.accountId) ?? null;
	}

	/** why no file can go to this account through this instance, before anything is chosen */
	readonly blocked = $derived.by<ImporterError | null>(() => {
		const instance = this.instance;
		const account = this.account;
		if (!instance || !account) return null;
		if (!instance.emits.includes('transactions')) return { kind: 'not_a_file_source' };
		if (instance.disabled) return { kind: 'instance_disabled' };
		if (account.closed_on !== null) return { kind: 'account_closed' };
		if (!instance.accounts.some((a) => a.account_id === this.accountId)) {
			return { kind: 'account_not_linked' };
		}
		return null;
	});

	/** why "Upload" is not available yet; null when it is */
	readonly uploadBlocked = $derived.by<string | null>(() => {
		if (this.blocked) return describeImporterError(this.blocked);
		if (!this.file) return 'Choose a file first.';
		if (this.phase === 'checking' || !this.dry) return 'The file is being checked.';
		if (this.dry.failure) return 'The check found a failure; adjust the profile and check again.';
		return null;
	});

	async init(): Promise<void> {
		this.loadStatus = 'loading';
		this.loadError = null;
		const [instances] = await Promise.allSettled([listInstances(), lookupsStore.ensure()]);
		if (instances.status === 'rejected') {
			this.loadError = classifyImporterError(instances.reason);
			this.loadStatus = 'error';
			return;
		}
		this.instance = instances.value.find((i) => i.id === this.instanceId) ?? null;
		this.loadStatus = this.instance && this.account ? 'ready' : 'missing';
	}

	/** A file was chosen (or cleared): start the dry run at once. */
	async choose(file: File | null): Promise<void> {
		this.#token++;
		this.file = file;
		this.dry = null;
		this.refusal = null;
		this.phase = 'choose';
		if (file) await this.check();
	}

	/** Run the dry run on the file held, with the profile as it is saved now. */
	async check(): Promise<void> {
		const file = this.file;
		if (!file || this.blocked || this.phase === 'uploading') return;
		const token = ++this.#token;
		this.phase = 'checking';
		this.refusal = null;
		try {
			// the profile may have been edited in another tab: take the instance as it is now
			const [out] = await Promise.all([
				uploadFile(this.instanceId, { file, accountId: this.accountId, dryRun: true }),
				this.#refreshInstance()
			]);
			if (token !== this.#token) return;
			this.dry = out;
			this.phase = 'report';
		} catch (error) {
			if (token !== this.#token) return;
			this.dry = null;
			this.phase = 'choose';
			this.refusal = describeImporterError(classifyImporterError(error));
		}
	}

	async #refreshInstance(): Promise<void> {
		try {
			const found = (await listInstances()).find((i) => i.id === this.instanceId);
			if (found) this.instance = found;
		} catch {
			// the instance held stays; the upload itself will say what is wrong
		}
	}

	/** "Upload": the real operation with the same file. */
	async commit(): Promise<void> {
		const file = this.file;
		if (!file || this.uploadBlocked !== null || this.phase !== 'report') return;
		const token = ++this.#token;
		this.phase = 'uploading';
		this.refusal = null;
		try {
			const out = await uploadFile(this.instanceId, {
				file,
				accountId: this.accountId,
				dryRun: false
			});
			if (token !== this.#token) return;
			this.result = out;
			this.notice = out.settle?.error ? SETTLE_STALE : null;
			this.run = await this.#storedRun(out);
			if (token !== this.#token) return;
			this.phase = 'done';
			// the account has rows and a balance now: its facts moved
			void lookupsStore.reload();
		} catch (error) {
			if (token !== this.#token) return;
			// a refusal of the request, or the failure the real run ended in (what the dry run would
			// have shown): nothing was imported, and the report stays for another try
			this.phase = 'report';
			this.refusal = describeImporterError(classifyImporterError(error));
		}
	}

	/** The run as stored (its coverage from and through); the upload's own answer when it cannot be read. */
	async #storedRun(out: UploadResult): Promise<RunSummaryInput> {
		if (out.run_id !== null) {
			try {
				return await getRun(out.run_id);
			} catch {
				// fall through
			}
		}
		return { ...dryRunAsRun(out, this.accountId) };
	}

	dispose(): void {
		this.#token++;
	}
}
