// Test fixtures for the rule screens: whole API objects with sensible defaults.
import type { Rule, RulePreview, RulePreviewList, RulePreviewRow } from '#lib/api/rules.js';
import type { SourceTransaction } from '#lib/api/types.js';

export function rule(over: Partial<Rule> = {}): Rule {
	return {
		id: 1,
		name: 'Landlord',
		sets: 'category',
		counter_account_id: null,
		payee_id: null,
		category_id: 10,
		condition_payee_id: null,
		conditions: [{ field: 'counterparty_name', op: 'starts_with', value: 'Landlord' }],
		priority: 100,
		...over
	};
}

/** A source transaction with nothing but a counterparty name unless told otherwise. */
export function source(over: Partial<SourceTransaction> = {}): SourceTransaction {
	return {
		counterparty_name: 'Landlord GmbH',
		counterparty_ref: null,
		counterparty_bic: null,
		purpose: null,
		booking_text: null,
		end_to_end_id: null,
		mandate_ref: null,
		instructed_amount: null,
		source_format: null,
		...over
	};
}

export function previewRow(over: Partial<RulePreviewRow> = {}): RulePreviewRow {
	return {
		entry_id: 1,
		account_id: 1,
		booked_on: '2026-10-01',
		amount: { amount: -95000, currency: 'EUR' },
		description: 'Rent October',
		source: source(),
		confirmed: false,
		current_value: null,
		current_key: null,
		shadowed_by_rule_id: null,
		keyed_fields: [],
		...over
	};
}

export function previewList(rows: RulePreviewRow[] = [], total = rows.length): RulePreviewList {
	return { total, rows };
}

export function preview(over: Partial<RulePreview> = {}): RulePreview {
	return {
		matches: previewList(),
		would_confirm: 0,
		stay_in_review: 0,
		different_value: previewList(),
		lost_key: previewList(),
		...over
	};
}
