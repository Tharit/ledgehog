// The panel's address: `?unit=<anchor entry id>` on any page (patterns §5).

/** The query parameter that opens the panel. */
export const UNIT_PARAM = 'unit';

/** The id in `?unit=`, or null when it is absent or not a positive integer. */
export function unitIdOf(url: URL): number | null {
	const raw = url.searchParams.get(UNIT_PARAM);
	return raw !== null && /^\d{1,15}$/.test(raw) && Number(raw) > 0 ? Number(raw) : null;
}

/** The address with `unit` set to `id` (or removed), every other part kept. */
export function withUnit(url: URL, id: number | null): string {
	const next = new URL(url.href);
	if (id === null) next.searchParams.delete(UNIT_PARAM);
	else next.searchParams.set(UNIT_PARAM, String(id));
	return `${next.pathname}${next.search}${next.hash}`;
}
