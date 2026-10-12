// Tags: create one, tag or untag one entry, and tag everything a filter selects (previewed first).
import { request } from './http.js';
import type { EntryFilter, EntryTagsOut, TagApplyBody, TagApplyOut, TagWriteOut } from './types.js';

export type ApplyControls = {
	/** only count, change nothing */
	dryRun?: boolean;
	/** the preview's `newly_tagged`; the server refuses the write if the result moved since */
	expectedCount?: number;
	/** an empty filter would tag the whole ledger; the UI never sets this */
	all?: boolean;
};

/** The apply body: the list's filter in the same names as its query parameters, plus the controls. */
export function applyBody(
	filter: EntryFilter,
	{ dryRun = false, expectedCount, all = false }: ApplyControls = {}
): TagApplyBody {
	const text = filter.q.trim();
	return {
		from: filter.from ?? null,
		to: filter.to ?? null,
		account_id: [...filter.account_id],
		category_id: [...filter.category_id],
		category_descendants: filter.category_descendants,
		uncategorised: filter.uncategorised,
		payee_id: [...filter.payee_id],
		tag_id: [...filter.tag_id],
		amount_min: filter.amount_min ?? null,
		amount_max: filter.amount_max ?? null,
		currency: filter.currency ?? null,
		direction: filter.direction ?? null,
		q: text === '' ? null : text,
		type: [...filter.type] as TagApplyBody['type'],
		flag: [...filter.flag] as TagApplyBody['flag'],
		all,
		dry_run: dryRun,
		expected_count: expectedCount ?? null
	};
}

/** A new tag; its colour is optional. */
export function createTag(name: string, color: string | null = null): Promise<TagWriteOut> {
	return request('POST', '/api/ledger/tags', { body: { name, color } });
}

/** Tag every entry the body's filter selects (or preview it with `dry_run`). */
export function applyTag(
	tagId: number,
	body: TagApplyBody,
	signal?: AbortSignal
): Promise<TagApplyOut> {
	return request('POST', `/api/ledger/tags/${tagId}/apply`, { body, signal });
}

/** Idempotent. The answer holds the entry's tag ids as they are now. */
export function tagEntry(entryId: number, tagId: number): Promise<EntryTagsOut> {
	return request('PUT', `/api/ledger/entries/${entryId}/tags/${tagId}`);
}

/** Idempotent. */
export function untagEntry(entryId: number, tagId: number): Promise<EntryTagsOut> {
	return request('DELETE', `/api/ledger/entries/${entryId}/tags/${tagId}`);
}
