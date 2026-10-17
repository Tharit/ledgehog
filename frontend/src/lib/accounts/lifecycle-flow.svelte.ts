// Closing and deleting an account (spec §3.3). "Close…" asks for the closing date (default today):
// the account stops fetching and holds no balance, its history stays. "Delete…" is the decision
// the server refuses for an account that holds anything: the refusal says what it holds and the
// dialog offers "Close…" instead.
import { closeAccount, deleteAccount } from '#lib/api/index.js';
import type { AccountWriteOut } from '#lib/api/types.js';
import type { Account } from '#lib/types/domain.js';
import { classifyWriteError, type WriteFailure } from './errors.js';

export class CloseAccountFlow {
	account = $state.raw<Account | null>(null);
	date = $state('');
	failure = $state.raw<WriteFailure | null>(null);
	busy = $state(false);

	start(account: Account, today: string): void {
		this.account = account;
		this.date = today;
		this.failure = null;
		this.busy = false;
	}

	get canSubmit(): boolean {
		return this.account !== null && this.date !== '';
	}

	async confirm(): Promise<AccountWriteOut | null> {
		const account = this.account;
		if (!account || this.busy || !this.canSubmit) return null;
		this.busy = true;
		this.failure = null;
		try {
			return await closeAccount(account.id, this.date);
		} catch (error) {
			this.failure = classifyWriteError(error);
			return null;
		} finally {
			this.busy = false;
		}
	}
}

export class DeleteAccountFlow {
	account = $state.raw<Account | null>(null);
	failure = $state.raw<WriteFailure | null>(null);
	busy = $state(false);

	start(account: Account): void {
		this.account = account;
		this.failure = null;
		this.busy = false;
	}

	/** True when it was deleted; a refusal (it holds something) is in `failure`. */
	async confirm(): Promise<boolean> {
		const account = this.account;
		if (!account || this.busy) return false;
		this.busy = true;
		this.failure = null;
		try {
			await deleteAccount(account.id);
			return true;
		} catch (error) {
			this.failure = classifyWriteError(error);
			return false;
		} finally {
			this.busy = false;
		}
	}
}
