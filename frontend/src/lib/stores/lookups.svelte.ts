// The lists ids resolve against everywhere (accounts, categories, payees, tags): ONE store for the
// ledger, the review queue, the unit panel and the settings screens, so a name changed or a tag
// created in one place is seen in all of them. Loaded once on first use; a failed list is simply
// empty and named (`failed`). `reload` refetches all four (after a `stale_reference`, after writes
// that change them); the settings screens hand over the lists they already fetched.
import { listAccounts, listCategories, listPayees, listTags } from '#lib/api/index.js';
import {
	buildLookups,
	emptyLookups,
	withCategories,
	withPayees,
	withTag,
	withTags,
	type Lookups
} from '#lib/ledger/lookups.js';
import type { Category, Payee, Tag } from '#lib/types/domain.js';

const NAMES = ['accounts', 'categories', 'payees', 'tags'] as const;

export class LookupsStore {
	lookups = $state.raw<Lookups>(emptyLookups());
	/** the lists that could not be loaded (their names) */
	failed = $state.raw<string[]>([]);
	loaded = $state(false);

	#inflight: Promise<void> | null = null;

	/** Load the four lists once; later calls share the first one. */
	ensure(): Promise<void> {
		if (this.loaded) return Promise.resolve();
		return (this.#inflight ??= this.#fetch());
	}

	/** Fetch the four lists again (they replace what is held; a failing list keeps its old value). */
	reload(): Promise<void> {
		return this.#fetch();
	}

	async #fetch(): Promise<void> {
		const results = await Promise.allSettled([
			listAccounts(),
			listCategories(),
			listPayees(),
			listTags()
		]);
		const prior = this.lookups;
		const value = <T extends { id: number }>(
			i: number,
			held: ReadonlyMap<number, T>
		): readonly T[] => {
			const result = results[i] as PromiseSettledResult<readonly T[] | undefined>;
			return result.status === 'fulfilled' ? (result.value ?? []) : [...held.values()];
		};
		this.lookups = buildLookups({
			accounts: value(0, prior.accounts),
			categories: value(1, prior.categories),
			payees: value(2, prior.payees),
			tags: value(3, prior.tags)
		});
		this.failed = NAMES.filter((_, i) => results[i].status === 'rejected');
		this.loaded = true;
		this.#inflight = null;
	}

	async reloadTags(): Promise<void> {
		try {
			this.lookups = withTags(this.lookups, await listTags());
		} catch {
			// the list held stays
		}
	}

	/** A tag created here joins the list. */
	addTag(tag: Tag): void {
		this.lookups = withTag(this.lookups, tag);
	}

	/** The settings screens fetched these lists: take them over without another request. */
	setCategories(categories: readonly Category[]): void {
		this.lookups = withCategories(this.lookups, categories);
	}

	setPayees(payees: readonly Payee[]): void {
		this.lookups = withPayees(this.lookups, payees);
	}

	/** Forget everything (tests, sign-out). */
	reset(): void {
		this.lookups = emptyLookups();
		this.failed = [];
		this.loaded = false;
		this.#inflight = null;
	}
}

export const lookupsStore = new LookupsStore();
