// How the pending section is cut (views/review-queue.md): by date (month and day) or by
// counterparty. The choice is in the review page's address with the filter: "By counterparty" is
// the default (D275, views/review-queue.md) and is left out, "By date" is `?cut=date`.

export type QueueCut = 'date' | 'counterparty';

/** The cut of an address that names none (D275). */
export const DEFAULT_CUT: QueueCut = 'counterparty';

/** The query parameter that holds the cut. */
export const CUT_PARAM = 'cut';

/** The cut an address names; none, `cut=counterparty` (old links) or anything unknown is the default. */
export function cutFromSearchParams(
	params: { get(name: string): string | null } | string
): QueueCut {
	const p = typeof params === 'string' ? new URLSearchParams(params) : params;
	return p.get(CUT_PARAM) === 'date' ? 'date' : DEFAULT_CUT;
}

/** Put the cut into `params`: removed for the default (by counterparty), `cut=date` for "by date". */
export function withCut(params: URLSearchParams, cut: QueueCut): URLSearchParams {
	if (cut !== DEFAULT_CUT) params.set(CUT_PARAM, cut);
	else params.delete(CUT_PARAM);
	return params;
}
