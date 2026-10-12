// Pure helpers of the "Tag all…" dialog: which marked rows an extra pass would tag, and the words.
import { formatCount } from '#lib/format/index.js';
import type { Entry } from '#lib/types/domain.js';
import { SETTLE_STALE } from './errors.js';
import { isDerivedType } from './types.js';

/** "1 row" / "3 rows". */
export function rowsPhrase(n: number, locale: string): string {
	return `${formatCount(n, locale)} ${n === 1 ? 'row' : 'rows'}`;
}

/**
 * The marked rows (the user changed them and the tag filter no longer matches them) that tagging
 * with `tagId` would still change: derived entries cannot be tagged, tagged ones need nothing.
 */
export function eligibleMarkedRows(marked: readonly Entry[], tagId: number): Entry[] {
	return marked.filter((e) => !isDerivedType(e.type) && !e.tag_ids.includes(tagId));
}

/** Why the filter does not include the rows that are still shown. */
export function markedExplanation(n: number, locale: string): string {
	return n === 1
		? '1 row still shown was changed by you and no longer matches this filter, so the filter does not include it.'
		: `${formatCount(n, locale)} rows still shown were changed by you and no longer match this filter, so the filter does not include them.`;
}

/** The checkbox that adds the marked rows to the operation. */
export function extrasLabel(n: number, locale: string): string {
	return n === 1
		? 'Also tag the 1 row you changed that is still shown'
		: `Also tag the ${formatCount(n, locale)} rows you changed that are still shown`;
}

const entries = (n: number, locale: string) =>
	`${formatCount(n, locale)} ${n === 1 ? 'entry' : 'entries'}`;

/** What was done, in one sentence without a trailing stop. `applied` and `extras` may be 0. */
export function taggedSummary(
	tagName: string,
	applied: number,
	extras: number,
	locale: string
): string {
	if (applied > 0 && extras > 0) {
		return `Tagged ${entries(applied, locale)} with "${tagName}" and ${rowsPhrase(extras, locale)} you changed`;
	}
	if (extras > 0) return `Tagged ${rowsPhrase(extras, locale)} you changed with "${tagName}"`;
	return `Tagged ${entries(applied, locale)} with "${tagName}"`;
}

/** The quiet notice after a full success; `stale` appends the settle sentence. */
export function taggedNotice(
	tagName: string,
	applied: number,
	extras: number,
	stale: boolean,
	locale: string
): string {
	const text = taggedSummary(tagName, applied, extras, locale);
	return stale ? `${text}. ${SETTLE_STALE}` : text;
}

/** The dialog line after the extra pass failed for some rows. `reasons` are already in words. */
export function partialReport(
	tagged: number,
	total: number,
	reasons: readonly string[],
	locale: string
): string {
	const failed = total - tagged;
	const why = [...new Set(reasons)].join(' ');
	return `Tagged ${formatCount(tagged, locale)} of ${formatCount(total, locale)} of the rows you changed; ${formatCount(failed, locale)} failed (${why})`;
}
