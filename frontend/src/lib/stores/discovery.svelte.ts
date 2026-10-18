// The Refresh accounts page (ux/views/importers.md): one instance's discovery. The discovery is a
// task like a sync and lives in the sync store; this holds what the page adds: the instance it is
// for, the result read from the task's status (and read again after a link, so the rows change
// state in place), the link and add-and-link actions, and the one notice line.
import {
	classifyImporterError,
	getTaskStatus,
	linkAccount,
	listImporters,
	listInstances,
	type CatalogEntry,
	type DiscoveryResult,
	type ImporterInstance
} from '#lib/api/index.js';
import { accounts as accountDialog } from '#lib/accounts/controller.svelte.js';
import { addAndLinkOptions, canRefreshAccounts, type RowState } from '#lib/importers/discovery.js';
import { LinkAccountFlow } from '#lib/importers/link-flow.svelte.js';
import { describeImporterError, doneText } from '#lib/importers/messages.js';
import { discoveryUrl } from '#lib/importers/links.js';
import { SETTLE_STALE } from '#lib/ledger/errors.js';
import type { DiscoveryEntry } from '#lib/types/domain.js';
import { refusalText, isBusyRefusal } from '#lib/sync/entry.js';
import { narrowedPlanUrl } from '#lib/sync/plan.js';
import { lookupsStore } from './lookups.svelte.js';
import { sync } from './sync.svelte.js';

export type DiscoveryNotice = {
	text: string;
	error: boolean;
	/** "Fetch", "Open the running task": where it goes */
	action?: { label: string; path: string };
};

/** What the page shows: nothing started, looking, the account list (or why not), or lost. */
export type DiscoveryPhase = 'none' | 'running' | 'ended' | 'interrupted';

export class DiscoveryStore {
	readonly instanceId: number;
	instance = $state.raw<ImporterInstance | null>(null);
	catalog = $state.raw<CatalogEntry[]>([]);
	loadStatus = $state<'loading' | 'ready' | 'missing' | 'error'>('loading');
	/** the account list, read from the ended task's status */
	result = $state.raw<DiscoveryResult | null>(null);
	resultStatus = $state<'idle' | 'loading' | 'ready' | 'lost' | 'error'>('idle');
	notice = $state.raw<DiscoveryNotice | null>(null);
	/** an account was linked on this page: the notice offers "Fetch" */
	linkedHere = $state(false);
	starting = $state(false);
	/** references whose add-and-link is under way */
	busyRefs = $state.raw<readonly string[]>([]);

	readonly link = new LinkAccountFlow({
		linked: (instance, accountId, settleFailed) =>
			void this.#linked(instance, accountId, settleFailed),
		gone: () => {
			this.loadStatus = 'missing';
		}
	});

	#generation = 0;
	#readTask: string | null = null;

	constructor(instanceId: number) {
		this.instanceId = instanceId;
	}

	/** whether this page hosts the store's task: a discovery of this instance */
	get hosted(): boolean {
		if (sync.status === 'idle' || sync.kind !== 'discovery') return false;
		if (sync.homePath === discoveryUrl(this.instanceId)) return true;
		// reattaching after a reload: the first event says which instance it is
		return sync.status === 'attaching' && sync.view.instances.length === 0;
	}

	get phase(): DiscoveryPhase {
		if (!this.hosted) return 'none';
		switch (sync.status) {
			case 'attaching':
			case 'running':
				return 'running';
			case 'ended':
				return 'ended';
			default:
				return 'interrupted';
		}
	}

	/** the failure of the login, once the task has ended in one */
	get failure() {
		return sync.view.instances.find((i) => i.instanceId === this.instanceId)?.failure ?? null;
	}

	/** "Refresh accounts" is offered for this instance (a fetch importer that emits transactions) */
	get refreshable(): boolean {
		return this.instance !== null && canRefreshAccounts(this.instance, this.catalog);
	}

	async init(): Promise<void> {
		const generation = ++this.#generation;
		void lookupsStore.ensure();
		this.loadStatus = 'loading';
		try {
			const [instances, catalog] = await Promise.all([listInstances(), listImporters()]);
			if (generation !== this.#generation) return;
			this.catalog = catalog;
			this.instance = instances.find((i) => i.id === this.instanceId) ?? null;
			this.loadStatus = this.instance ? 'ready' : 'missing';
		} catch {
			if (generation !== this.#generation) return;
			this.loadStatus = 'error';
		}
	}

	/** Start the discovery (again): a refusal is a notice here, a busy one links to the running task. */
	async refresh(): Promise<void> {
		this.starting = true;
		this.notice = null;
		const refusal = await sync.startDiscovery(this.instanceId);
		this.starting = false;
		if (!refusal) {
			this.result = null;
			this.resultStatus = 'idle';
			this.#readTask = null;
			return;
		}
		this.notice = isBusyRefusal(refusal)
			? {
					text: refusalText(refusal),
					error: false,
					action: {
						label: 'Open the running task',
						path: sync.status === 'idle' ? '/sync' : sync.homePath
					}
				}
			: { text: refusalText(refusal), error: true };
	}

	/**
	 * Read the result of the ended task. `again` reads it afresh (after a link: the server answers
	 * with each row as it now stands); a task read once is not read again by a re-render.
	 */
	async read(again = false): Promise<void> {
		const taskId = sync.taskId;
		if (!taskId || this.phase !== 'ended') return;
		if (!again && this.#readTask === taskId) return;
		this.#readTask = taskId;
		const generation = this.#generation;
		if (this.result === null) this.resultStatus = 'loading';
		try {
			const status = await getTaskStatus(taskId);
			if (generation !== this.#generation || taskId !== sync.taskId) return;
			this.result = status.result;
			this.resultStatus = status.result ? 'ready' : 'idle';
		} catch (error) {
			if (generation !== this.#generation || taskId !== sync.taskId) return;
			const failure = classifyImporterError(error);
			if (failure.kind === 'not_found') {
				this.result = null;
				this.resultStatus = 'lost';
			} else if (this.result === null) this.resultStatus = 'error';
		}
	}

	/** "Link…": the link dialog with the account fixed and the discovered reference sent. */
	openLink(entry: DiscoveryEntry, state: Extract<RowState, { kind: 'match' }>): void {
		const instance = this.instance;
		if (!instance) return;
		this.link.start(instance, {
			accountId: state.accountId,
			name:
				lookupsStore.lookups.accounts.get(state.accountId)?.name ?? `Account #${state.accountId}`,
			externalRef: entry.account.external_ref
		});
	}

	/** "Add and link": the add dialog, prefilled; once the account exists it is linked at once. */
	openAddAndLink(entry: DiscoveryEntry): void {
		accountDialog.openAdd(
			addAndLinkOptions(entry, (account) => void this.#linkNew(entry, account.id, account.name))
		);
	}

	async #linkNew(entry: DiscoveryEntry, accountId: number, name: string): Promise<void> {
		const instance = this.instance;
		if (!instance) return;
		const ref = entry.account.external_ref;
		this.busyRefs = [...this.busyRefs, ref];
		this.notice = null;
		try {
			const out = await linkAccount(instance.id, accountId, { externalRef: ref });
			await this.#linked(
				{
					...instance,
					accounts: [
						...instance.accounts.filter((a) => a.account_id !== accountId),
						{ account_id: accountId, external_ref: out.external_ref }
					]
				},
				accountId,
				!!out.settle?.error,
				name
			);
		} catch (error) {
			// the account exists; the row recomputes on the next read and offers "Link…"
			this.notice = {
				text: `${name} was added, but linking it failed: ${describeImporterError(classifyImporterError(error))}`,
				error: true
			};
			await this.read(true);
		} finally {
			this.busyRefs = this.busyRefs.filter((r) => r !== ref);
		}
	}

	async #linked(
		instance: ImporterInstance,
		accountId: number,
		settleFailed: boolean,
		name?: string
	): Promise<void> {
		this.instance = instance;
		this.linkedHere = true;
		const account =
			name ?? lookupsStore.lookups.accounts.get(accountId)?.name ?? `Account #${accountId}`;
		const text = doneText({ action: 'linked', label: instance.label, account });
		this.notice = {
			text: settleFailed ? `${text} ${SETTLE_STALE}` : text,
			error: false,
			action: { label: 'Fetch', path: narrowedPlanUrl(instance.id) }
		};
		// the account is synced now: its facts changed
		void lookupsStore.reload();
		await this.read(true);
	}

	dispose(): void {
		this.#generation++;
		this.link.close();
	}
}
