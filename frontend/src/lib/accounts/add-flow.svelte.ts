// The Add account form's state and its one submission. A currency the caller needs is locked;
// otherwise it is one of the currencies the household already knows (the base currency and its
// accounts'). The new account joins the shared lookups before the caller hears of it.
import { createAccount } from '#lib/api/index.js';
import type { AccountKind } from '#lib/api/types.js';
import { lookupsStore } from '#lib/stores/lookups.svelte.js';
import { session } from '#lib/stores/session.svelte.js';
import type { Account } from '#lib/types/domain.js';
import type { AddAccountOptions } from './controller.svelte.js';
import { classifyAccountError, describeAccountFailure, failureField } from './errors.js';
import { DEFAULT_KIND } from './kinds.js';
import { loadProviderSuggestions } from './provider-suggestions.js';

export type AddAccountErrors = {
	name?: string;
	currency?: string;
	externalRef?: string;
	providers?: string;
	start?: string;
};

/** The currencies to choose from: the base currency first, then the accounts', each once. */
export function knownCurrencies(base: string | undefined, accounts: Iterable<Account>): string[] {
	const found = base ? [base] : [];
	for (const account of [...accounts].sort((a, b) => a.currency.localeCompare(b.currency)))
		if (!found.includes(account.currency)) found.push(account.currency);
	return found;
}

export class AddAccountFlow {
	name = $state('');
	kind = $state<AccountKind>(DEFAULT_KIND);
	currency = $state('');
	/** the currency was given and cannot be changed */
	locked = $state(false);
	externalRef = $state('');
	/** a clearance account's: the day its first order starts after, and the shops it books */
	startDate = $state('');
	providers = $state<string[]>([]);
	suggestions = $state<string[]>([]);
	errors = $state.raw<AddAccountErrors>({});
	/** a refusal that belongs to no field: shown in the dialog above its buttons */
	failure = $state<string | null>(null);
	busy = $state(false);

	readonly currencies = $derived(
		knownCurrencies(session.config?.base_currency, lookupsStore.lookups.accounts.values())
	);

	/** Reset for a fresh dialog: nothing of an earlier one survives (patterns §11.2). */
	start(options: AddAccountOptions = {}): void {
		this.name = options.name ?? '';
		this.externalRef = options.externalRef ?? '';
		this.kind = options.kind ?? DEFAULT_KIND;
		this.locked = options.currency !== undefined;
		this.currency = options.currency ?? session.config?.base_currency ?? this.currencies[0] ?? '';
		this.startDate = '';
		this.providers = [];
		this.errors = {};
		this.failure = null;
		this.busy = false;
		void loadProviderSuggestions().then((found) => (this.suggestions = found));
	}

	get clearance(): boolean {
		return this.kind === 'clearance';
	}

	get canSubmit(): boolean {
		return (
			this.name.trim() !== '' && this.currency !== '' && (!this.clearance || this.startDate !== '')
		);
	}

	/** Add the account; the account, or null with the refusal said in `errors` or `failure`. */
	async submit(): Promise<Account | null> {
		const name = this.name.trim();
		if (!this.canSubmit || this.busy) return null;
		this.busy = true;
		this.errors = {};
		this.failure = null;
		try {
			const known = [...lookupsStore.lookups.accounts.values()];
			const externalRef = this.externalRef.trim();
			const out = await createAccount({
				name,
				kind: this.kind,
				currency: this.currency,
				providers: this.clearance ? this.providers : [],
				...(this.clearance ? { start_date: this.startDate } : {}),
				...(externalRef !== '' ? { external_ref: externalRef } : {}),
				// after the accounts held, so a new one does not jump to the top of the list
				sort_order: known.reduce((top, a) => Math.max(top, a.sort_order), -1) + 1
			});
			lookupsStore.addAccount(out.account);
			return out.account;
		} catch (error) {
			const failure = classifyAccountError(error);
			const text = describeAccountFailure(failure);
			const field = failureField(failure);
			if (field) this.errors = { [field]: text };
			else this.failure = text;
			return null;
		} finally {
			this.busy = false;
		}
	}
}
