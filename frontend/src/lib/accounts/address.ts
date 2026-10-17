// The row detail's address: `?source=<source transaction id>` on the account page, so a link
// from a run summary lands on the row whatever page of the statement it is on.

export const SOURCE_PARAM = 'source';

/** The id in `?source=`, or null when it is absent or not a positive integer. */
export function sourceIdOf(url: { readonly href: string }): number | null {
	const raw = new URL(url.href).searchParams.get(SOURCE_PARAM);
	return raw !== null && /^\d{1,15}$/.test(raw) && Number(raw) > 0 ? Number(raw) : null;
}

/** The address with `source` set to `id` (or removed), every other part kept. */
export function withSource(url: { readonly href: string }, id: number | null): string {
	const next = new URL(url.href);
	if (id === null) next.searchParams.delete(SOURCE_PARAM);
	else next.searchParams.set(SOURCE_PARAM, String(id));
	return `${next.pathname}${next.search}${next.hash}`;
}

/** The account id of `/accounts/<id>`, or null for anything else. */
export function accountIdOf(param: string | undefined): number | null {
	return param !== undefined && /^\d{1,15}$/.test(param) && Number(param) > 0
		? Number(param)
		: null;
}
