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

/** The other user's name as "<Name>’s login" (spec §5.11); the fallback when it is not known. */
export function otherLoginText(ownerName: string | null): string {
	return `${ownerName ?? 'The other user'}’s login`;
}

/**
 * Whose login an instance holds, for the list and the page: "your login", "<Name>’s login" or
 * "shared" (ux/views/importers.md); null for a file importer, which holds none.
 */
export function loginText(
	instance: ImporterInstance,
	catalog: readonly CatalogEntry[]
): string | null {
	if (instance.access === 'owner') {
		return instance.manageable ? 'your login' : otherLoginText(instance.owner_name);
	}
	return catalog.find((entry) => entry.name === instance.importer)?.kind === 'fetch'
		? 'shared'
		: null;
}

/** An importer as the user reads it: the CSV importer also reads spreadsheets (csv.md §2). */
export function importerTitle(name: string): string {
	if (name === 'csv') return 'CSV or spreadsheet';
	return name === 'camt' ? 'camt (XML statement)' : name;
}

/**
 * An importer that delivers documents and no transactions: its instances have no linked accounts (a
 * document is booked onto the clearance account that takes its provider, features/documents.md §1),
 * so nothing links one.
 */
export function deliversDocumentsOnly(importer: Pick<CatalogEntry, 'emits'>): boolean {
	return importer.emits.includes('documents') && !importer.emits.includes('transactions');
}

/**
 * The catalog's words for how an importer is fed and what it delivers: "takes a file" (a file
 * importer always delivers transactions), or "fetches" with what. Rates are not named; an importer
 * that fetches only rates reads as plain "fetches".
 */
export function kindText(entry: Pick<CatalogEntry, 'kind' | 'emits'>): string {
	if (entry.kind === 'file') return 'takes a file';
	const transactions = entry.emits.includes('transactions');
	const documents = entry.emits.includes('documents');
	if (transactions && documents) return 'fetches transactions and documents';
	if (transactions) return 'fetches transactions';
	return documents ? 'fetches documents' : 'fetches';
}
