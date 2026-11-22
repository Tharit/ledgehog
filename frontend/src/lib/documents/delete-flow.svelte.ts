// "Delete…" a document (spec §5.5): the document goes and, where it is booked, its booking with all
// its entries. A refusal (it is already gone, the server is unreachable) is said in the dialog.
import { deleteDocument } from '#lib/api/index.js';
import { classifyWriteError, type WriteFailure } from '#lib/accounts/errors.js';

export class DeleteDocumentFlow {
	documentId = $state<number | null>(null);
	failure = $state.raw<WriteFailure | null>(null);
	busy = $state(false);

	start(documentId: number): void {
		this.documentId = documentId;
		this.failure = null;
		this.busy = false;
	}

	/** True when it was deleted; otherwise the reason is in `failure`. */
	async confirm(): Promise<boolean> {
		const id = this.documentId;
		if (id === null || this.busy) return false;
		this.busy = true;
		this.failure = null;
		try {
			await deleteDocument(id);
			return true;
		} catch (error) {
			this.failure = classifyWriteError(error);
			return false;
		} finally {
			this.busy = false;
		}
	}
}
