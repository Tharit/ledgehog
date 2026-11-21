// How the pending section is cut (views/review-queue.md): by date (month and day) or by
// counterparty. The choice is in the review page's address with the filter, `?cut=counterparty`;
// "By date" is the default and is left out.

export type QueueCut = 'date' | 'counterparty';

/** The query parameter that holds the cut. */
export const CUT_PARAM = 'cut';

/** The cut an address names; anything unknown is "by date". */
export function cutFromSearchParams(
	params: { get(name: string): string | null } | string
): QueueCut {
	const p = typeof params === 'string' ? new URLSearchParams(params) : params;
	return p.get(CUT_PARAM) === 'counterparty' ? 'counterparty' : 'date';
}

/** Put the cut into `params`: set for "by counterparty", removed for "by date". */
export function withCut(params: URLSearchParams, cut: QueueCut): URLSearchParams {
	if (cut === 'counterparty') params.set(CUT_PARAM, cut);
	else params.delete(CUT_PARAM);
	return params;
}
