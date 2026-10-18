// Units and the review queue (architecture §4.1): reads only.
import { request } from './http.js';
import type {
	QueueCount,
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

/** How many units can be acted on now (pending review and needs an account): the Review item's count. */
export async function getQueueCount(signal?: AbortSignal): Promise<number> {
	const out = await request<QueueCount>('GET', '/api/units/queue/count', { signal });
	return out.count;
}

/** What committing the draft would do; nothing is written (architecture §4.1, §6.3). */
export function previewUnit(
	draft: UnitDraftRequest,
	signal?: AbortSignal,
	/** widen the window the partner offers are listed for (1 to 90 days; default: the matching window) */
	windowDays?: number | null
): Promise<UnitPreview> {
	return request('POST', '/api/units/preview', {
		body: draft,
		query: windowDays ? { window_days: windowDays } : undefined,
		signal
	});
}

/** Write the draft in one transaction, then settle. A commit does not confirm: settling does. */
export function commitUnit(
	draft: UnitDraftRequest,
	signal?: AbortSignal,
	/** the window the preview was widened to: it decides which proposals the commit takes */
	windowDays?: number | null
): Promise<UnitCommit> {
	return request('POST', '/api/units/commit', {
		body: draft,
		query: windowDays ? { window_days: windowDays } : undefined,
		signal
	});
}
