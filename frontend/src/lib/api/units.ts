// Units and the review queue (architecture §4.1): reads only.
import { request } from './http.js';
import type {
	NewUnitCount,
	ReviewQueue,
	SectionKind,
	Unit,
	UnitCommit,
	UnitDraftRequest,
	UnitPreview
} from '#lib/units/types.js';

export const QUEUE_PAGE_SIZE = 50;

/** The unit holding an entry. A 404 `not_found` means it is in none (a derived entry, or gone). */
export function getUnit(entryId: number, signal?: AbortSignal): Promise<Unit> {
	return request('GET', `/api/units/${entryId}`, { signal });
}

export type QueueOptions = {
	/** with `cursor`: continue this one section */
	section?: SectionKind;
	limit?: number;
	cursor?: string;
	signal?: AbortSignal;
};

/** The first page of every section, or the page of one `section` after `cursor`. */
export function getQueue({
	section,
	limit = QUEUE_PAGE_SIZE,
	cursor,
	signal
}: QueueOptions = {}): Promise<ReviewQueue> {
	return request('GET', '/api/units/queue', { query: { limit, section, cursor }, signal });
}

/** How many units entered the queue since `since` (a snapshot token of the queue). */
export function getNewUnitCount(since: string, signal?: AbortSignal): Promise<NewUnitCount> {
	return request('GET', '/api/units/queue/new-count', { query: { since }, signal });
}

/** What committing the draft would do; nothing is written (architecture §4.1, §6.3). */
export function previewUnit(draft: UnitDraftRequest, signal?: AbortSignal): Promise<UnitPreview> {
	return request('POST', '/api/units/preview', { body: draft, signal });
}

/** Write the draft in one transaction, then settle. A commit does not confirm: settling does. */
export function commitUnit(draft: UnitDraftRequest, signal?: AbortSignal): Promise<UnitCommit> {
	return request('POST', '/api/units/commit', { body: draft, signal });
}
