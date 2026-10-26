// The example of the rule editor: an entry the user looks at while writing the conditions. It
// fills in nothing and changes nothing that is saved (spec §5.9); it only has to be shown, found
// and remembered in the address.
import type { Entry } from '#lib/api/types.js';
import {
	FIELD_LABELS,
	PAYEE_FIELD,
	SOURCE_FIELDS,
	SOURCE_TEXT_FIELD,
	type SourceField
} from './conditions.js';

export const EXAMPLE_PARAM = 'from';

/** The example's entry id in a query string, or null when there is none or it is not an id. */
export function parseExampleId(search: string): number | null {
	const id = Number(new URLSearchParams(search).get(EXAMPLE_PARAM));
	return Number.isSafeInteger(id) && id > 0 ? id : null;
}

/** The parts of an address `withExample` needs: a `URL`, the page's `url`, or a string. */
type Address = string | Pick<URL, 'pathname' | 'search' | 'hash'>;

/** The address with the example set (or removed), everything else in it kept as it is. */
export function withExample(address: Address, id: number | null): string {
	const text =
		typeof address === 'string' ? address : `${address.pathname}${address.search}${address.hash}`;
	const parsed = new URL(text, 'http://localhost');
	if (id === null) parsed.searchParams.delete(EXAMPLE_PARAM);
	else parsed.searchParams.set(EXAMPLE_PARAM, String(id));
	return `${parsed.pathname}${parsed.search}${parsed.hash}`;
}

export type SourceRow = { field: SourceField; label: string; value: string | null };

/**
 * The fields of an entry's source transaction a rule can read, one row each, in the editor's
 * order; a field the source lacks has no value. Null without a source transaction.
 */
export function sourceRows(entry: Pick<Entry, 'source'>): SourceRow[] | null {
	const source = entry.source;
	if (!source) return null;
	return SOURCE_FIELDS.map((field) => {
		const text = source[field];
		return { field, label: FIELD_LABELS[field], value: textOrNull(text) };
	});
}

export type EntryRow = {
	field: typeof PAYEE_FIELD | typeof SOURCE_TEXT_FIELD;
	label: string;
	value: string | null;
};

/**
 * The fields of the entry itself a rule can read, one row each: its own source text, and the payee
 * (category rules read it). The account is shown with the entry's basics above.
 */
export function entryRows(
	entry: Pick<Entry, 'payee_id' | 'source_text'>,
	payeeName: (id: number) => string | undefined = () => undefined
): EntryRow[] {
	const payee = entry.payee_id === null ? null : (payeeName(entry.payee_id) ?? null);
	return [
		{
			field: SOURCE_TEXT_FIELD,
			label: FIELD_LABELS[SOURCE_TEXT_FIELD],
			value: textOrNull(entry.source_text)
		},
		{ field: PAYEE_FIELD, label: 'Payee', value: payee }
	];
}

function textOrNull(text: string | null | undefined): string | null {
	return text === undefined || text === null || text === '' ? null : text;
}

/** Shown in place of the table for an entry without a source transaction. */
export const NO_SOURCE_NOTE = 'This entry has no source transaction: rules read imported fields.';
