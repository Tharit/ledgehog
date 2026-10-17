// Where the importer screens live (ux/views/importers.md).

export const IMPORTERS_PATH = '/settings/importers';

/** The page that adds an instance of the importer `name` (the catalog's name). */
export function newImporterUrl(name: string): string {
	return `${IMPORTERS_PATH}/new?importer=${encodeURIComponent(name)}`;
}

/** An instance's page; `linkAccount` opens it with the "Link account" dialog already asking. */
export function instanceUrl(id: number, options: { linkAccount?: boolean } = {}): string {
	return `${IMPORTERS_PATH}/${id}${options.linkAccount ? '?link=1' : ''}`;
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
