// The plan page's logic (ux/views/sync.md "Starting"): what the plan read says in words, the part of
// it an address narrows to, and the request items a start sends. Nothing is selected: "Start sync"
// syncs every login the plan shows, except one that another sync holds.
import type { PlanAccount, PlanInstance, SyncItem } from '#lib/api/sync.js';

/** The part of the plan an address names: `?instance=` alone, or with `&account=`. */
export type Narrowing = { instanceId: number | null; accountId: number | null };

export function narrowingOf(search: string): Narrowing {
	const params = new URLSearchParams(search);
	const id = (name: string) => {
		const raw = params.get(name);
		return raw !== null && /^\d{1,15}$/.test(raw) && Number(raw) > 0 ? Number(raw) : null;
	};
	const instanceId = id('instance');
	// an account alone names nothing: it belongs to a login
	return { instanceId, accountId: instanceId === null ? null : id('account') };
}

/** The address of the plan narrowed to a login, or to one of its accounts. */
export function narrowedPlanUrl(instanceId: number, accountId?: number | null): string {
	const account = accountId === undefined || accountId === null ? '' : `&account=${accountId}`;
	return `/sync?instance=${instanceId}${account}`;
}

export function isNarrowed(narrowing: Narrowing): boolean {
	return narrowing.instanceId !== null;
}

/**
 * The plan as the page shows it: a login with nothing to fetch is not a block; a narrowed plan has
 * only that login, and with an account only that account (documents are not part of it).
 */
export function narrowPlan(plan: readonly PlanInstance[], narrowing: Narrowing): PlanInstance[] {
	return plan
		.filter((i) => narrowing.instanceId === null || i.instance_id === narrowing.instanceId)
		.map((i) =>
			narrowing.accountId === null
				? i
				: {
						...i,
						accounts: i.accounts.filter((a) => a.account_id === narrowing.accountId),
						documents_since: null
					}
		)
		.filter((i) => i.accounts.length > 0 || i.documents_since !== null);
}

/** The instances a start would run: the ones no other sync holds. */
export function startable(plan: readonly PlanInstance[]): PlanInstance[] {
	return plan.filter((i) => !i.busy);
}

/** The plan's start of an account in words (`since_source`, ux/views/sync.md). */
export function sinceSourceText(source: PlanAccount['since_source']): string {
	switch (source) {
		case 'coverage':
			return 'continues from the last sync, with an overlap';
		case 'latest_entry':
			return 'the day after its latest entry';
		case 'importer_default':
			return "the importer's default";
	}
}

/**
 * The items a start sends: per login that is not busy, per account `{instance_id, account_id}` with a
 * `since` only where the account is editable and the user changed its start, and one documents item
 * where the login has documents. `starts` holds what the user typed, by account id.
 */
export function planItems(
	plan: readonly PlanInstance[],
	starts: Readonly<Record<number, string>> = {}
): SyncItem[] {
	return startable(plan).flatMap((instance) => [
		...instance.accounts.map((account): SyncItem => {
			const chosen = starts[account.account_id];
			const item: SyncItem = { instance_id: instance.instance_id, account_id: account.account_id };
			if (account.editable && chosen && chosen !== account.since) item.since = chosen;
			return item;
		}),
		...(instance.documents_since !== null
			? [{ instance_id: instance.instance_id, kind: 'documents' as const }]
			: [])
	]);
}
