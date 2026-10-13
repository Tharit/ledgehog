// State of the categories screen: the flat list, the tree built from it, and the writes (create,
// rename, look, move, reorder, delete, merge). The list is reloaded after every write, so what is
// shown is what the server has (patterns §1); the ledger loads its own lookups when it opens, so it
// sees the new names and colours without a reload. No domain computation here.
import {
	ApiError,
	createCategory,
	deleteCategory,
	listCategories,
	mergeCategory,
	updateCategory
} from '#lib/api/index.js';
import { attempt } from '#lib/dimensions/attempt.js';
import { needsReload, type Outcome } from '#lib/dimensions/errors.js';
import { DeleteFlow, MergeFlow } from '#lib/dimensions/flows.svelte.js';
import { plural } from '#lib/dimensions/text.js';
import { SETTLE_STALE } from '#lib/ledger/errors.js';
import { NO_IDS } from '#lib/ledger/patch.js';
import { lookupsStore } from '#lib/stores/lookups.svelte.js';
import type { Category, CategoryDeleteOut, CategoryMergeOut } from '#lib/types/domain.js';
import {
	buildTree,
	indexById,
	moveWithinSiblings,
	nextSortOrder,
	siblingsOf,
	toggled,
	type CategoryKind
} from './tree.js';

export type CategoriesStatus = 'loading' | 'ready' | 'error';
export type CategoriesNotice = { text: string; error: boolean };

/** What a presentation change sets: `null` clears (inherit), absent stays. */
export type LookPatch = { icon?: string | null; color?: string | null };

export class CategoriesStore {
	categories = $state.raw<Category[]>([]);
	status = $state<CategoriesStatus>('loading');
	error = $state.raw<ApiError | null>(null);
	notice = $state.raw<CategoriesNotice | null>(null);
	/** the categories whose children are folded away */
	collapsed = $state.raw<ReadonlySet<number>>(NO_IDS);

	readonly byId = $derived(indexById(this.categories));
	readonly tree = $derived(buildTree(this.categories));

	readonly merge = new MergeFlow<CategoryMergeOut>({
		subject: 'category',
		preview: (id, into) => attempt(() => mergeCategory(id, into, { dryRun: true })),
		commit: (id, into, expectedCount) => attempt(() => mergeCategory(id, into, { expectedCount })),
		done: (id, out) => void this.#merged(id, out),
		reload: () => this.load()
	});

	readonly remove = new DeleteFlow<CategoryDeleteOut>({
		subject: 'category',
		preview: (id) => attempt(() => deleteCategory(id, { dryRun: true })),
		commit: (id) => attempt(() => deleteCategory(id)),
		done: (id, out) => void this.#deleted(out),
		reload: () => this.load()
	});

	/** Load the list. `quiet` keeps what is shown (a reload after a write). */
	async load(quiet = false): Promise<void> {
		if (!quiet) this.status = 'loading';
		try {
			this.categories = await listCategories();
			lookupsStore.setCategories(this.categories);
			this.status = 'ready';
			this.error = null;
		} catch (error) {
			if (quiet && this.status === 'ready') return;
			this.error =
				error instanceof ApiError
					? error
					: new ApiError(0, 'network_error', 'The server could not be reached.');
			this.status = 'error';
		}
	}

	notify(text: string, error = false): void {
		this.notice = { text, error };
	}

	toggle(id: number): void {
		this.collapsed = toggled(this.collapsed, id);
	}

	expand(id: number): void {
		if (!this.collapsed.has(id)) return;
		this.toggle(id);
	}

	/** After a write: reload the list; a settle that failed is a quiet notice (architecture §5.2). */
	async #after<T extends { settle?: { error: string | null } | null }>(
		outcome: Outcome<T>
	): Promise<Outcome<T>> {
		if (outcome.ok) {
			await this.load(true);
			if (outcome.value.settle?.error) this.notify(SETTLE_STALE);
		} else if (needsReload(outcome.failure)) {
			await this.load(true);
		}
		return outcome;
	}

	/** A top-level category (`kind`) or a child (`parentId`; it takes the parent's kind). */
	async create(
		name: string,
		where: { kind: CategoryKind } | { parentId: number }
	): Promise<Outcome<Category>> {
		const parentId = 'parentId' in where ? where.parentId : null;
		const siblings = this.categories.filter((c) =>
			'parentId' in where
				? c.parent_id === where.parentId
				: c.parent_id === null && c.kind === where.kind
		);
		const outcome = await this.#after(
			await attempt(() =>
				createCategory({
					name,
					...('parentId' in where ? { parent_id: where.parentId } : { kind: where.kind }),
					sort_order: nextSortOrder(siblings)
				})
			)
		);
		if (outcome.ok) {
			if (parentId !== null) this.expand(parentId);
			return { ok: true, value: outcome.value.category };
		}
		return outcome;
	}

	async rename(id: number, name: string): Promise<Outcome<Category>> {
		return this.#update(id, { name });
	}

	async setLook(id: number, look: LookPatch): Promise<Outcome<Category>> {
		return this.#update(id, look);
	}

	/** Under another parent of its kind, or to the top level (`null`), after its new siblings. */
	async reparent(id: number, parentId: number | null): Promise<Outcome<Category>> {
		const category = this.byId.get(id);
		if (!category) return this.#update(id, { parent_id: parentId });
		const siblings = this.categories.filter(
			(c) => c.id !== id && c.parent_id === parentId && c.kind === category.kind
		);
		const outcome = await this.#update(id, {
			parent_id: parentId,
			sort_order: nextSortOrder(siblings)
		});
		if (outcome.ok && parentId !== null) this.expand(parentId);
		return outcome;
	}

	/** One place up or down among its siblings; the rows that change number are written in turn. */
	async move(id: number, direction: 'up' | 'down'): Promise<Outcome<null>> {
		const category = this.byId.get(id);
		if (!category) return { ok: true, value: null };
		const updates = moveWithinSiblings(siblingsOf(category, this.categories), id, direction);
		let failed: Outcome<null> | null = null;
		for (const update of updates) {
			const result = await attempt(() =>
				updateCategory(update.id, { sort_order: update.sort_order })
			);
			if (!result.ok) {
				failed = result;
				break;
			}
		}
		await this.load(true);
		return failed ?? { ok: true, value: null };
	}

	async #update(
		id: number,
		body: Parameters<typeof updateCategory>[1]
	): Promise<Outcome<Category>> {
		const outcome = await this.#after(await attempt(() => updateCategory(id, body)));
		return outcome.ok ? { ok: true, value: outcome.value.category } : outcome;
	}

	async #merged(sourceId: number, out: CategoryMergeOut): Promise<void> {
		const source = this.byId.get(sourceId)?.name ?? 'the category';
		const target = this.byId.get(out.target_id)?.name ?? 'the target';
		await this.load(true);
		const text = `Merged ${source} into ${target} (${plural(out.entry_count, 'entry', 'entries')}, ${plural(out.rule_ids.length, 'rule', 'rules')}).`;
		this.notify(out.settle?.error ? `${text} ${SETTLE_STALE}` : text);
	}

	async #deleted(out: CategoryDeleteOut): Promise<void> {
		await this.load(true);
		this.notify(`Deleted ${out.category.name}.`);
	}
}
