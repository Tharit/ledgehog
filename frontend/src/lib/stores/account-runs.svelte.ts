// What the account page reads from the importers (ux/views/account.md): the instances the account is
// linked to ("the sources", architecture §4.1: filtered here from the instances list, not a route
// of their own) and its runs, the import log. Page-scoped, like the page store that refreshes it
// after the page's own writes.
import {
	listImporters,
	listInstances,
	listRuns,
	type CatalogEntry,
	type ImportRun,
	type ImporterInstance
} from '#lib/api/index.js';
import { sourceLines, type SourceLine } from '#lib/accounts/sources.js';

export type PartStatus = 'loading' | 'ready' | 'error';

export class AccountRunsStore {
	accountId = $state<number | null>(null);
	runs = $state.raw<ImportRun[]>([]);
	runsStatus = $state<PartStatus>('loading');
	showAll = $state(false);
	instances = $state.raw<ImporterInstance[]>([]);
	catalog = $state.raw<CatalogEntry[]>([]);
	sourcesStatus = $state<PartStatus>('loading');

	readonly sources = $derived<SourceLine[]>(
		this.accountId === null ? [] : sourceLines(this.accountId, this.instances, this.catalog)
	);

	#generation = 0;

	async load(accountId: number): Promise<void> {
		this.accountId = accountId;
		this.showAll = false;
		this.runs = [];
		this.runsStatus = 'loading';
		this.sourcesStatus = 'loading';
		const generation = ++this.#generation;
		await Promise.all([this.#loadRuns(accountId, generation), this.#loadSources(generation)]);
	}

	/** The runs again (after a revert, an upload elsewhere, a mark): the instances stay. */
	async reload(): Promise<void> {
		const accountId = this.accountId;
		if (accountId === null) return;
		const generation = this.#generation;
		try {
			const runs = await listRuns({ accountId, limit: 100 });
			if (generation !== this.#generation) return;
			this.runs = runs;
			this.runsStatus = 'ready';
		} catch {
			// the runs held stay
		}
	}

	async #loadRuns(accountId: number, generation: number): Promise<void> {
		try {
			const runs = await listRuns({ accountId, limit: 100 });
			if (generation !== this.#generation) return;
			this.runs = runs;
			this.runsStatus = 'ready';
		} catch {
			if (generation !== this.#generation) return;
			this.runsStatus = 'error';
		}
	}

	async #loadSources(generation: number): Promise<void> {
		try {
			const [instances, catalog] = await Promise.all([listInstances(), listImporters()]);
			if (generation !== this.#generation) return;
			this.instances = instances;
			this.catalog = catalog;
			this.sourcesStatus = 'ready';
		} catch {
			if (generation !== this.#generation) return;
			this.sourcesStatus = 'error';
		}
	}

	/** The label of the instance a run came from; a deleted instance's runs say so. */
	instanceLabel = (run: ImportRun): string =>
		this.instances.find((i) => i.id === run.instance_id)?.label ??
		(run.instance_id === null ? 'Deleted importer' : run.importer);

	dispose(): void {
		this.#generation++;
	}
}
