// Test fixtures for the rule screens: whole API objects with sensible defaults.
import type { Rule, RulePreview, RulePreviewList, RulePreviewRow } from '#lib/api/rules.js';

export function rule(over: Partial<Rule> = {}): Rule {
	return {
		id: 1,
		name: 'Landlord',
		sets: 'category',
		counter_account_id: null,
		payee_id: null,
		category_id: 10,
		condition_payee_id: null,
		counterparty_ref: null,
		mandate_ref: null,
		name_exact: null,
		name_prefix: 'Landlord',
		purpose_regex: null,
		booking_text: null,
		priority: 100,
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
		counterparty_name: 'Landlord GmbH',
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
