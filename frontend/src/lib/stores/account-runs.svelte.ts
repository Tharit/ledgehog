// What the account page reads from the importers (ux/views/account.md): the instances the account is
// linked to ("the sources", architecture §4.1: filtered here from the instances list, not a route
// of their own) and its runs, the import log. Page-scoped, like the page store that refreshes it
// after the page's own writes.
import {
	DEFAULT_PAGE_SIZE,
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
	/** every run the account has, whatever the page */
	total = $state(0);
	runsStatus = $state<PartStatus>('loading');
	loadingMore = $state(false);
	/** the last "load more" failed: the runs held stay */
	moreFailed = $state(false);
	instances = $state.raw<ImporterInstance[]>([]);
	catalog = $state.raw<CatalogEntry[]>([]);
	sourcesStatus = $state<PartStatus>('loading');

	readonly sources = $derived<SourceLine[]>(
		this.accountId === null ? [] : sourceLines(this.accountId, this.instances, this.catalog)
	);

	#generation = 0;

	async load(accountId: number): Promise<void> {
		this.accountId = accountId;
		this.runs = [];
		this.total = 0;
		this.loadingMore = false;
		this.moreFailed = false;
		this.runsStatus = 'loading';
		this.sourcesStatus = 'loading';
		const generation = ++this.#generation;
		await Promise.all([this.#loadRuns(accountId, generation), this.#loadSources(generation)]);
	}

	/** The first page of runs again (after a revert, an upload elsewhere, a mark): the instances stay. */
	async reload(): Promise<void> {
		const accountId = this.accountId;
		if (accountId === null) return;
		const generation = this.#generation;
		try {
			const page = await listRuns({ accountId, limit: DEFAULT_PAGE_SIZE });
			if (generation !== this.#generation) return;
			this.runs = page.runs;
			this.total = page.total;
			this.moreFailed = false;
			this.runsStatus = 'ready';
		} catch {
			// the runs held stay
		}
	}

	/** Append the next page (offset = runs held). */
	async loadMore(): Promise<void> {
		const accountId = this.accountId;
		if (accountId === null || this.runsStatus !== 'ready' || this.loadingMore) return;
		if (this.runs.length >= this.total) return;
		const generation = this.#generation;
		this.loadingMore = true;
		this.moreFailed = false;
		try {
			const page = await listRuns({
				accountId,
				limit: DEFAULT_PAGE_SIZE,
				offset: this.runs.length
			});
			if (generation !== this.#generation) return;
			this.runs = [...this.runs, ...page.runs];
			this.total = page.total;
		} catch {
			if (generation !== this.#generation) return;
			this.moreFailed = true;
		} finally {
			if (generation === this.#generation) this.loadingMore = false;
		}
	}

	async #loadRuns(accountId: number, generation: number): Promise<void> {
		try {
			const page = await listRuns({ accountId, limit: DEFAULT_PAGE_SIZE });
			if (generation !== this.#generation) return;
			this.runs = page.runs;
			this.total = page.total;
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

	/** What the importer a run came from is (the catalog says); one it does not list has no next step. */
	importerKind = (run: ImportRun): 'file' | 'fetch' | null => {
		const kind = this.catalog.find((entry) => entry.name === run.importer)?.kind;
		return kind === 'file' || kind === 'fetch' ? kind : null;
	};

	dispose(): void {
		this.#generation++;
	}
}
