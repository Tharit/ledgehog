// Test fixtures for the ledger: whole API objects with sensible defaults.
import type { Account, Category, Entry, Payee, Tag } from '#lib/types/domain.js';

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
		counterparty_name: null,
		purpose: null,
		display_text: 'REWE Markt',
		payee_id: null,
		category_id: null,
		counter_account_id: null,
		counterpart_entry_id: null,
		source_transaction_id: null,
		document_id: null,
		review_flags: [],
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
		records_since_zero: null,
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
