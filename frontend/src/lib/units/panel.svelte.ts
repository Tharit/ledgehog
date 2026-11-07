// The unit panel's state (patterns §4.1, §5): which unit is open, loading it, stepping to its
// neighbours and closing. The address is the state: `?unit=<anchor entry id>` on any page. Opening
// adds a history entry, stepping replaces it, so a reload and a shared link open the panel, and
// Back closes it. The panel is mounted once in the root layout and driven by this store.
// Page-independent: the list it was opened from registers itself as a `UnitSource`; the panel
// only asks it for neighbours and positions.
//
// Navigation is injected (`PanelNav`), so this store never touches SvelteKit or the DOM history
// itself and can be tested with a plain object.

import { untrack } from 'svelte';
import { ApiError, getUnit } from '#lib/api/index.js';
import { NO_IDS, withIds } from '#lib/ledger/patch.js';
import { unitIdOf, withUnit } from './address.js';
import { lookupsStore } from '#lib/stores/lookups.svelte.js';
import { ruleNames } from '#lib/stores/rule-names.svelte.js';
import type { RuleNames } from './evidence.js';
import { activeUnitSource, type StepDirection } from './sources.js';
import type { Affected, Unit, UnitCommit, UnitPreview } from './types.js';
import { UnitDraftFlow } from './unit-draft-flow.svelte.js';

export type PanelNav = {
	/** the address now */
	url(): URL;
	/** a new history entry */
	push(url: string): void;
	/** this history entry, changed */
	replace(url: string): void;
	/** one entry back */
	back(): void;
};

export type PanelStatus = 'idle' | 'loading' | 'ready' | 'error' | 'missing';

function asApiError(error: unknown): ApiError {
	return error instanceof ApiError
		? error
		: new ApiError(0, 'network_error', 'The server could not be reached.');
}

export class UnitPanel {
	readonly #nav: PanelNav;

	/** the unit the address names; null while the panel is closed */
	unitId = $state<number | null>(null);
	status = $state<PanelStatus>('idle');
	unit = $state.raw<Unit | null>(null);
	error = $state.raw<ApiError | null>(null);
	/** a quiet line about stepping ("This is the last unit.") */
	stepNotice = $state<string | null>(null);
	/** the rules known by name, loaded when a unit shows a rule's key */
	get rules(): RuleNames {
		return ruleNames.names;
	}

	/** the draft of the open unit, its preview and its commit */
	readonly flow: UnitDraftFlow;

	/** a decision about leaving a draft with changes ("Discard changes?"), while one is asked */
	leave = $state.raw<{ proceed: () => void } | null>(null);
	/** counts up when focus should go back to the panel itself (after advancing, after a decision) */
	focusToken = $state(0);

	/** the element that had focus when the panel opened: focus returns there */
	origin: HTMLElement | null = null;
	/** the entry the panel was opened from (to find its row again) */
	originEntryId: number | null = null;

	readonly isOpen = $derived(this.unitId !== null);
	readonly position = $derived.by(() => {
		const source = activeUnitSource();
		const unit = this.unit;
		if (!source?.position || !unit) return null;
		for (const id of this.#candidates(unit)) {
			const at = source.position(id);
			if (at) return at;
		}
		return null;
	});
	/** what a screen reader hears when the panel loads or steps */
	readonly announcement = $derived.by(() => {
		if (this.status === 'loading') return 'Loading the unit…';
		if (this.status === 'error') return 'The unit could not be loaded.';
		if (this.status === 'missing') return 'This entry has no review.';
		return this.stepNotice ?? '';
	});

	/** the entries of the units committed since the panel opened: advancing skips them */
	#handled: ReadonlySet<number> = NO_IDS;
	#pushed = false;
	/** the unit closed by a Back that has not completed yet */
	#leaving: number | null = null;
	#generation = 0;
	#controller: AbortController | null = null;

	constructor(nav: PanelNav, locale: () => string = () => 'en') {
		this.#nav = nav;
		this.flow = new UnitDraftFlow({
			locale,
			unitChanged: (unit) => {
				this.unit = unit;
			},
			patch: (affected) => this.#patch(affected),
			reloadLookups: () => lookupsStore.reload(),
			accountCurrency: (id) => lookupsStore.lookups.accounts.get(id)?.currency,
			accountKind: (id) => lookupsStore.lookups.accounts.get(id)?.kind,
			addTag: (tag) => lookupsStore.addTag(tag),
			previewed: (preview) => {
				if (previewReadsRules(preview)) void ruleNames.ensure();
			},
			committed: (out, anchorId) => void this.#advance(out, anchorId)
		});
	}

	/** Ask before a draft with changes is lost; `proceed` runs at once when there are none. */
	requestLeave(proceed: () => void): void {
		if (this.flow.committing) return;
		if (this.flow.isDirty) this.leave = { proceed };
		else proceed();
	}

	/** The user chose to discard: carry on with what they were doing. */
	confirmLeave(): void {
		const pending = this.leave;
		this.leave = null;
		pending?.proceed();
	}

	/** The user chose to keep editing. */
	cancelLeave(): void {
		this.leave = null;
		this.focusToken++;
	}

	/** Open another unit from inside the panel (a consequence row): asks first when dirty. */
	openEntry(entryId: number): void {
		this.requestLeave(() => this.open(entryId));
	}

	#patch(affected: Affected): void {
		activeUnitSource()?.patch(affected);
	}

	/**
	 * Follow the address: on load, after Back/Forward, after a navigation. The address is the
	 * source of truth and this is the ONLY way it flows into the panel; it never reads reactive
	 * state (so an effect calling it is not re-run by the panel's own changes: that was a loop in
	 * which closing re-opened the panel from the address Back had not yet left).
	 */
	sync(): void {
		untrack(() => {
			const id = unitIdOf(this.#nav.url());
			if (id !== null && id === this.#leaving) {
				// Back is under way: the address still names the unit just closed
				this.#leaving = null;
				return;
			}
			this.#leaving = null;
			if (id === this.unitId) return;
			if (id === null) {
				this.#reset();
				return;
			}
			this.#show(id);
		});
	}

	/** Open the panel on the unit of `entryId`: a new history entry. */
	open(entryId: number, origin?: HTMLElement | null): void {
		if (this.unitId === entryId && this.isOpen) return;
		const wasOpen = this.isOpen;
		this.origin =
			origin ?? (document.activeElement instanceof HTMLElement ? document.activeElement : null);
		this.originEntryId = entryId;
		const url = withUnit(this.#nav.url(), entryId);
		if (wasOpen) this.#nav.replace(url);
		else {
			this.#nav.push(url);
			this.#pushed = true;
		}
		this.#show(entryId);
	}

	/** Step to the previous (-1) or next (1) unit of the list the panel was opened from. */
	step(dir: StepDirection): void {
		this.requestLeave(() => this.#step(dir));
	}

	#step(dir: StepDirection): void {
		const source = activeUnitSource();
		const unit = this.unit;
		if (!this.isOpen || !unit) return;
		if (!source) {
			this.stepNotice = 'Open a unit from the Ledger or Review to step through units.';
			return;
		}
		let next: number | null = null;
		for (const id of this.#candidates(unit)) {
			next = source.neighbour(id, dir);
			if (next !== null) break;
		}
		if (next === null) {
			this.stepNotice = dir === 1 ? 'This is the last unit.' : 'This is the first unit.';
			return;
		}
		this.#nav.replace(withUnit(this.#nav.url(), next));
		this.#show(next);
	}

	/** Close (asking first when the draft has changes). */
	close(): void {
		if (!this.isOpen) return;
		this.requestLeave(() => this.#close());
	}

	/** Close: Back when the panel was opened here, else the parameter is removed from the address. */
	#close(): void {
		if (!this.isOpen) return;
		if (this.#pushed) {
			this.#leaving = this.unitId;
			this.#nav.back();
		} else {
			this.#nav.replace(withUnit(this.#nav.url(), null));
		}
		this.#reset();
	}

	/** Load the open unit again (Try again). */
	retry(): void {
		if (this.unitId !== null) void this.#load(this.unitId);
	}

	/**
	 * Read the open unit again without the loading state (after an edit made elsewhere): the
	 * unit shown is replaced and the draft starts over it; a failure falls back to the error state.
	 */
	async reload(): Promise<void> {
		const id = this.unitId;
		if (id === null) return;
		if (this.status !== 'ready') return this.retry();
		this.#controller?.abort();
		const controller = new AbortController();
		this.#controller = controller;
		const generation = ++this.#generation;
		try {
			const unit = await getUnit(id, controller.signal);
			if (generation !== this.#generation) return;
			this.unit = unit;
			this.flow.begin(unit);
			if (unit.anchor_entry_id !== id) {
				this.#nav.replace(withUnit(this.#nav.url(), unit.anchor_entry_id));
				this.unitId = unit.anchor_entry_id;
			}
			if (unitReadsRules(unit)) void ruleNames.refresh(); // fresh after this load
		} catch (error) {
			if (generation !== this.#generation) return;
			this.unit = null;
			const failure = asApiError(error);
			this.error = failure;
			this.status = failure.code === 'not_found' ? 'missing' : 'error';
		}
	}

	/**
	 * Where focus goes on close: the row of the unit last shown when it can take focus (a table
	 * row), else the list it was opened from (a grid whose cursor `reveal` has already put on
	 * that unit), else the grid holding the row.
	 */
	focusTarget(): HTMLElement | null {
		const ids = this.unit
			? this.#candidates(this.unit)
			: this.originEntryId === null
				? []
				: [this.originEntryId];
		let grid: HTMLElement | null = null;
		for (const id of ids) {
			const row = document.querySelector<HTMLElement>(`[data-entry-id="${id}"]`);
			if (!row) continue;
			if (row.tabIndex >= 0) return row;
			grid ??= row.closest<HTMLElement>('[role="grid"]') ?? row;
		}
		if (this.origin?.isConnected) return this.origin;
		return grid;
	}

	/** Put the list's cursor on the unit shown (the source decides what that means). */
	#reveal(ids: readonly number[], visit = true): void {
		const source = activeUnitSource();
		if (!source?.reveal) return;
		for (const id of ids) if (source.reveal(id, visit)) return;
	}

	#candidates(unit: Unit): number[] {
		return [unit.anchor_entry_id, ...unit.entries.map((e) => e.id)];
	}

	#show(id: number): void {
		this.unitId = id;
		this.stepNotice = null;
		this.#reveal([id]);
		void this.#load(id);
	}

	#reset(): void {
		this.flow.reset();
		this.leave = null;
		this.#handled = NO_IDS;
		this.#generation++;
		this.#controller?.abort();
		this.#controller = null;
		this.unitId = null;
		this.unit = null;
		this.error = null;
		this.status = 'idle';
		this.stepNotice = null;
		this.#pushed = false;
	}

	async #load(id: number): Promise<void> {
		this.#controller?.abort();
		const controller = new AbortController();
		this.#controller = controller;
		const generation = ++this.#generation;
		this.status = 'loading';
		this.error = null;
		try {
			const unit = await getUnit(id, controller.signal);
			if (generation !== this.#generation) return;
			this.unit = unit;
			this.status = 'ready';
			this.flow.begin(unit);
			this.#reveal(this.#candidates(unit));
			// opened by any entry of the unit: the address names the anchor
			if (unit.anchor_entry_id !== id) {
				this.#nav.replace(withUnit(this.#nav.url(), unit.anchor_entry_id));
				this.unitId = unit.anchor_entry_id;
			}
			if (unitReadsRules(unit)) void ruleNames.refresh(); // fresh after this load
		} catch (error) {
			if (generation !== this.#generation) return;
			this.unit = null;
			const failure = asApiError(error);
			this.error = failure;
			this.status = failure.code === 'not_found' ? 'missing' : 'error';
		}
	}

	/**
	 * After a commit (patterns §5): stay open and show the next unit of the list that was not
	 * handled here, skipping those already committed. At the end the panel closes with a notice
	 * and the list's cursor on the last unit.
	 */
	async #advance(out: UnitCommit, anchorId: number): Promise<void> {
		// the unit as the preview showed it: a partner that settling pairs right after the commit is
		// part of it, though the commit itself did not write it
		const shown = (this.flow.preview?.rows ?? [])
			.filter((r) => r.in_unit && r.id > 0)
			.map((r) => r.id);
		const committed = [
			...out.units.flatMap((u) => u.entry_ids),
			...Object.values(out.created),
			...shown,
			anchorId
		];
		this.#handled = withIds(this.#handled, committed);
		const generation = this.#generation;
		let next: number | null = null;
		try {
			next = await this.#nextUnit(committed);
		} catch {
			// the list could not say: this is the end of what can be walked
		}
		if (generation !== this.#generation || !this.isOpen) return;
		this.focusToken++;
		if (next !== null) {
			this.#nav.replace(withUnit(this.#nav.url(), next));
			this.flow.reset();
			this.unit = null;
			this.#show(next);
			return;
		}
		const source = activeUnitSource();
		this.#reveal(committed, false); // the marks of what was just committed stay
		source?.notice?.(source.finishedText ?? 'No more units');
		this.#close();
	}

	/** The next unit after `from` that was not handled here, loading more of the list when it ends. */
	async #nextUnit(from: readonly number[]): Promise<number | null> {
		const source = activeUnitSource();
		if (!source) return null;
		let last = from[0];
		for (let round = 0; round < 3; round++) {
			let walk = (round === 0 ? from : [last]).find((id) => source.neighbour(id, 1) !== null);
			while (walk !== undefined) {
				const next = source.neighbour(walk, 1);
				if (next === null) {
					last = walk;
					break;
				}
				if (!this.#handled.has(next)) return next;
				walk = next;
			}
			if (!source.loadMore || !(await source.loadMore())) return null;
		}
		return null;
	}

	/** The panel is going away. */
	dispose(): void {
		this.flow.reset();
		this.#generation++;
		this.#controller?.abort();
	}
}

/** Does any key of a preview's rows come from a rule? */
export function previewReadsRules(preview: UnitPreview): boolean {
	return preview.rows.some((row) =>
		Object.values(row.derivation).some(
			(key) =>
				typeof key === 'object' && key !== null && (key as { pass?: unknown }).pass === 'rule'
		)
	);
}

/** Does any derivation key of the unit's entries come from a rule (so the rule names are needed)? */
export function unitReadsRules(unit: Unit): boolean {
	return unit.entries.some((entry) =>
		Object.values(entry.derivation).some(
			(key) =>
				typeof key === 'object' && key !== null && (key as { pass?: unknown }).pass === 'rule'
		)
	);
}
