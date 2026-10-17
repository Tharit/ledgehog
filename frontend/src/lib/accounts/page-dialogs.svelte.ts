// Which of the account page's decision and form dialogs is open (one at a time), and on what. The
// row detail is not here: it is addressed by `?source=` (accounts/address.ts).
import type { StatementRecord } from '#lib/types/domain.js';

export type PageDialog =
	'edit' | 'close' | 'delete' | 'balance' | 'record-delete' | 'mark' | 'revert';

export class AccountDialogs {
	kind = $state<PageDialog | null>(null);
	/** the record a balance edit or a record deletion is about */
	record = $state.raw<StatementRecord | null>(null);
	/** the run a revert is about */
	runId = $state<number | null>(null);

	open(kind: PageDialog, target: { record?: StatementRecord; runId?: number } = {}): void {
		this.record = target.record ?? null;
		this.runId = target.runId ?? null;
		this.kind = kind;
	}

	close(): void {
		this.kind = null;
	}

	is(kind: PageDialog): boolean {
		return this.kind === kind;
	}
}
