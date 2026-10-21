// The add form's state and its two submissions: "Add" (creates, closes) and "Add and add another" (creates, keeps the dialog, resets the
// amount to its sign and clears the purpose).
// A submission keeps its client id while its values do not change, so a retry after a lost answer
// is the same request and the server cannot enter the row twice (architecture §4.1).
import { ApiError, createSource } from '#lib/api/index.js';
import type { SourceWriteOut } from '#lib/api/types.js';
import { formatMoney, todayIso } from '#lib/format/index.js';
import { lookupsStore } from '#lib/stores/lookups.svelte.js';
import { session } from '#lib/stores/session.svelte.js';
import type { Account } from '#lib/types/domain.js';
import { DEFAULT_AMOUNT_TEXT, leadingSign } from './amount.js';
import { entryForm, type AddOptions } from './controller.svelte.js';
import { defaultAccountId, entryAccounts, readLastAccount, writeLastAccount } from './defaults.js';
import { classifyEntryError } from './errors.js';
import { newClientId } from './ids.js';
import { validateEntry, type EntryInput, type FieldErrors } from './validate.js';

export type FlowFeedback = { kind: 'error' | 'conflict'; text: string; retryable?: boolean };

export type SubmitResult = 'added' | 'failed';

function asApiError(error: unknown): ApiError {
	return error instanceof ApiError
		? error
		: new ApiError(0, 'network_error', 'The server could not be reached.');
}

export class AddFlow {
	accountId = $state<number | null>(null);
	date = $state('');
	amountText = $state(DEFAULT_AMOUNT_TEXT);
	purpose = $state('');

	errors = $state.raw<FieldErrors>({});
	feedback = $state.raw<FlowFeedback | null>(null);
	/** "Added −12.50 EUR · groceries.", after "Add and add another" */
	added = $state<string | null>(null);
	busy = $state<'add' | 'another' | null>(null);
	/** counts up when the Amount field should take focus */
	focusAmount = $state(0);

	#pending: { signature: string; id: string } | null = null;

	readonly accounts = $derived<Account[]>(entryAccounts(lookupsStore.lookups.accounts.values()));
	readonly account = $derived(this.accounts.find((a) => a.id === this.accountId) ?? null);
	readonly locale = $derived(session.config?.locale ?? 'en');

	/** Reset to the defaults for a fresh dialog: nothing of an earlier draft survives (patterns §11.2). */
	start(options: AddOptions = {}): void {
		this.accountId = null;
		this.defaultAccount(options);
		this.date = todayIso(session.config?.timezone ?? 'UTC');
		this.amountText = DEFAULT_AMOUNT_TEXT;
		this.purpose = '';
		this.errors = {};
		this.feedback = null;
		this.added = null;
		this.busy = null;
		this.#pending = null;
	}

	/** Choose the starting account, unless one is chosen (also when the lists arrive late). */
	defaultAccount(options: AddOptions = {}): void {
		if (this.accountId !== null) return;
		this.accountId = defaultAccountId(this.accounts, {
			filtered: options.filtered,
			lastUsed: readLastAccount(session.user?.id ?? null)
		});
	}

	/** An edit of any field clears what was said about it. */
	touch(field: keyof FieldErrors): void {
		if (this.errors[field]) this.errors = { ...this.errors, [field]: undefined };
		this.feedback = null;
	}

	async submit(another: boolean): Promise<SubmitResult> {
		if (this.busy) return 'failed';
		const checked = validateEntry(
			{
				accountId: this.accountId,
				currency: this.account?.currency ?? null,
				date: this.date,
				amountText: this.amountText,
				purpose: this.purpose
			},
			this.locale
		);
		this.errors = checked.errors;
		this.feedback = null;
		if (checked.input === null) {
			if (checked.errors.amount && !checked.errors.account) this.focusAmount++;
			return 'failed';
		}
		const input = checked.input;
		const id = this.#idFor(input);
		this.busy = another ? 'another' : 'add';
		let out: SourceWriteOut;
		try {
			out = await createSource({ id, ...input });
		} catch (error) {
			this.busy = null;
			await this.#fail(asApiError(error));
			return 'failed';
		}
		this.busy = null;
		this.#pending = null;
		writeLastAccount(session.user?.id ?? null, input.account_id);
		if (another) this.#clearForNext(input);
		entryForm.created(out);
		return 'added';
	}

	/** The same values keep the same id; changed values are another submission. */
	#idFor(input: EntryInput): string {
		const signature = JSON.stringify(input);
		if (this.#pending?.signature !== signature) {
			this.#pending = { signature, id: newClientId() };
		}
		return this.#pending.id;
	}

	#clearForNext(input: EntryInput): void {
		const money = formatMoney(input.amount, this.account?.currency ?? 'EUR', {
			locale: this.locale,
			showCurrency: true,
			showPlus: false
		});
		this.added = `Added ${money}${input.purpose ? ` · ${input.purpose}` : ''}.`;
		this.amountText = leadingSign(this.amountText) ?? DEFAULT_AMOUNT_TEXT;
		this.purpose = '';
		this.errors = {};
		this.focusAmount++;
	}

	async #fail(error: ApiError): Promise<void> {
		const failure = classifyEntryError(error);
		switch (failure.kind) {
			case 'field':
				this.errors = { [failure.field]: failure.text };
				if (failure.reloadLookups) {
					await lookupsStore.reload();
					if (!this.accounts.some((a) => a.id === this.accountId)) this.accountId = null;
				}
				break;
			case 'id_taken':
				this.#pending = null;
				this.feedback = { kind: 'error', text: failure.text, retryable: true };
				break;
			case 'error':
				this.feedback = { kind: 'error', text: failure.text, retryable: failure.retryable };
				break;
			default:
				this.feedback = { kind: 'error', text: failure.text };
		}
	}
}
