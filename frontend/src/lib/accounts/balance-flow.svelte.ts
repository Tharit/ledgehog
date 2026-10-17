// "Set balance" (spec §5.10): a form dialog with the date, defaulting to today, and the balance.
// A date that already holds a manual record edits that record (the server upserts); opened on a
// manual record from the statement it edits that one, date included. The server decides what the
// record explains; the page refetches after the write.
import { correctBalance, setBalance } from '#lib/api/index.js';
import type { RecordWriteOut } from '#lib/api/types.js';
import { describeParseError } from '#lib/entry-form/amount.js';
import { formatMoney, parseMoneyInput } from '#lib/format/index.js';
import type { Account, StatementRecord } from '#lib/types/domain.js';
import { classifyWriteError } from './errors.js';

export type BalanceErrors = { date?: string; balance?: string };

export class BalanceFlow {
	account = $state.raw<Pick<Account, 'id' | 'currency'> | null>(null);
	/** the manual record being edited; null: a new one (or one on a date that holds one) */
	record = $state.raw<Pick<StatementRecord, 'id'> | null>(null);
	date = $state('');
	balanceText = $state('');
	errors = $state.raw<BalanceErrors>({});
	failure = $state<string | null>(null);
	busy = $state(false);

	#locale = 'en';

	start(
		account: Pick<Account, 'id' | 'currency'>,
		{
			today,
			locale,
			record
		}: {
			today: string;
			locale: string;
			record?: Pick<StatementRecord, 'id' | 'balance_on' | 'balance'>;
		}
	): void {
		this.account = account;
		this.#locale = locale;
		this.record = record ? { id: record.id } : null;
		this.date = record?.balance_on ?? today;
		this.balanceText = record
			? formatMoney(record.balance.amount, record.balance.currency, {
					locale,
					showPlus: false
				})
			: '';
		this.errors = {};
		this.failure = null;
		this.busy = false;
	}

	get canSubmit(): boolean {
		return this.account !== null && this.date !== '' && this.balanceText.trim() !== '';
	}

	/** The record as it now stands, or null with the refusal said in `errors` or `failure`. */
	async submit(): Promise<RecordWriteOut | null> {
		const account = this.account;
		if (!account || this.busy || !this.canSubmit) return null;
		const parsed = parseMoneyInput(this.balanceText, account.currency, this.#locale);
		if (!parsed.ok) {
			this.errors = { balance: describeParseError(parsed.error, account.currency) };
			return null;
		}
		const balance = { amount: parsed.minor, currency: account.currency };
		this.busy = true;
		this.errors = {};
		this.failure = null;
		try {
			return this.record
				? await correctBalance(this.record.id, { balance, balance_on: this.date })
				: await setBalance(account.id, { balance_on: this.date, balance });
		} catch (error) {
			const failure = classifyWriteError(error);
			if (failure.reason === 'record_date_taken') this.errors = { date: failure.text };
			else this.failure = failure.text;
			return null;
		} finally {
			this.busy = false;
		}
	}
}
