// Category writes (spec §3.5): create, update, delete and merge. Delete and merge are previewed
// with `dry_run`; the real merge carries the preview's `entry_count` as `expected_count`. Failures
// are ApiErrors routed by `code` (and `details.reason` for a 409 `conflict`): see
// `#lib/dimensions/errors.js`.
import { request } from './http.js';
import type {
	CategoryCreateBody,
	CategoryDeleteOut,
	CategoryMergeOut,
	CategoryUpdateBody,
	CategoryWriteOut
} from './types.js';

export type MergeControls = {
	/** only report what would happen, change nothing */
	dryRun?: boolean;
	/** the preview's `entry_count`; the server refuses the write if the result moved since */
	expectedCount?: number;
};

export function createCategory(body: CategoryCreateBody): Promise<CategoryWriteOut> {
	return request('POST', '/api/ledger/categories', { body });
}

/** Absent fields stay; `null` clears an icon or colour, `parent_id: null` makes it top-level. */
export function updateCategory(id: number, body: CategoryUpdateBody): Promise<CategoryWriteOut> {
	return request('PUT', `/api/ledger/categories/${id}`, { body });
}

/** Refused with 409 `category_in_use` while anything references it; `dryRun` says what stands in the way. */
export function deleteCategory(
	id: number,
	{ dryRun = false }: { dryRun?: boolean } = {}
): Promise<CategoryDeleteOut> {
	return request('DELETE', `/api/ledger/categories/${id}`, { query: { dry_run: dryRun } });
}

export function mergeCategory(
	id: number,
	into: number,
	{ dryRun = false, expectedCount }: MergeControls = {}
): Promise<CategoryMergeOut> {
	return request('POST', `/api/ledger/categories/${id}/merge`, {
		body: { into, dry_run: dryRun, expected_count: expectedCount ?? null }
	});
}
