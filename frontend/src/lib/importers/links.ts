// Where the importer screens live (ux/views/importers.md).

export const IMPORTERS_PATH = '/settings/importers';

/** The page that adds an instance of the importer `name` (the catalog's name). */
export function newImporterUrl(name: string): string {
	return `${IMPORTERS_PATH}/new?importer=${encodeURIComponent(name)}`;
}

/**
 * An instance's page. `linkAccount` opens it with the "Link account" dialog already asking;
 * `added` does the same right after a new instance was saved, and says so.
 */
export function instanceUrl(
	id: number,
	options: { linkAccount?: boolean; added?: boolean } = {}
): string {
	const intent = options.added ? '?added=1' : options.linkAccount ? '?link=1' : '';
	return `${IMPORTERS_PATH}/${id}${intent}`;
}

/** How the instance page was reached (see `instanceUrl`). */
export function intentOf(search: string): 'added' | 'link' | null {
	const params = new URLSearchParams(search);
	return params.has('added') ? 'added' : params.has('link') ? 'link' : null;
}

/** The page of an instance's discovery ("Refresh accounts"). */
export function discoveryUrl(id: number): string {
	return `${IMPORTERS_PATH}/${id}/accounts`;
}

/** The upload page of an account, with the file importer's instance chosen. */
export function uploadUrl(accountId: number, instanceId: number): string {
	return `/accounts/${accountId}/upload?instance=${instanceId}`;
}

/** The account's page; with `source` it opens that row's detail (`?source=`). */
export function accountUrl(accountId: number, source?: number): string {
	return source === undefined
		? `/accounts/${accountId}`
		: `/accounts/${accountId}?source=${source}`;
}

/** The importer name in the address of the add page, or null when it is absent. */
export function importerOf(search: string): string | null {
	const name = new URLSearchParams(search).get('importer');
	return name !== null && name.trim() !== '' ? name : null;
}

/** An account id from an address or query value; null unless a positive integer. */
export function positiveId(raw: string | null | undefined): number | null {
	return raw !== null && raw !== undefined && /^\d{1,15}$/.test(raw) && Number(raw) > 0
		? Number(raw)
		: null;
}
