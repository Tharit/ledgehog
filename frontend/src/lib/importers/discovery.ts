// What a discovery's rows say (ux/views/importers.md "Refresh accounts", spec §5.4): each account the
// login reaches is in one state, decided in the order the spec lists them, and the add dialog is
// prefilled from what the bank reported. Pure: no I/O.
import type { AccountKind } from '#lib/api/types.js';
import type { AddAccountOptions } from '#lib/accounts/controller.svelte.js';
import { ACCOUNT_KINDS } from '#lib/accounts/kinds.js';
import type { CatalogEntry, DiscoveryEntry, ImporterInstance } from '#lib/types/domain.js';

/**
 * The state of one row, in the spec's order: *linked* (to the account named); *nothing to fetch*
 * (the bank offers neither bookings nor a balance); *closed* (it matches a closed account, which is
 * not offered); *match* (it matches an open account, offered "Link…"); *new* (not in the ledger yet,
 * offered "Add and link").
 */
export type RowState =
	| { kind: 'linked'; accountId: number }
	| { kind: 'nothing_to_fetch' }
	| { kind: 'closed'; accountId: number }
	| { kind: 'match'; accountId: number }
	| { kind: 'new' };

export function rowState(entry: DiscoveryEntry): RowState {
	if (entry.linked_account_id !== null)
		return { kind: 'linked', accountId: entry.linked_account_id };
	if (entry.account.capabilities.length === 0) return { kind: 'nothing_to_fetch' };
	const match = entry.matches_account;
	if (match) {
		return match.closed
			? { kind: 'closed', accountId: match.id }
			: { kind: 'match', accountId: match.id };
	}
	return { kind: 'new' };
}

export const NOTHING_TO_FETCH_TEXT =
	'The bank offers neither bookings nor a balance for this account.';

/**
 * "Refresh accounts" replaces "Link account" for an instance of an importer that fetches and emits
 * transactions; every other instance keeps "Link account" (a file importer is never asked for a
 * reference).
 */
export function canRefreshAccounts(
	instance: Pick<ImporterInstance, 'importer' | 'emits'>,
	catalog: readonly CatalogEntry[]
): boolean {
	return (
		instance.emits.includes('transactions') &&
		catalog.find((entry) => entry.name === instance.importer)?.kind === 'fetch'
	);
}

/** The kind the bank hints at, when it is one this ledger has. */
export function kindOfHint(hint: string | null): AccountKind | undefined {
	return ACCOUNT_KINDS.find((k) => k.kind === hint)?.kind;
}

/**
 * The add-account dialog for a row that is not in the ledger yet: prefilled with the name, the
 * kind from the hint, the currency (locked: the pocket has it) and the reference, ending "Add and
 * link".
 */
export function addAndLinkOptions(
	entry: DiscoveryEntry,
	onadded: AddAccountOptions['onadded']
): AddAccountOptions {
	const { name, kind_hint, currency, external_ref } = entry.account;
	return {
		name,
		// no (known) hint: a bank account found by discovery is not money held by hand
		kind: kindOfHint(kind_hint) ?? 'checking',
		...(currency ? { currency, currencyHint: 'The currency the bank reports for it.' } : {}),
		externalRef: external_ref,
		verb: 'Add and link',
		busyVerb: 'Adding…',
		description: 'It is added to the ledger and linked to this login at once.',
		onadded
	};
}
