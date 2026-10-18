// The Review item's count (architecture §6.5): how many units can be acted on now, pending review
// and needs an account. Read by its own call, `GET /api/units/queue/count`, when the app starts and
// whenever the ledger's change value moves; the root layout drives it. A list that is not a
// snapshot, in effect: it only ever shows the latest answer.
import { getQueueCount } from '#lib/api/index.js';

export class ReviewCount {
	count = $state(0);
	#generation = 0;

	/** Read the count; an answer that is not the latest read's is dropped, a failure keeps the number held. */
	async refresh(): Promise<void> {
		const generation = ++this.#generation;
		try {
			const count = await getQueueCount();
			if (generation === this.#generation) this.count = count;
		} catch {
			// a count that cannot be had is no news
		}
	}

	/** The session ended: nothing is held. */
	reset(): void {
		this.#generation++;
		this.count = 0;
	}
}

/** The one count of the app. */
export const reviewCount = new ReviewCount();
