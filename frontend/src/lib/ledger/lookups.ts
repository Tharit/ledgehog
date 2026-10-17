// The lists the ledger resolves ids against, indexed by id.
import type { Account, Category, Payee, Tag } from '#lib/types/domain.js';

export type Lookups = {
	accounts: ReadonlyMap<number, Account>;
	categories: ReadonlyMap<number, Category>;
	payees: ReadonlyMap<number, Payee>;
	tags: ReadonlyMap<number, Tag>;
};

function byId<T extends { id: number }>(items: readonly T[]): Map<number, T> {
	return new Map(items.map((item) => [item.id, item]));
}

export function buildLookups(lists: {
	accounts?: readonly Account[];
	categories?: readonly Category[];
	payees?: readonly Payee[];
	tags?: readonly Tag[];
}): Lookups {
	return {
		accounts: byId(lists.accounts ?? []),
		categories: byId(lists.categories ?? []),
		payees: byId(lists.payees ?? []),
		tags: byId(lists.tags ?? [])
	};
}

export function emptyLookups(): Lookups {
	return buildLookups({});
}

/** The lookups with one more tag (just created), the rest untouched. */
export function withTag(lookups: Lookups, tag: Tag): Lookups {
	return { ...lookups, tags: new Map([...lookups.tags, [tag.id, tag]]) };
}

/** The lookups with the tag list replaced by a fresh one, the rest untouched. */
export function withTags(lookups: Lookups, tags: readonly Tag[]): Lookups {
	return { ...lookups, tags: byId(tags) };
}

/** The lookups with the category list replaced, the rest untouched. */
export function withCategories(lookups: Lookups, categories: readonly Category[]): Lookups {
	return { ...lookups, categories: byId(categories) };
}

/** The lookups with the payee list replaced, the rest untouched. */
export function withPayees(lookups: Lookups, payees: readonly Payee[]): Lookups {
	return { ...lookups, payees: byId(payees) };
}

/** The lookups with one more account (just added), the rest untouched. */
export function withAccount(lookups: Lookups, account: Account): Lookups {
	return { ...lookups, accounts: new Map([...lookups.accounts, [account.id, account]]) };
}

/** The lookups with the account list replaced by a fresh one (its facts moved), the rest untouched. */
export function withAccounts(lookups: Lookups, accounts: readonly Account[]): Lookups {
	return { ...lookups, accounts: byId(accounts) };
}
