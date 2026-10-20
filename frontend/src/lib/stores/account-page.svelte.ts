// State of the account page (`/accounts/[id]`): the account with its facts, its statement, the
// page's one notice line. Page-scoped: the page creates one and drops it. The statement is a
// snapshot refetched after this page's own writes (`afterWrite`), the account's facts with it,
// because a write moves the balance, the data age and the unexplained difference.
import { ApiError, clearDuplicate, getEntry, listAccounts, reopenAccount } from '#lib/api/index.js';
import type { RecordWriteOut } from '#lib/api/types.js';
import { classifyWriteError } from '#lib/accounts/errors.js';
import { entryForm } from '#lib/entry-form/controller.svelte.js';
import { todayIso } from '#lib/format/index.js';
import { SETTLE_STALE } from '#lib/ledger/errors.js';
import type { Account, Provenance } from '#lib/types/domain.js';
import { unitPanel } from '#lib/units/panel-instance.js';
import { lookupsStore } from './lookups.svelte.js';
import { NewDataWatch } from './new-data.svelte.js';
import { session } from './session.svelte.js';
import { StatementStore } from './statement.svelte.js';

export type PageStatus = 'loading' | 'ready' | 'missing' | 'error';

/** One quiet line under the page header, with an optional link-like action (patterns §11.5). */
export type PageNotice = {
	text: string;
	error: boolean;
	action?: { label: string; run: () => void };
};

export class AccountPageStore {
	accountId = $state<number | null>(null);
	account = $state.raw<Account | null>(null);
	status = $state<PageStatus>('loading');
	error = $state.raw<ApiError | null>(null);
	readonly statement = new StatementStore();
	notice = $state.raw<PageNotice | null>(null);
	/** this account changed since the header, facts and statement were fetched (keyed on open) */
	readonly news = new NewDataWatch();

	readonly locale = $derived(session.config?.locale ?? 'en');
	readonly today = $derived(todayIso(session.config?.timezone ?? 'UTC'));

	#refreshers: Array<() => Promise<void>> = [];
	#generation = 0;

	/** Something else that has to be read again after a write (the runs of this account). */
	onRefresh(refresh: () => Promise<void>): void {
		this.#refreshers = [...this.#refreshers, refresh];
	}

	/** Show an account: its facts and the first page of its statement. */
	async open(accountId: number): Promise<void> {
		const generation = ++this.#generation;
		this.news.rekey({ account: accountId });
		this.accountId = accountId;
		this.account = null;
		this.status = 'loading';
		this.error = null;
		this.notice = null;
		await this.news.prepare();
		if (generation !== this.#generation) return;
		void this.statement.load(accountId);
		try {
			const found = await this.#fetchAccount(accountId);
			if (generation !== this.#generation) return;
			this.account = found;
			this.status = found ? 'ready' : 'missing';
		} catch (error) {
			if (generation !== this.#generation) return;
			this.error =
				error instanceof ApiError
					? error
					: new ApiError(0, 'network_error', 'The server could not be reached.');
			this.status = 'error';
		}
	}

	async #fetchAccount(id: number): Promise<Account | null> {
		const all = await listAccounts();
		lookupsStore.setAccounts(all);
		return all.find((a) => a.id === id) ?? null;
	}

	/** The account as a write answered: its facts as they now stand. */
	applyAccount(account: Account): void {
		if (account.id !== this.accountId) return;
		this.account = account;
		lookupsStore.addAccount(account);
	}

	/**
	 * A write made from this page was done: the facts and every page of the statement are read
	 * again, and so is whatever registered (runs). A failure leaves what is held, said quietly.
	 */
	async afterWrite(): Promise<void> {
		const id = this.accountId;
		if (id === null) return;
		const generation = this.#generation;
		await this.news.prepare();
		if (generation !== this.#generation) return;
		const [account] = await Promise.allSettled([
			this.#fetchAccount(id),
			this.statement.refetch(),
			...this.#refreshers.map((refresh) => refresh())
		]);
		if (generation !== this.#generation) return;
		if (account.status === 'fulfilled' && account.value) this.account = account.value;
		if (account.status === 'rejected' || this.statement.refetchFailed) {
			this.notify('The page could not be refreshed; its figures may be out of date.', true);
		}
	}

	notify(text: string, error = false, action?: PageNotice['action']): void {
		this.notice = { text, error, action };
	}

	/** A record was set or edited: the answer's account facts apply at once, the rest is refetched. */
	async recordWritten(out: RecordWriteOut): Promise<void> {
		this.applyAccount(out.account);
		if (out.settle.error) this.notify(`Saved. ${SETTLE_STALE}`);
		await this.afterWrite();
	}

	/** "Not a duplicate": acts at once; the notice says the row has an entry again, in review. */
	async notDuplicate(sourceId: number): Promise<boolean> {
		try {
			const out = await clearDuplicate(sourceId);
			const entryId = out.anchor_entry_id;
			await this.afterWrite();
			this.notify(
				'This row has an entry again and is in review.',
				false,
				entryId === null
					? undefined
					: { label: 'Open in review', run: () => unitPanel.open(entryId) }
			);
			return true;
		} catch (error) {
			this.notify(classifyWriteError(error).text, true);
			return false;
		}
	}

	/** "Reopen": acts at once; the facts follow the answer. */
	async reopen(): Promise<void> {
		const id = this.accountId;
		if (id === null) return;
		try {
			const out = await reopenAccount(id);
			this.applyAccount(out.account);
			await this.afterWrite();
		} catch (error) {
			this.notify(classifyWriteError(error).text, true);
		}
	}

	/**
	 * Edit or delete a row entered by hand: the entry form's own dialogs, which take the row's
	 * entry. The statement follows what they do (the controller's `changed`).
	 */
	async openAuthored(row: Pick<Provenance, 'entry_id'>, mode: 'edit' | 'delete'): Promise<void> {
		if (row.entry_id === null) return;
		try {
			const entry = await getEntry(row.entry_id);
			if (mode === 'edit') entryForm.openEdit(entry);
			else entryForm.openDelete(entry);
		} catch (error) {
			this.notify(classifyWriteError(error).text, true);
		}
	}

	dispose(): void {
		this.#generation++;
		this.statement.dispose();
	}
}
