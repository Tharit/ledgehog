// What the tags screen says about a tag, in words: its size, its span, what deleting it costs.
import { formatDate } from '#lib/format/index.js';
import { plural } from '#lib/dimensions/text.js';
import type { Tag } from '#lib/types/domain.js';

/** "12 entries", "1 entry", "0 entries". */
export function entriesLabel(count: number): string {
	return plural(count, 'entry', 'entries');
}

/** "3 Mar 2026 – 9 Mar 2026" from the earliest and latest tagged entry; "no entries" for none. */
export function tagSpan(tag: Pick<Tag, 'starts_on' | 'ends_on'>): string {
	const { starts_on: from, ends_on: to } = tag;
	if (from === null || to === null) return 'no entries';
	return from === to ? formatDate(from) : `${formatDate(from)} – ${formatDate(to)}`;
}

/** What the delete decision says: how many entries lose the tag. */
export function tagDeleteText(tag: Pick<Tag, 'name' | 'entry_count'>): string {
	return tag.entry_count === 0
		? `No entry carries “${tag.name}”, so no entry changes.`
		: `${entriesLabel(tag.entry_count)} will lose the tag “${tag.name}”. The entries themselves stay.`;
}

/** "Deleted tag “x” (3 entries)." */
export function tagDeletedNotice(name: string, removed: number): string {
	return `Deleted tag “${name}” (${entriesLabel(removed)}).`;
}

/** The list indexed by id. */
export function indexTags(tags: readonly Tag[]): Map<number, Tag> {
	return new Map(tags.map((t) => [t.id, t]));
}
