// How a failed list fetch is presented, routed by the error's `code` and never by its message
// (architecture §4.4, patterns §8).

export type LoadErrorPresentation = { title: string; message: string; retryable: boolean };

export function describeLoadError(code: string): LoadErrorPresentation {
	switch (code) {
		case 'network_error':
			return {
				title: 'The ledger could not be loaded',
				message: 'The server could not be reached. Check the connection and try again.',
				retryable: true
			};
		case 'validation_error':
			return {
				title: 'This filter is not valid',
				message: 'The server did not accept these filters. Clear them and try again.',
				retryable: false
			};
		case 'unauthenticated':
			return {
				title: 'You are signed out',
				message: 'Your session has ended. Sign in again to see the ledger.',
				retryable: false
			};
		default:
			return {
				title: 'The ledger could not be loaded',
				message: 'The server could not answer this request. Try again in a moment.',
				retryable: true
			};
	}
}

/** What a derived entry's tagging refusal says; also shown when `t` is pressed on one. */
export const DERIVED_NOT_TAGGABLE = 'Derived entries cannot be tagged';

/** What `r` says on a derived entry: there is no source to start a rule from. */
export const DERIVED_NO_RULE = 'Derived entries have no source to start a rule from';

/** Said after a write whose derived figures could not be recomputed (patterns §8). */
export const SETTLE_STALE = 'Derived figures may be stale until the next action.';

/** What a conflicting or vanished row/tag is answered with (patterns §8). */
export const ROWS_REFRESHED =
	'Someone else changed these rows — the list was refreshed in place; check the marked rows.';

type TagErrorLike = { code: string; details?: unknown };

function reasonOf(error: TagErrorLike): unknown {
	return (error.details as { reason?: unknown } | null | undefined)?.reason;
}

/** One failure per kind (code and reason): what a batch of failed writes needs recovering from. */
export function distinctTagErrors<T extends TagErrorLike>(errors: readonly T[]): T[] {
	const byKind = new Map(errors.map((e) => [`${e.code}:${String(reasonOf(e))}`, e]));
	return [...byKind.values()];
}

/** Where a tag write came from: one entry (picker), or a bulk action ("Tag all"). */
export type TagErrorScope = 'entry' | 'bulk';

/**
 * What the app does about a failed tag write besides saying it: refetch the loaded rows in place
 * and/or reload the tag list. Routed by `code` and `details.reason`. Never a retry or overwrite.
 */
export function tagErrorEffects(
	error: TagErrorLike,
	scope: TagErrorScope
): { rows: boolean; tags: boolean } {
	const reason = reasonOf(error);
	switch (error.code) {
		case 'not_found':
			return { rows: scope === 'entry', tags: true };
		case 'conflict':
			if (reason === 'derived_entry' || reason === 'filter_result_changed') {
				return { rows: false, tags: false };
			}
			if (reason === 'duplicate_name') return { rows: false, tags: true };
			return { rows: true, tags: false };
		default:
			return { rows: false, tags: false };
	}
}

/**
 * How a failed tag write is put to the user, routed by the error's `code` and, for a conflict, its
 * `details.reason` — never by the message (architecture §4.4, patterns §8). `name` is the tag
 * name that was being created, if any.
 */
export function describeTagError(
	error: TagErrorLike,
	scope: TagErrorScope = 'entry',
	name?: string
): string {
	const reason = reasonOf(error);
	switch (error.code) {
		case 'not_found':
			return scope === 'bulk'
				? 'This tag no longer exists — the tag list was refreshed.'
				: 'This entry or tag no longer exists — the list and the tag list were refreshed in place.';
		case 'conflict':
			if (reason === 'derived_entry') return DERIVED_NOT_TAGGABLE;
			if (reason === 'duplicate_name') {
				return `A tag named "${name ?? ''}" already exists — the tag list was refreshed.`;
			}
			if (reason === 'filter_result_changed') {
				return 'The result changed. Check it and confirm again.';
			}
			return ROWS_REFRESHED;
		case 'validation_error':
			return 'The server did not accept this. Check the filter or the name and try again.';
		case 'network_error':
			return 'The server could not be reached. Check the connection and try again.';
		case 'unauthenticated':
			return 'Your session has ended. Sign in again.';
		default:
			return 'The server could not do this. Try again in a moment.';
	}
}
