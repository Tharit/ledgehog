// Fixtures for the entry-form dialog tests.
import type {
	SourceDeleteOut,
	SourceEditEffects,
	SourceEditOut,
	SourceWriteOut
} from '#lib/api/types.js';
import { buildLookups } from '#lib/ledger/lookups.js';
import { account, entry } from '#lib/ledger/fixtures.js';
import { lookupsStore } from '#lib/stores/lookups.svelte.js';
import { session } from '#lib/stores/session.svelte.js';
import type { Entry } from '#lib/types/domain.js';

export const cash = account({ id: 1, name: 'Cash', kind: 'cash', synced: false, sort_order: 1 });
export const loan = account({
	id: 3,
	name: 'Hand loan',
	kind: 'loan',
	synced: false,
	sort_order: 2
});
export const giro = account({ id: 2, name: 'Giro', synced: true, sort_order: 0 });

/** Accounts known and the viewer signed in, as the layout leaves them. */
export function signedIn(accounts = [giro, cash, loan]): void {
	session.user = { id: 1, login: 'ada', display_name: 'Ada' };
	session.config = {
		base_currency: 'EUR',
		timezone: 'UTC',
		locale: 'en',
		max_rate_age_days: 7,
		matching_window_days: 7,
		document_window_back_days: 60,
		document_window_ahead_days: 7,
		oidc_offered: false,
		oidc_enforced: false
	};
	lookupsStore.lookups = buildLookups({ accounts });
	lookupsStore.loaded = true;
}

export const NO_SETTLE_ERROR = { error: null, touched_entry_ids: [] };

export function written(over: Partial<SourceWriteOut> = {}): SourceWriteOut {
	return {
		source_transaction_id: 50,
		anchor_entry_id: 77,
		entries: [],
		units: [],
		removed_entry_ids: [],
		settle: NO_SETTLE_ERROR,
		...over
	};
}

export const noEffects: SourceEditEffects = {
	collapsed_entry_ids: [],
	unpaired_entry_ids: [],
	deleted_entry_ids: [],
	followed_entry_ids: [],
	rederived_entry_ids: [],
	returned_to_review_ids: [],
	versions: [{ entry_id: 5, version: 3 }]
};

export function edited(over: Partial<SourceEditEffects> = {}, dryRun = true): SourceEditOut {
	return {
		dry_run: dryRun,
		source_transaction_id: 50,
		effects: { ...noEffects, ...over },
		anchor_entry_id: dryRun ? null : 5,
		entries: [],
		units: [],
		removed_entry_ids: [],
		settle: dryRun ? null : NO_SETTLE_ERROR
	};
}

export function deleted(over: Partial<SourceDeleteOut> = {}): SourceDeleteOut {
	return {
		dry_run: true,
		source_transaction_id: 50,
		counts: {
			entries: 1,
			confirmed_entries: 1,
			tagged_entries: 1,
			tag_memberships: 2,
			partners_returning_to_review: 1,
			freed_documents: 0
		},
		freed_document_ids: [],
		partners: [entry({ id: 8, version: 4 })],
		removed: [entry({ id: 5, version: 2 })],
		removed_entry_ids: [5],
		units: [],
		settle: null,
		...over
	};
}

/** A user-authored entry of the cash account, as the panel hands it over. */
export function authored(over: Partial<Entry> = {}): Entry {
	return entry({
		id: 5,
		version: 3,
		account_id: 1,
		source_transaction_id: 50,
		authored: true,
		booked_on: '2026-10-09',
		amount: { amount: -1250, currency: 'EUR' },
		display_text: 'groceries',
		source: {
			amount: { amount: -1250, currency: 'EUR' },
			booking_text: null,
			counterparty_bic: null,
			counterparty_name: null,
			counterparty_ref: null,
			end_to_end_id: null,
			instructed_amount: null,
			mandate_ref: null,
			purpose: 'groceries',
			source_format: null
		},
		...over
	});
}
