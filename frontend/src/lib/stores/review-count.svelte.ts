// The Review item's count (architecture §6.5): how many units can be acted on now, pending review
// and needs an account. Read by its own call, `GET /api/units/queue/count`, when the app starts and
// whenever the ledger's change value moves; the root layout drives it. A list that is not a
// snapshot, in effect: it only ever shows the latest answer. The Overview's To review card reads
// the same numbers, with the split.
import { getQueueCounts } from '#lib/api/index.js';

export class ReviewCount {
	count = $state(0);
	pendingReview = $state(0);
	needsAccount = $state(0);
	/** a read has answered: until then the numbers are not news, only zeros */
	known = $state(false);
	#generation = 0;

	/** Read the count; an answer that is not the latest read's is dropped, a failure keeps the number held. */
	async refresh(): Promise<void> {
		const generation = ++this.#generation;
		try {
			const counts = await getQueueCounts();
			if (generation !== this.#generation) return;
			this.count = counts.count;
			this.pendingReview = counts.pending_review;
			this.needsAccount = counts.needs_account;
			this.known = true;
		} catch {
			// a count that cannot be had is no news
		}
	}

	/** The session ended: nothing is held. */
	reset(): void {
		this.#generation++;
		this.count = 0;
		this.pendingReview = 0;
		this.needsAccount = 0;
		this.known = false;
	}
}

/** The one count of the app. */
export const reviewCount = new ReviewCount();
