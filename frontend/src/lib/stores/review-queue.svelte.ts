// State of the review page: the queue as fetched (a SNAPSHOT, patterns §7, architecture §6.5),
// its three sections with their cursors, and the passive count of units that arrived since. The
// queue never adds or reorders rows by itself: a refresh happens on request ("N new — refresh").
// It registers as the `UnitSource` of the panel, so `[` and `]` step through units in queue order.
// Page-scoped: the page creates one and drops it. No domain computation here.

import { ApiError, getNewUnitCount, getQueue } from '#lib/api/index.js';
import { clearMarks, applyAffected, noMarks, type Marks } from '#lib/units/patch.js';
import { ruleNames } from './rule-names.svelte.js';
import type { StepDirection, UnitSource } from '#lib/units/sources.js';
import { SECTION_ORDER, type Affected, type SectionKind, type Unit } from '#lib/units/types.js';
import { unitReadsRules } from '#lib/units/panel.svelte.js';
import { appendUnits, insertUnitEntries, patchUnitEntries } from '#lib/units/queue.js';

export type QueueStatus = 'loading' | 'ready' | 'error';

export type SectionState = {
	kind: SectionKind;
	/** units in the section, whatever the page */
	total: number;
	units: Unit[];
	nextCursor: string | null;
	loadingMore: boolean;
	moreError: ApiError | null;
};

function asApiError(error: unknown): ApiError {
	return error instanceof ApiError
		? error
		: new ApiError(0, 'network_error', 'The server could not be reached.');
}

function emptySections(): SectionState[] {
	return SECTION_ORDER.map((kind) => ({
		kind,
		total: 0,
		units: [],
		nextCursor: null,
		loadingMore: false,
		moreError: null
	}));
}

export class ReviewQueueStore {
	sections = $state.raw<SectionState[]>(emptySections());
	status = $state<QueueStatus>('loading');
	error = $state.raw<ApiError | null>(null);
	/** units that arrived since the snapshot (a passive count) */
	newCount = $state(0);
	/** what the unit panel's actions did to the rows held */
	marks = $state.raw<Marks>(noMarks());

	/** a quiet line the panel leaves behind ("Review done"); cleared by a reload */
	notice = $state<string | null>(null);

	/** the unit (anchor id) the panel shows: the page puts its cursor there */
	revealed = $state<number | null>(null);

	readonly total = $derived(this.sections.reduce((sum, s) => sum + s.total, 0));
	/** the loaded units in queue order, across the sections */
	readonly units = $derived(this.sections.flatMap((s) => s.units));

	#snapshot: string | null = null;
	#generation = 0;
	#controller: AbortController | null = null;
	#countController: AbortController | null = null;

	/** What the panel steps through: the loaded units in queue order, "12 of 214" by position. */
	readonly source: UnitSource = {
		neighbour: (id, dir) => this.neighbour(id, dir),
		patch: (affected) => this.patchAffected(affected),
		notice: (text) => (this.notice = text),
		finishedText: 'Review done',
		// the end of a page is not the end of the queue: the panel carries on after loading more
		loadMore: async () => {
			const next = this.sections.find((s) => s.nextCursor !== null);
			if (!next) return false;
			const before = this.units.length;
			await this.loadMore(next.kind);
			return this.units.length > before;
		},
		reveal: (id) => {
			const at = this.#indexOf(id);
			if (at < 0) return false;
			this.revealed = this.units[at].anchor_entry_id;
			return true;
		},
		position: (id) => {
			const at = this.#indexOf(id);
			return at < 0 ? null : { index: at + 1, total: this.total };
		}
	};

	#indexOf(entryId: number): number {
		return this.units.findIndex((u) => u.entries.some((e) => e.id === entryId));
	}

	/** The anchor of the unit before (-1) or after (1) the unit holding `entryId`, or null. */
	neighbour(entryId: number, dir: StepDirection): number | null {
		const at = this.#indexOf(entryId);
		if (at < 0) return null;
		return this.units[at + dir]?.anchor_entry_id ?? null;
	}

	/** Fetch the first page of every section (the first load, and a refresh on request). */
	async load(): Promise<void> {
		this.#controller?.abort();
		const controller = new AbortController();
		this.#controller = controller;
		const generation = ++this.#generation;
		this.status = 'loading';
		this.error = null;
		try {
			const queue = await getQueue({ signal: controller.signal });
			if (generation !== this.#generation) return;
			this.sections = SECTION_ORDER.map((kind) => {
				const found = queue.sections.find((s) => s.kind === kind);
				return {
					kind,
					total: found?.total ?? 0,
					units: found?.units ?? [],
					nextCursor: found?.next_cursor ?? null,
					loadingMore: false,
					moreError: null
				};
			});
			this.#snapshot = queue.snapshot;
			this.newCount = 0;
			this.notice = null;
			this.marks = noMarks();
			this.status = 'ready';
			if (this.units.some(unitReadsRules)) void ruleNames.ensure();
		} catch (error) {
			if (generation !== this.#generation) return;
			this.error = asApiError(error);
			// a refresh that fails keeps the queue held
			this.status = this.units.length > 0 ? 'ready' : 'error';
		}
	}

	/** Append the next page of one section (a keyset cursor, never an offset). */
	async loadMore(kind: SectionKind): Promise<void> {
		const section = this.sections.find((s) => s.kind === kind);
		if (!section || section.nextCursor === null || section.loadingMore) return;
		const generation = this.#generation;
		this.#update(kind, { loadingMore: true, moreError: null });
		try {
			const page = await getQueue({ section: kind, cursor: section.nextCursor });
			if (generation !== this.#generation) return;
			const found = page.sections.find((s) => s.kind === kind);
			// the section as it is NOW (an action may have patched its rows meanwhile)
			const now = this.sections.find((s) => s.kind === kind) ?? section;
			this.#update(kind, {
				units: appendUnits(now.units, found?.units ?? []),
				total: found?.total ?? section.total,
				nextCursor: found?.next_cursor ?? null,
				loadingMore: false
			});
			if ((found?.units ?? []).some(unitReadsRules)) void ruleNames.ensure();
		} catch (error) {
			if (generation !== this.#generation) return;
			this.#update(kind, { loadingMore: false, moreError: asApiError(error) });
		}
	}

	/** How many units arrived since the snapshot: one cheap request, a passive count (§7). */
	async checkNew(): Promise<void> {
		const snapshot = this.#snapshot;
		if (snapshot === null || this.status !== 'ready') return;
		this.#countController?.abort();
		const controller = new AbortController();
		this.#countController = controller;
		const generation = this.#generation;
		try {
			const out = await getNewUnitCount(snapshot, controller.signal);
			if (generation !== this.#generation) return;
			this.newCount = out.new_count;
		} catch {
			// a count that cannot be had is no news
		}
	}

	/** An action touched these entries: patch the units held, in place; nothing is added or moved. */
	patchAffected(affected: Affected): void {
		// the one exception: the entries a split created join the unit of their anchor
		const sections = this.sections.map((section) => ({
			...section,
			units: insertUnitEntries(section.units, affected)
		}));
		const flat = sections.flatMap((s) => s.units).flatMap((u) => u.entries);
		const out = applyAffected(flat, affected, this.marks);
		this.sections = sections.map((section) => ({
			...section,
			units: patchUnitEntries(section.units, out.entries)
		}));
		this.marks = out.marks;
	}

	/** The cursor visited these entries: their marks fade. */
	visited(entryIds: readonly number[]): void {
		let next = this.marks;
		for (const id of entryIds) next = clearMarks(next, id);
		this.marks = next;
	}

	#update(kind: SectionKind, change: Partial<SectionState>): void {
		this.sections = this.sections.map((s) => (s.kind === kind ? { ...s, ...change } : s));
	}

	dispose(): void {
		this.#generation++;
		this.#controller?.abort();
		this.#countController?.abort();
	}
}
