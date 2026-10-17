// "Delete…" on a balance record, any kind (spec §3.10): the decision says what deleting does, the
// interval merging into the next record's, and writes only on its verb.
import { deleteBalanceRecord } from '#lib/api/index.js';
import type { RecordDeleteOut } from '#lib/api/types.js';
import type { StatementRecord } from '#lib/types/domain.js';
import { classifyWriteError, type WriteFailure } from './errors.js';

export class RecordDeleteFlow {
	record = $state.raw<StatementRecord | null>(null);
	failure = $state.raw<WriteFailure | null>(null);
	busy = $state(false);

	start(record: StatementRecord): void {
		this.record = record;
		this.failure = null;
		this.busy = false;
	}

	/** The deletion's answer, or null with the refusal in `failure`. */
	async confirm(): Promise<RecordDeleteOut | null> {
		const record = this.record;
		if (!record || this.busy) return null;
		this.busy = true;
		this.failure = null;
		try {
			return await deleteBalanceRecord(record.id);
		} catch (error) {
			this.failure = classifyWriteError(error);
			return null;
		} finally {
			this.busy = false;
		}
	}
}
