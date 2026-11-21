// State of the review page: the queue as fetched (a SNAPSHOT, patterns §7, architecture §6.5),
// and its three sections with their cursors. The queue never adds or reorders rows by itself: a
// refresh happens on request ("New data — Refresh").
// It registers as the `UnitSource` of the panel, so `[` and `]` step through units in queue order.
// Page-scoped: the page creates one and drops it. No domain computation here.

import { ApiError, getQueue } from '#lib/api/index.js';
import { clearMarks, applyAffected, markChanged, noMarks, type Marks } from '#lib/units/patch.js';
import { commitAsSeen, type SeenOptions } from '#lib/units/commit-seen.js';
import { selectionReason } from '#lib/units/selection.js';
import { affectedOf } from '#lib/units/unit-draft-flow.svelte.js';
import { NewDataWatch } from './new-data.svelte.js';
import { ruleNames } from './rule-names.svelte.js';
import type { StepDirection, UnitSource } from '#lib/units/sources.js';
import {
	SECTION_ORDER,
	type Affected,
	type CounterpartyGroup,
	type QueueAccountGroup,
	type QueueGroup,
	type SectionKind,
	type Unit
} from '#lib/units/types.js';
import { DEFAULT_CUT, type QueueCut } from '#lib/units/queue-cut.js';
import { unitReadsRules } from '#lib/units/panel.svelte.js';
import {
	appendUnits,
	insertUnitEntries,
	groupKeys,
	orderByGroups,
	patchUnitEntries
} from '#lib/units/queue.js';

export type QueueStatus = 'loading' | 'ready' | 'error';

export type SectionState = {
	kind: SectionKind;
	/** units in the section, whatever the page */
	total: number;
	units: Unit[];
	/** needs-an-account only: the units per currency over the whole section, by currency code */
	groups: QueueGroup[];
	/** waiting only: the units per account waited for, over the whole section, in the server's order */
	accountGroups: QueueAccountGroup[];
	/** pending, cut by counterparty only: every group of the whole section, as the FIRST fetch gave
	 * them (labels and counts do not change on Load more) */
	counterpartyGroups: CounterpartyGroup[];
	nextCursor: string | null;
	loadingMore: boolean;
	moreError: ApiError | null;
};

/** The ticks are an immutable snapshot, replaced whole (`$state.raw`): a plain Map is what is meant. */
function copyOf<K, V>(from?: ReadonlyMap<K, V>): Map<K, V> {
	return new Map(from);
}

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
		groups: [],
		accountGroups: [],
		counterpartyGroups: [],
		nextCursor: null,
		loadingMore: false,
		moreError: null
	}));
}

export class ReviewQueueStore {
	sections = $state.raw<SectionState[]>(emptySections());
	status = $state<QueueStatus>('loading');
	error = $state.raw<ApiError | null>(null);
	/** the ledger changed since the queue was fetched: the one quiet notice (patterns §7) */
	readonly news = new NewDataWatch('ledger');
	/** what the unit panel's actions did to the rows held */
	marks = $state.raw<Marks>(noMarks());

	/** a quiet line the panel leaves behind ("Review done"); cleared by a reload */
	notice = $state<string | null>(null);

	/** currencies an account was added for since the load: "N units can now be completed" */
	accountsAdded = $state.raw<readonly string[]>([]);

	/** An account in this currency now exists: a passive notice, no row moves (patterns §7). */
	noteAccountAdded(currency: string): void {
		if (!this.accountsAdded.includes(currency))
			this.accountsAdded = [...this.accountsAdded, currency];
	}

	/** the accounts the queue is narrowed to (none: the whole queue); the page keeps them in the address */
	accountIds = $state.raw<readonly number[]>([]);
	#applied = false;

	/** The address says which accounts: fetch the queue again when they differ from those held (or it
	 * was never fetched). The same accounts in the same order are no change. */
	applyAccounts(ids: readonly number[]): Promise<void> {
		return this.applyView(ids, this.cut);
	}

	/** how the pending section is cut (default: by counterparty, D275); the page keeps it in the address */
	cut = $state<QueueCut>(DEFAULT_CUT);

	/** The address says which accounts and which cut: fetch again when either differs from what is
	 * held (or nothing was fetched yet). */
	applyView(ids: readonly number[], cut: QueueCut): Promise<void> {
		const same =
			ids.length === this.accountIds.length && ids.every((id, i) => id === this.accountIds[i]);
		if (this.#applied && same && cut === this.cut) return Promise.resolve();
		this.#applied = true;
		this.accountIds = ids;
		this.cut = cut;
		return this.load();
	}

	/**
	 * The units ticked for "commit as seen" (views/review-queue.md), by anchor id, each as its rows
	 * showed it when ticked: what a commit is compared with. Cleared by every load; a page of Load
	 * more keeps it.
	 */
	selected = $state.raw<ReadonlyMap<number, Unit>>(copyOf());
	/** a run of commits is under way: how far it is */
	progress = $state.raw<{ done: number; total: number } | null>(null);

	/** Why this unit cannot be ticked, or null where a commit would confirm what its row shows. */
	selectionReason(unit: Unit): string | null {
		return selectionReason(
			unit,
			unit.entries.some((e) => this.marks.resolved.has(e.id))
		);
	}

	/** Tick (`on`) or clear the units that can be; the reason of the first that cannot, if all of them could not. */
	select(units: readonly Unit[], on: boolean): string | null {
		const next = copyOf(this.selected);
		let reason: string | null = null;
		let changed = false;
		for (const unit of units) {
			if (on) {
				const why = this.selectionReason(unit);
				if (why !== null) reason ??= why;
				else if (!next.has(unit.anchor_entry_id)) {
					next.set(unit.anchor_entry_id, unit);
					changed = true;
				}
			} else if (next.delete(unit.anchor_entry_id)) changed = true;
		}
		if (changed) this.selected = next;
		return changed ? null : reason;
	}

	/** Tick the unit, or clear it when ticked; the reason where it cannot be ticked. */
	toggle(unit: Unit): string | null {
		return this.select([unit], !this.selected.has(unit.anchor_entry_id));
	}

	clearSelection(): void {
		if (this.selected.size > 0) this.selected = copyOf();
	}

	/**
	 * Commit the ticked units one after the other, each as the panel would, in the order drawn: each
	 * is read and previewed anew and committed only if its values are those its row showed. Not a
	 * transaction: a unit that changed or is refused is cleared, marked with the reason and counted,
	 * and the rest go on. What each commit touched patches the rows at once.
	 */
	async commitSelected(options: SeenOptions): Promise<void> {
		if (this.progress !== null) return;
		const run = this.units.filter((u) => this.selected.has(u.anchor_entry_id));
		if (run.length === 0) return;
		const generation = this.#generation;
		this.notice = null;
		let committed = 0;
		let refused = 0;
		for (const [at, unit] of run.entries()) {
			if (generation !== this.#generation) return; // the queue was loaded again: the run is void
			this.progress = { done: at, total: run.length };
			const seen = this.selected.get(unit.anchor_entry_id);
			if (!seen) continue; // cleared meanwhile
			const result = await commitAsSeen(seen, options);
			if (generation !== this.#generation) return;
			if (result.ok) {
				committed++;
				this.patchAffected(affectedOf(result.out, unit.anchor_entry_id));
			} else {
				refused++;
				this.marks = markChanged(
					this.marks,
					seen.entries.map((e) => e.id),
					result.reason
				);
			}
			this.select([seen], false);
		}
		this.progress = null;
		this.notice =
			refused === 0
				? `${committed} committed`
				: `${committed} committed · ${refused} not committed`;
	}

	/** the unit (anchor id) the panel shows: the page puts its cursor there */
	revealed = $state<number | null>(null);

	readonly total = $derived(this.sections.reduce((sum, s) => sum + s.total, 0));
	/** the loaded units in queue order, across the sections */
	readonly units = $derived(this.sections.flatMap((s) => s.units));

	#generation = 0;
	#controller: AbortController | null = null;

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
		reveal: (id, visit = true) => {
			const at = this.#indexOf(id);
			if (at < 0) return false;
			const unit = this.units[at];
			this.revealed = unit.anchor_entry_id;
			// the cursor follows; a mark fades when it visits (not for the units just committed)
			if (visit) this.visited(unit.entries.map((e) => e.id));
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
		// a refresh, a filter or a cut: what was ticked is not what will be drawn
		this.selected = copyOf();
		this.progress = null;
		await this.news.prepare();
		if (generation !== this.#generation) return;
		try {
			const queue = await getQueue({
				accountIds: this.accountIds,
				cut: this.cut,
				signal: controller.signal
			});
			if (generation !== this.#generation) return;
			this.sections = SECTION_ORDER.map((kind) => {
				const found = queue.sections.find((s) => s.kind === kind);
				const groups = found?.groups ?? [];
				const accountGroups = found?.account_groups ?? [];
				return {
					kind,
					total: found?.total ?? 0,
					units: orderByGroups(found?.units ?? [], groupKeys({ groups, accountGroups })),
					groups,
					accountGroups,
					counterpartyGroups: found?.counterparty_groups ?? [],
					nextCursor: found?.next_cursor ?? null,
					loadingMore: false,
					moreError: null
				};
			});
			this.notice = null;
			this.accountsAdded = [];
			this.marks = noMarks();
			this.status = 'ready';
			if (this.units.some(unitReadsRules)) void ruleNames.refresh(); // fresh after this load
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
			const page = await getQueue({
				section: kind,
				cursor: section.nextCursor,
				accountIds: this.accountIds,
				cut: this.cut
			});
			if (generation !== this.#generation) return;
			const found = page.sections.find((s) => s.kind === kind);
			// the section as it is NOW (an action may have patched its rows meanwhile)
			const now = this.sections.find((s) => s.kind === kind) ?? section;
			this.#update(kind, {
				// the units of a later page join their group
				units: orderByGroups(
					appendUnits(now.units, found?.units ?? []),
					groupKeys({
						groups: found?.groups ?? now.groups,
						accountGroups: found?.account_groups ?? now.accountGroups
					})
				),
				groups: found?.groups ?? now.groups,
				accountGroups: found?.account_groups ?? now.accountGroups,
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
		this.#dropIneligible();
	}

	/**
	 * A patch can make a ticked unit ineligible (its rows now lack a category, its pair is gone):
	 * it is unticked silently, as its checkbox is disabled; the batch must not commit what the row
	 * no longer shows as complete.
	 */
	#dropIneligible(): void {
		if (this.selected.size === 0) return;
		const next = copyOf(this.selected);
		for (const [anchor] of this.selected) {
			const now = this.units.find((u) => u.anchor_entry_id === anchor);
			if (now && this.selectionReason(now) !== null) next.delete(anchor);
		}
		if (next.size !== this.selected.size) this.selected = next;
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
	}
}
