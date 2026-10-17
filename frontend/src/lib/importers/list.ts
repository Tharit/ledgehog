// What a row of the instance list shows (ux/views/importers.md "The instance list").
import type { CatalogEntry, ImporterInstance } from '#lib/api/importers.js';
import { formatInstant, relativeDay, todayIso } from '#lib/format/index.js';

/** When it last ran: relative to the household's day, the absolute instant as the tooltip (patterns §3). */
export function lastRunText(
	instant: string | null,
	timeZone: string,
	locale = 'en',
	now: Date = new Date()
): { text: string; title: string } {
	if (instant === null) return { text: 'never run', title: 'This importer has not run yet.' };
	const day = todayIso(timeZone, new Date(instant));
	const relative = relativeDay(day, todayIso(timeZone, now), locale);
	return { text: relative.text, title: formatInstant(instant, timeZone, locale) };
}

/** An instance has run once it has a last run; the server still refuses a delete that raced a run. */
export function hasRuns(instance: ImporterInstance): boolean {
	return instance.last_run_at !== null;
}

/** Reset… is for an importer that keeps state, a login: a fetch importer; a file importer has none. */
export function canReset(instance: ImporterInstance, catalog: readonly CatalogEntry[]): boolean {
	return catalog.find((entry) => entry.name === instance.importer)?.kind === 'fetch';
}

/** The catalog's words for how an importer is fed. */
export function kindText(kind: CatalogEntry['kind']): string {
	return kind === 'file' ? 'takes a file' : 'fetches';
}
