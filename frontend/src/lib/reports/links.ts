// Every number of a report links to the ledger with the equivalent filter (reports.md, spec §8):
// the period as dates, the category with its descendants, the page's account and tag filters
// carried over. A whole kind lists its top-level categories as alternatives; unclassified,
// reconciliations and unconfirmed link to the ledger's own filters for them.
import type { Category } from '#lib/types/domain.js';
import { ledgerHref } from './figures.js';
import type { Kind } from './shapes.js';

/** What a figure is of: its days and the filters the page carries. */
export type Scope = {
	from: string;
	to: string;
	accountIds: readonly number[];
	tagIds: readonly number[];
};

function base(scope: Scope) {
	return {
		from: scope.from,
		to: scope.to,
		account_id: [...scope.accountIds],
		tag_id: [...scope.tagIds]
	};
}

/** A category with its descendants; `itself` only the entries booked to it. */
export function categoryHref(scope: Scope, categoryId: number, itself = false): string {
	return ledgerHref({
		...base(scope),
		category_id: [categoryId],
		category_descendants: !itself
	});
}

/** The top-level categories of a kind, as alternatives (they hold the whole kind). */
export function kindCategoryIds(categories: ReadonlyMap<number, Category>, kind: Kind): number[] {
	return [...categories.values()]
		.filter((c) => c.parent_id === null && (c.kind === 'income') === (kind === 'income'))
		.map((c) => c.id)
		.sort((a, b) => a - b);
}

export function kindHref(
	scope: Scope,
	kind: Kind,
	categories: ReadonlyMap<number, Category>
): string {
	return ledgerHref({ ...base(scope), category_id: kindCategoryIds(categories, kind) });
}

/** Entries without a category (spec §8: flows, and entries with no type yet), out, in or both. */
export function unclassifiedHref(scope: Scope, direction?: 'in' | 'out'): string {
	return ledgerHref({ ...base(scope), uncategorised: true, direction });
}

export function reconciliationsHref(scope: Scope): string {
	return ledgerHref({ ...base(scope), type: ['reconciliation'] });
}

export function unconfirmedHref(scope: Scope): string {
	return ledgerHref({ ...base(scope), flag: ['unconfirmed'] });
}

// ---- By account: the drill-downs of one account's link (reports.md, Tab 2). Each carries the
// period and the page's tags; the page has no account filter, the link's account is the filter.

function ofAccount(scope: Scope, accountId: number) {
	return { ...base(scope), account_id: [accountId] };
}

/** A category (with its descendants) on one account; "Other" lists the categories it holds. */
export function accountCategoryHref(
	scope: Scope,
	accountId: number,
	categoryIds: readonly number[]
): string {
	return ledgerHref({ ...ofAccount(scope, accountId), category_id: [...categoryIds] });
}

/** What one account has that has no category yet, out or in. */
export function accountUnclassifiedHref(
	scope: Scope,
	accountId: number,
	direction: 'in' | 'out'
): string {
	return ledgerHref({ ...ofAccount(scope, accountId), uncategorised: true, direction });
}

export function accountReconciliationsHref(scope: Scope, accountId: number): string {
	return ledgerHref({ ...ofAccount(scope, accountId), type: ['reconciliation'] });
}

/** The transfer legs that leave `from` for `to`. */
export function transferHref(scope: Scope, from: number, to: number): string {
	return ledgerHref({
		...ofAccount(scope, from),
		counter_account_id: [to],
		type: ['transfer'],
		direction: 'out'
	});
}
