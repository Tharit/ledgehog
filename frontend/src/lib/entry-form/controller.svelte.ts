// THE entry form: one controller for the whole app, its dialogs mounted once in the root layout
// (components/entry-form), so the unit panel's `⋯` menu can reach them from any page. The ledger's
// "Add entry" and the panel's "Edit entry" / "Delete entry" call `openAdd`, `openEdit`, `openDelete`.
// Pages that hold rows register a listener to learn what a write did (the ledger refreshes to show
// a new entry); rows are patched through the panel's active unit source (patterns §7).
import type { SourceDeleteOut, SourceEditOut, SourceWriteOut } from '#lib/api/types.js';
import { SETTLE_STALE } from '#lib/ledger/errors.js';
import { session } from '#lib/stores/session.svelte.js';
import type { Entry } from '#lib/types/domain.js';
import { unitPanel } from '#lib/units/panel-instance.js';
import { activeUnitSource } from '#lib/units/sources.js';
import { describeEntry } from './effects.js';

export type EntryFormListener = {
	/** a transaction was entered (also by "Add and add another") */
	created?(out: SourceWriteOut): void | Promise<void>;
	/** a quiet line for the page's notice slot (patterns §11.5) */
	notify?(text: string, error?: boolean): void;
};

export type EditTarget = {
	entry: Entry;
	/** the source's amount: what the form edits (a split's entries sum to it) */
	sourceMinor: number;
};

export type AddOptions = {
	/** the account the ledger is filtered to, when it is exactly one */
	filtered?: readonly number[];
};

type Mode = 'add' | 'edit' | 'delete';

/** The source's amount: the source says it; else the sum of the held entries of that source. */
export function sourceAmountOf(entry: Entry, siblings: readonly Entry[] = []): number {
	if (entry.source) return entry.source.amount.amount;
	const same = siblings.filter(
		(e) =>
			e.source_transaction_id !== null && e.source_transaction_id === entry.source_transaction_id
	);
	const rows = same.some((e) => e.id === entry.id) ? same : [entry];
	return rows.reduce((sum, e) => sum + e.amount.amount, 0);
}

export class EntryFormController {
	mode = $state<Mode | null>(null);
	addOptions = $state.raw<AddOptions>({});
	target = $state.raw<EditTarget | null>(null);
	/** the element that opened a dialog: the panel returns focus there */
	opener: HTMLElement | null = null;

	#listeners: EntryFormListener[] = [];

	/** Register a page's listener; call the returned function when the page goes away. */
	listen(listener: EntryFormListener): () => void {
		this.#listeners = [...this.#listeners, listener];
		return () => void (this.#listeners = this.#listeners.filter((l) => l !== listener));
	}

	openAdd(options: AddOptions = {}): void {
		this.#remember();
		this.addOptions = options;
		this.target = null;
		this.mode = 'add';
	}

	/** Edit a user-authored entry's transaction. Entries without a source transaction are ignored. */
	openEdit(entry: Entry): void {
		if (entry.source_transaction_id === null) return;
		this.#remember();
		this.target = {
			entry,
			sourceMinor: sourceAmountOf(entry, unitPanel.unit?.entries ?? [])
		};
		this.mode = 'edit';
	}

	openDelete(entry: Entry): void {
		if (entry.source_transaction_id === null) return;
		this.#remember();
		this.target = { entry, sourceMinor: sourceAmountOf(entry, unitPanel.unit?.entries ?? []) };
		this.mode = 'delete';
	}

	close(): void {
		this.mode = null;
	}

	#remember(): void {
		this.opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
	}

	get #locale(): string {
		return session.config?.locale ?? 'en';
	}

	notify(text: string, error = false): void {
		for (const listener of this.#listeners) listener.notify?.(text, error);
	}

	/** A transaction was entered. `open`: the work panel opens on its unit (Add, not "Add and add another"). */
	created(out: SourceWriteOut, open: boolean): void {
		for (const listener of this.#listeners) void listener.created?.(out);
		if (out.settle.error) this.notify(`Added. ${SETTLE_STALE}`);
		if (open && out.anchor_entry_id !== null) unitPanel.open(out.anchor_entry_id, this.opener);
	}

	/** An edit was saved: the rows held follow the answer, and the open unit is loaded again. */
	edited(out: SourceEditOut): void {
		activeUnitSource()?.patch({
			entries: out.entries,
			removed_entry_ids: out.removed_entry_ids,
			returned_to_review: out.effects.returned_to_review_ids
		});
		if (unitPanel.isOpen) void unitPanel.reload();
		if (out.settle?.error) this.notify(`Saved. ${SETTLE_STALE}`);
	}

	/** The panel's unit has to be read again (a conflict said it moved). */
	refreshPanel(): void {
		if (unitPanel.isOpen) void unitPanel.reload();
	}

	/**
	 * A delete was done: the rows go (kept and marked), the partners follow the answer, and the panel
	 * steps to the neighbour unit or closes when it showed the deleted one.
	 */
	deleted(out: SourceDeleteOut, entry: Entry): void {
		const source = activeUnitSource();
		source?.patch({
			entries: out.partners,
			removed_entry_ids: out.removed_entry_ids
		});
		const removed = out.removed_entry_ids;
		const shown = unitPanel.unit;
		if (
			unitPanel.isOpen &&
			(removed.includes(unitPanel.unitId ?? -1) ||
				(shown !== null && shown.entries.some((e) => removed.includes(e.id))))
		) {
			const from = shown?.anchor_entry_id ?? unitPanel.unitId ?? entry.id;
			const next = source?.neighbour(from, 1) ?? source?.neighbour(from, -1) ?? null;
			if (next !== null && !removed.includes(next)) unitPanel.open(next, this.opener);
			else unitPanel.close();
		}
		const said = `Deleted entry ${describeEntry(entry, this.#locale)}.`;
		this.notify(out.settle?.error ? `${said} ${SETTLE_STALE}` : said);
	}
}

export const entryForm = new EntryFormController();
