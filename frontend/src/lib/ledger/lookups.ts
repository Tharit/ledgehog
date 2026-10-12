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
