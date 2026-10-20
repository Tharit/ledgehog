// "The sources" of an account page (ux/views/account.md): each importer instance the account is
// linked to, one line each, with its action: "Upload file" for a file importer. The instances come
// from `GET /api/importers/instances`, filtered by the account here (architecture §4.1: an
// account's linked importers are not a route of their own); the catalog says which importer takes
// a file. The types are the little this needs, so they follow what the API sends.

export type InstanceLike = {
	id: number;
	importer: string;
	label: string;
	disabled?: boolean;
	access?: 'owner' | 'shared';
	owner_name?: string | null;
	/** may this user run it: false is the other user's login (spec §5.11) */
	manageable?: boolean;
	accounts: readonly { account_id: number }[];
};

export type CatalogLike = { name: string; kind: 'file' | 'fetch' | string };

export type SourceLine = {
	instanceId: number;
	label: string;
	importer: string;
	kind: 'file' | 'fetch';
	disabled: boolean;
	/** set when the line is the other user's login: whose, shown in place of the action (spec §5.11) */
	otherLogin: { name: string | null } | null;
};

/** The instances `accountId` is linked to, in the order given, each with the importer's kind. */
export function sourceLines(
	accountId: number,
	instances: readonly InstanceLike[],
	catalog: readonly CatalogLike[]
): SourceLine[] {
	return instances
		.filter((instance) => instance.accounts.some((link) => link.account_id === accountId))
		.map((instance) => ({
			instanceId: instance.id,
			label: instance.label,
			importer: instance.importer,
			kind:
				catalog.find((entry) => entry.name === instance.importer)?.kind === 'file'
					? 'file'
					: 'fetch',
			disabled: instance.disabled === true,
			otherLogin: instance.manageable === false ? { name: instance.owner_name ?? null } : null
		}));
}

/** Where a file importer's upload page is, with its instance chosen. */
export function uploadHref(accountId: number, instanceId: number): string {
	return `/accounts/${accountId}/upload?instance=${instanceId}`;
}
