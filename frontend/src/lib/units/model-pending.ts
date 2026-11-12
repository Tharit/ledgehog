// What the UI says while the model has not yet answered (views/review-queue.md): one wording each,
// shared by the navigation, the queue and the panel.

/** "1 entry" / "N entries" */
function entries(count: number): string {
	return count === 1 ? '1 entry' : `${count} entries`;
}

/** The Review item's activity mark: its tooltip and accessible name; undefined while nothing is pending. */
export function modelActivity(pending: number): string | undefined {
	return pending > 0 ? `The model is looking at ${entries(pending)}` : undefined;
}

/** The quiet line above the queue; null while nothing is pending. */
export function modelQueueLine(pending: number): string | null {
	return pending > 0 ? `The model is looking at ${entries(pending)}.` : null;
}

/** An entry row's marker. */
export const MODEL_STILL_LOOKING = 'The model is still looking at this';

/** The panel's line for a unit whose guess is still coming. */
export const MODEL_GUESS_COMING = "The model's guess for the category is still coming.";
