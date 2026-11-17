// What an entry is called in one line (patterns §4.1): its description or source text, else its
// payee or counterparty name, else its purpose. Built from the row's derived `display_description`
// and `display_payee`, so the list and every one-line name agree.
import type { Entry, Payee } from '#lib/types/domain.js';

type Named = Pick<Entry, 'display_description' | 'display_payee'>;

/**
 * The one-line name of an entry, or null when nothing has text. A payee's name comes from the
 * payee list; without it (or when the payee is not in it) that step is skipped.
 */
export function entryName(entry: Named, payees?: ReadonlyMap<number, Payee>): string | null {
	const description = entry.display_description;
	if (description && description.from !== 'purpose') return description.text;
	const payee = entry.display_payee;
	if (payee) {
		const name = payee.from === 'payee' ? payees?.get(payee.payee_id)?.name : payee.text;
		if (name?.trim()) return name;
	}
	return description?.text ?? null;
}
