// The tags as the choices of a picker: sorted by name, each a chip in its colour.
import { resolveTag } from '#lib/theme/resolve.js';
import type { Tag } from '#lib/types/domain.js';

export type TagItem = { id: number; label: string; color: string | null; tag: true };

export function tagItems(tags: readonly Tag[]): TagItem[] {
	return [...tags]
		.sort((a, b) => a.name.localeCompare(b.name))
		.map((tag) => ({ id: tag.id, label: tag.name, color: resolveTag(tag).color, tag: true }));
}
