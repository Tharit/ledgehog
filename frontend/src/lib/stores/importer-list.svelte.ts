// State of the importer list page (ux/views/importers.md): the instances, the catalog (it says which
// can be reset and what Add importer offers) and the accounts they link to. Page-scoped; every
// write patches the list in place (patterns §7).
import {
	classifyImporterError,
	listImporters,
	listInstances,
	updateInstance,
	type CatalogEntry,
	type ImporterError,
	type ImporterInstance
} from '#lib/api/importers.js';
import { SETTLE_STALE } from '#lib/ledger/errors.js';
import type { Lookups } from '#lib/ledger/lookups.js';
import { InstanceDecisionFlow, type DecisionKind } from '#lib/importers/decision-flow.svelte.js';
import { describeImporterError, doneText, type ImporterDone } from '#lib/importers/messages.js';
import { lookupsStore } from './lookups.svelte.js';
import { session } from './session.svelte.js';

export type ImporterListStatus = 'loading' | 'ready' | 'error';

export class ImporterListStore {
	status = $state<ImporterListStatus>('loading');
	error = $state.raw<ImporterError | null>(null);
	instances = $state.raw<ImporterInstance[]>([]);
	catalog = $state.raw<CatalogEntry[]>([]);
	/** what the last write said, or why it failed */
	notice = $state<{ text: string; error: boolean } | null>(null);
	/** the instances whose Disable or Enable is running */
	busy = $state.raw<number[]>([]);

	readonly locale = $derived(session.config?.locale ?? 'en');
	readonly timeZone = $derived(session.config?.timezone ?? 'UTC');
	/** the account names the rows link to */
	readonly lookups = $derived<Lookups>(lookupsStore.lookups);

	readonly decision = new InstanceDecisionFlow({
		done: (kind, instance, now, accountId, settleFailed) =>
			this.#decided(kind, instance, now, accountId, settleFailed),
		gone: (_kind, instance) => {
			this.instances = this.instances.filter((i) => i.id !== instance.id);
			this.notice = { text: `Importer “${instance.label}” no longer exists.`, error: false };
		}
	});

	#generation = 0;

	say(done: ImporterDone, settleFailed = false): void {
		const text = doneText(done);
		this.notice = { text: settleFailed ? `${text} ${SETTLE_STALE}` : text, error: false };
	}

	async load(): Promise<void> {
		const generation = ++this.#generation;
		this.status = 'loading';
		this.error = null;
		void lookupsStore.ensure();
		const [instances, catalog] = await Promise.allSettled([listInstances(), listImporters()]);
		if (generation !== this.#generation) return;
		if (instances.status === 'rejected') {
			this.error = classifyImporterError(instances.reason);
			this.status = 'error';
			return;
		}
		this.instances = instances.value;
		// without the catalog nothing offers Reset…; the list itself stands
		this.catalog = catalog.status === 'fulfilled' ? catalog.value : [];
		this.status = 'ready';
	}

	#replace(instance: ImporterInstance): void {
		this.instances = this.instances.map((i) => (i.id === instance.id ? instance : i));
	}

	/** Disable or Enable: a plain direct write, so the list shows it and says nothing; a failure is a notice. */
	async setDisabled(instance: ImporterInstance, disabled: boolean): Promise<void> {
		if (this.busy.includes(instance.id)) return;
		this.busy = [...this.busy, instance.id];
		this.notice = null;
		try {
			this.#replace(await updateInstance(instance.id, { disabled }));
		} catch (error) {
			const failure = classifyImporterError(error);
			this.notice = { text: describeImporterError(failure), error: true };
			if (failure.kind === 'not_found') {
				this.instances = this.instances.filter((i) => i.id !== instance.id);
			}
		} finally {
			this.busy = this.busy.filter((id) => id !== instance.id);
		}
	}

	#decided(
		kind: DecisionKind,
		instance: ImporterInstance,
		now: ImporterInstance | null,
		accountId: number | null,
		settleFailed: boolean
	): void {
		if (kind === 'delete') {
			this.instances = this.instances.filter((i) => i.id !== instance.id);
			this.say({ action: 'deleted', label: instance.label }, settleFailed);
			// its links went with it: those accounts are no longer synced by it
			void lookupsStore.reload();
			return;
		}
		if (now) this.#replace(now);
		if (kind === 'reset') {
			this.notice = {
				text: `Importer “${instance.label}” was reset: its state is cleared, its settings stay.`,
				error: false
			};
		} else if (accountId !== null) {
			const account = this.lookups.accounts.get(accountId)?.name ?? 'The account';
			this.say({ action: 'unlinked', label: instance.label, account }, settleFailed);
		}
	}

	dispose(): void {
		this.#generation++;
		this.decision.close();
	}
}
