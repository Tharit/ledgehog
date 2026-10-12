// The lists the rule screens resolve ids against (targets, payee conditions, preview rows):
// accounts, categories and payees. A list that cannot be loaded is simply empty and named, so the
// screen can say so in one quiet line.
import { listAccounts, listCategories, listPayees } from '#lib/api/index.js';
import { buildLookups, type Lookups } from '#lib/ledger/lookups.js';

export async function loadRuleLookups(): Promise<{ lookups: Lookups; failed: string[] }> {
	const names = ['accounts', 'categories', 'payees'];
	const results = await Promise.allSettled([listAccounts(), listCategories(), listPayees()]);
	const value = <T>(result: PromiseSettledResult<T[]>): T[] =>
		result.status === 'fulfilled' ? result.value : [];
	return {
		lookups: buildLookups({
			accounts: value(results[0]),
			categories: value(results[1]),
			payees: value(results[2])
		}),
		failed: names.filter((_, i) => results[i].status === 'rejected')
	};
}
