// State of the ledger list page: the filter, the page of entries held, the lookups the rows
// resolve ids against. The list is a SNAPSHOT (patterns §7): a changed filter refetches, nothing
// refreshes by itself, and "load more" appends. Page-scoped: the page creates one and drops it.
// No domain computation here: what a row shows comes from the API.

import {
	ApiError,
	createTag,
	DEFAULT_PAGE_SIZE,
	listEntries,
	tagEntry,
	untagEntry
} from '#lib/api/index.js';
import { todayIso } from '#lib/format/index.js';
import { describeFilter } from '#lib/ledger/describe.js';
import {
	describeTagError,
	SETTLE_STALE,
	tagErrorEffects,
	type TagErrorScope
} from '#lib/ledger/errors.js';
import {
	emptyFilter,
	filterKey,
	isEmpty,
	normalizeFilter,
	type LedgerFilterState
} from '#lib/ledger/filter.js';
import {
	idsOf,
	mergeRefreshed,
	NO_IDS,
	nextMoved,
	patchTagIds,
	rowsOutOfTagFilter,
	tagChangedIds,
	withIds
} from '#lib/ledger/patch.js';
import type { Lookups } from '#lib/ledger/lookups.js';
import type { Entry, EntryTagIds, Tag } from '#lib/types/domain.js';
import { applyAffected, clearMarks, noMarks, type Marks } from '#lib/units/patch.js';
import type { Affected } from '#lib/units/types.js';
import { lookupsStore, type LookupsStore } from './lookups.svelte.js';
import { NewDataWatch } from './new-data.svelte.js';
import { session } from './session.svelte.js';
import { TagAllFlow } from './tag-all.svelte.js';

/** the most rows one list request may ask for */
const REFRESH_PAGE = 500;

export type LedgerStatus = 'loading' | 'ready' | 'error';

/** A quiet one-line message about what the last action did (patterns §8). */
export type LedgerNotice = { text: string; error: boolean };

function asApiError(error: unknown): ApiError {
	return error instanceof ApiError
		? error
		: new ApiError(0, 'network_error', 'The server could not be reached.');
}

export class LedgerStore {
	filter = $state.raw<LedgerFilterState>(emptyFilter());
	entries = $state.raw<Entry[]>([]);
	/** every entry matching the filter, whatever the page */
	total = $state(0);
	status = $state<LedgerStatus>('loading');
	/** why the first page failed (status `error`) */
	error = $state.raw<ApiError | null>(null);
	loadingMore = $state(false);
	/** why "load more" failed; the entries held stay */
	moreError = $state.raw<ApiError | null>(null);

	readonly #lookups: LookupsStore;
	/** the shared lists rows resolve ids against (stores/lookups.svelte.ts) */
	get lookups(): Lookups {
		return this.#lookups.lookups;
	}
	/** the lists that could not be loaded (their names), shown as a quiet notice */
	get lookupsFailed(): string[] {
		return this.#lookups.failed;
	}

	constructor(lookups: LookupsStore = lookupsStore) {
		this.#lookups = lookups;
	}

	readonly locale = $derived(session.config?.locale ?? 'en');
	readonly baseCurrency = $derived(session.config?.base_currency ?? 'EUR');
	readonly today = $derived(todayIso(session.config?.timezone ?? 'UTC'));
	/** the active filters in words, for the empty state */
	readonly activeFilters = $derived(
		describeFilter(this.filter, { lookups: this.lookups, locale: this.locale }).map((p) => p.label)
	);

	/** what the last tag action said; cleared by the next one and by a reload */
	notice = $state.raw<LedgerNotice | null>(null);
	/** entries whose tags were changed here since the list was fetched */
	touchedIds = $state.raw<ReadonlySet<number>>(NO_IDS);

	/** what the unit panel's actions did to the rows held (resolved, consequence, deleted, returned) */
	marks = $state.raw<Marks>(noMarks());

	/** rows a refresh in place did not return: kept and marked, never removed (patterns §7, §8) */
	movedIds = $state.raw<ReadonlySet<number>>(NO_IDS);

	/**
	 * Rows the user's tag action took out of an active tag filter. They stay where they are,
	 * marked "changed by your last action", until the list is refreshed (decision C10).
	 */
	readonly changedIds = $derived(
		rowsOutOfTagFilter(this.entries, this.touchedIds, this.filter.tag_id)
	);

	/** Why "Tag all N…" is not available, or null when it is. */
	readonly tagAllReason = $derived.by(() => {
		if (this.status !== 'ready') return 'The list is still loading';
		if (isEmpty(this.filter)) return 'Narrow the filter first';
		if (this.total === 0) return 'No entries to tag';
		return null;
	});

	readonly tagAll = new TagAllFlow({
		filter: () => this.filter,
		locale: () => this.locale,
		addTag: (tag) => this.addTag(tag),
		markedRows: () => this.entries.filter((e) => this.changedIds.has(e.id)),
		recover: (error, scope) => this.recover(error, scope),
		patch: (updates) => this.patchTags(updates),
		applied: (updates, text) => {
			this.patchTags(updates);
			this.notify(text);
		}
	});

	/** rows from a sync that arrived since the list was fetched: the one quiet notice (patterns §7) */
	readonly news = new NewDataWatch();

	#controller: AbortController | null = null;
	#refreshController: AbortController | null = null;
	#generation = 0;
	#key: string | null = null;

	/** Show this filter. The same filter as the one held does nothing (a URL echo). */
	applyFilter(next: LedgerFilterState): void {
		const filter = normalizeFilter(next);
		const key = filterKey(filter);
		if (key === this.#key) return;
		this.#key = key;
		this.filter = filter;
		void this.reload();
	}

	/** Fetch the first page again for the current filter. */
	async reload(): Promise<void> {
		this.#controller?.abort();
		this.#refreshController?.abort();
		const controller = new AbortController();
		this.#controller = controller;
		const generation = ++this.#generation;
		this.news.take();
		this.status = 'loading';
		this.error = null;
		this.moreError = null;
		this.loadingMore = false;
		this.entries = [];
		this.total = 0;
		this.touchedIds = NO_IDS;
		this.movedIds = NO_IDS;
		this.marks = noMarks();
		this.notice = null;
		try {
			const page = await listEntries(this.filter, {
				limit: DEFAULT_PAGE_SIZE,
				offset: 0,
				signal: controller.signal
			});
			if (generation !== this.#generation) return;
			this.entries = page.entries;
			this.total = page.total;
			this.status = 'ready';
		} catch (error) {
			if (generation !== this.#generation) return; // superseded by a newer fetch
			this.error = asApiError(error);
			this.status = 'error';
		}
	}

	/** Append the next page (offset += entries held). */
	async loadMore(): Promise<void> {
		if (this.status !== 'ready' || this.loadingMore || this.entries.length >= this.total) return;
		const controller = new AbortController();
		this.#controller = controller;
		const generation = this.#generation;
		this.loadingMore = true;
		this.moreError = null;
		try {
			const page = await listEntries(this.filter, {
				limit: DEFAULT_PAGE_SIZE,
				offset: this.entries.length,
				signal: controller.signal
			});
			if (generation !== this.#generation) return;
			this.entries = [...this.entries, ...page.entries];
			this.total = page.total;
		} catch (error) {
			if (generation !== this.#generation) return;
			this.moreError = asApiError(error);
		} finally {
			if (generation === this.#generation) this.loadingMore = false;
		}
	}

	/**
	 * Refetch the window already loaded for the current filter and merge it into the rows held, in
	 * place (patterns §7, §8): fresh rows replace held ones by id, held rows the answer lacks stay
	 * and are marked, rows not held are not added, the order never changes.
	 */
	async refreshInPlace(): Promise<void> {
		if (this.status !== 'ready' || this.entries.length === 0) return;
		this.#refreshController?.abort();
		const controller = new AbortController();
		this.#refreshController = controller;
		const generation = this.#generation;
		const filter = this.filter;
		const held = idsOf(this.entries);
		const wanted = this.entries.length;
		try {
			const fresh: Entry[] = [];
			let total = this.total;
			while (fresh.length < wanted) {
				const limit = Math.min(REFRESH_PAGE, wanted - fresh.length);
				const page = await listEntries(filter, {
					limit,
					offset: fresh.length,
					signal: controller.signal
				});
				if (generation !== this.#generation || controller.signal.aborted) return;
				fresh.push(...page.entries);
				total = page.total;
				if (page.entries.length < limit) break;
			}
			const merged = mergeRefreshed(this.entries, fresh, held);
			this.entries = merged.entries;
			this.total = total;
			this.movedIds = nextMoved(this.movedIds, fresh, merged.missing);
		} catch {
			if (generation !== this.#generation || controller.signal.aborted) return;
			this.notify('The list could not be refreshed in place; its rows may be out of date.', true);
		}
	}

	/** Load the tag list again (a tag was created or deleted elsewhere). */
	async reloadTags(): Promise<void> {
		await this.#lookups.reloadTags();
	}

	/** After a failed tag write: refetch what moved, as `tagErrorEffects` says. Never a retry. */
	async recover(error: ApiError, scope: TagErrorScope): Promise<void> {
		const effects = tagErrorEffects(error, scope);
		await Promise.all([
			effects.rows ? this.refreshInPlace() : undefined,
			effects.tags ? this.reloadTags() : undefined
		]);
	}

	/** Load the lists rows resolve ids against, once (shared with every other screen). */
	loadLookups(): Promise<void> {
		return this.#lookups.ensure();
	}

	notify(text: string, error = false): void {
		this.notice = { text, error };
	}

	/** A tag created here joins the list the rows and pickers resolve against. */
	addTag(tag: Tag): void {
		this.#lookups.addTag(tag);
	}

	/** Patch tag ids into the rows held, in place: never added, removed or reordered (§7). */
	patchTags(updates: readonly EntryTagIds[]): void {
		if (updates.length === 0) return;
		this.entries = patchTagIds(this.entries, updates);
		this.touchedIds = withIds(
			this.touchedIds,
			updates.map((u) => u.id)
		);
	}

	/** An action in the unit panel touched these entries: patch the rows held, in place (§7). */
	patchAffected(affected: Affected): void {
		// rows whose tags the commit changed are as touched as by the row's own tag action: under an
		// active tag filter they stay, marked, until the list is refreshed (decision C10)
		const retagged = tagChangedIds(this.entries, affected.entries);
		if (retagged.length > 0) this.touchedIds = withIds(this.touchedIds, retagged);
		const out = applyAffected(this.entries, affected, this.marks);
		this.entries = out.entries;
		this.marks = out.marks;
	}

	/** The cursor visited these entries: their marks fade (patterns §7). */
	visited(entryIds: readonly number[]): void {
		let next = this.marks;
		for (const id of entryIds) next = clearMarks(next, id);
		if (next !== this.marks) this.marks = next;
	}

	/** Tag (`tagged`) or untag one entry; the row follows the answer. True when it worked. */
	async setEntryTag(entryId: number, tagId: number, tagged: boolean): Promise<boolean> {
		this.notice = null;
		try {
			const out = tagged ? await tagEntry(entryId, tagId) : await untagEntry(entryId, tagId);
			this.patchTags([out.entry]);
			if (out.settle.error) this.notify(`Saved. ${SETTLE_STALE}`);
			return true;
		} catch (error) {
			const failure = asApiError(error);
			this.notify(describeTagError(failure), true);
			await this.recover(failure, 'entry');
			return false;
		}
	}

	/** Create a tag and put it on one entry. True when both worked. */
	async createTagFor(entryId: number, name: string): Promise<boolean> {
		this.notice = null;
		let tag: Tag;
		try {
			tag = (await createTag(name)).tag;
		} catch (error) {
			const failure = asApiError(error);
			this.notify(describeTagError(failure, 'entry', name), true);
			await this.recover(failure, 'entry');
			return false;
		}
		this.addTag(tag);
		return this.setEntryTag(entryId, tag.id, true);
	}

	/** The page is going away: nothing more may land in the store. */
	dispose(): void {
		this.#generation++;
		this.#controller?.abort();
		this.#controller = null;
		this.#refreshController?.abort();
		this.#refreshController = null;
		this.tagAll.close();
	}
}
