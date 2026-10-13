// The unit panel's state (patterns §4.1, §5): which unit is open, loading it, stepping to its
// neighbours and closing. The address is the state: `?unit=<anchor entry id>` on any page. Opening
// adds a history entry, stepping replaces it, so a reload and a shared link open the panel, and
// Back closes it. The panel is mounted once in the root layout and driven by this store.
// Page-independent: the list it was opened from registers itself as a `UnitSource`; the panel
// only asks it for neighbours and positions.
//
// Navigation is injected (`PanelNav`), so this store never touches SvelteKit or the DOM history
// itself and can be tested with a plain object.

import { ApiError, getUnit } from '#lib/api/index.js';
import { unitIdOf, withUnit } from './address.js';
import { ruleNames } from '#lib/stores/rule-names.svelte.js';
import type { RuleNames } from './evidence.js';
import { activeUnitSource, type StepDirection } from './sources.js';
import type { Unit } from './types.js';

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

	#pushed = false;
	#generation = 0;
	#controller: AbortController | null = null;

	constructor(nav: PanelNav) {
		this.#nav = nav;
	}

	/** Follow the address: on load, after Back/Forward, after a navigation. */
	sync(): void {
		const id = unitIdOf(this.#nav.url());
		if (id === this.unitId) return;
		if (id === null) {
			this.#reset();
			return;
		}
		this.#show(id);
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

	/** Close: Back when the panel was opened here, else the parameter is removed from the address. */
	close(): void {
		if (!this.isOpen) return;
		if (this.#pushed) {
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

	/** The panel's element to focus on close: the origin, else the row of the entry it came from. */
	focusTarget(): HTMLElement | null {
		if (this.origin?.isConnected) return this.origin;
		if (this.originEntryId === null) return null;
		const ids = [this.originEntryId, ...(this.unit?.entries.map((e) => e.id) ?? [])];
		for (const id of ids) {
			const row = document.querySelector<HTMLElement>(`[data-entry-id="${id}"]`);
			if (row) return row.closest<HTMLElement>('[role="grid"]') ?? row;
		}
		return null;
	}

	#candidates(unit: Unit): number[] {
		return [unit.anchor_entry_id, ...unit.entries.map((e) => e.id)];
	}

	#show(id: number): void {
		this.unitId = id;
		this.stepNotice = null;
		void this.#load(id);
	}

	#reset(): void {
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
			// opened by any entry of the unit: the address names the anchor
			if (unit.anchor_entry_id !== id) {
				this.#nav.replace(withUnit(this.#nav.url(), unit.anchor_entry_id));
				this.unitId = unit.anchor_entry_id;
			}
			if (unitReadsRules(unit)) void ruleNames.ensure();
		} catch (error) {
			if (generation !== this.#generation) return;
			this.unit = null;
			const failure = asApiError(error);
			this.error = failure;
			this.status = failure.code === 'not_found' ? 'missing' : 'error';
		}
	}

	/** The panel is going away. */
	dispose(): void {
		this.#generation++;
		this.#controller?.abort();
	}
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
