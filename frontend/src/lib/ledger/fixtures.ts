// Test fixtures for the ledger: whole API objects with sensible defaults.
import type { Account, Category, Entry, Payee, Tag, TagApplyOut } from '#lib/types/domain.js';

export function entry(over: Partial<Entry> = {}): Entry {
	return {
		id: 1,
		version: 1,
		account_id: 1,
		booked_on: '2026-10-09',
		value_on: null,
		amount: { amount: -4731, currency: 'EUR' },
		type: 'flow',
		description: null,
		note: null,
		display_text: 'REWE Markt',
		payee_id: null,
		category_id: null,
		counter_account_id: null,
		counterpart_entry_id: null,
		source_transaction_id: null,
		source: null,
		authored: false,
		derivation: {},
		unit_key: null,
		partner: null,
		origin: null,
		review_flags: [],
		model_pending: false,
		source_text: null,
		tag_ids: [],
		...over
	};
}

export function account(over: Partial<Account> = {}): Account {
	return {
		id: 1,
		name: 'Giro',
		kind: 'checking',
		currency: 'EUR',
		external_ref: null,
		providers: [],
		closed_on: null,
		sort_order: 0,
		note: null,
		icon: null,
		color: 'forest',
		synced: true,
		synced_through: null,
		last_data_on: null,
		unexplained_difference: null,
		anchored: true,
		balance: { amount: 0, currency: 'EUR' },
		balance_as_of: null,
		records_since_zero: null,
		net_deposits: null,
		gain: null,
		return_rate: null,
		return_as_of: null,
		...over
	};
}

export function category(over: Partial<Category> = {}): Category {
	return {
		id: 10,
		parent_id: null,
		name: 'Groceries',
		kind: 'expense',
		sort_order: 0,
		icon: 'shopping-cart',
		color: 'sage',
		...over
	};
}

export function payee(over: Partial<Payee> = {}): Payee {
	return { id: 20, name: 'REWE', icon: null, color: null, note: null, ...over };
}

export function tag(over: Partial<Tag> = {}): Tag {
	return {
		id: 30,
		name: 'Lisbon trip',
		color: 'lavender',
		starts_on: null,
		ends_on: null,
		entry_count: 0,
		...over
	};
}

/** A tag preview (dry run) by default: 3 newly tagged, 2 already carry it. */
export function applyOut(over: Partial<TagApplyOut> = {}): TagApplyOut {
	return {
		dry_run: true,
		selected: 5,
		newly_tagged: 3,
		already_tagged: 2,
		skipped_derived: 0,
		per_account: [{ account_id: 1, newly_tagged: 3 }],
		span_before: { starts_on: null, ends_on: null, entry_count: 0 },
		span_after: { starts_on: '2026-10-01', ends_on: '2026-10-09', entry_count: 3 },
		entries: [],
		settle: null,
		...over
	};
}
