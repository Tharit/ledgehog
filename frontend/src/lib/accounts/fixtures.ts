// Statement items and provenance for the account page's tests.
import type { Provenance, StatementRecord, StatementSource } from '#lib/types/domain.js';

const eur = (amount: number) => ({ amount, currency: 'EUR' });

export function sourceRow(over: Partial<StatementSource> = {}): StatementSource {
	return {
		kind: 'source',
		id: 1,
		booked_on: '2026-10-10',
		value_on: null,
		amount: eur(-4000),
		counterparty_name: 'REWE',
		purpose: 'Groceries',
		authored: false,
		duplicate_of: null,
		entry_id: 10,
		run_id: 5,
		late_for: null,
		booking: null,
		origin: 'import',
		...over
	};
}

export function recordRow(over: Partial<StatementRecord> = {}): StatementRecord {
	return {
		kind: 'record',
		id: 1,
		balance_on: '2026-10-09',
		record_kind: 'reported',
		balance: eur(100000),
		anchor: false,
		difference: eur(0),
		late_arrivals: 0,
		...over
	};
}

export function provenance(over: Partial<Provenance> = {}): Provenance {
	return {
		id: 1,
		account_id: 1,
		authored: false,
		source_format: 'csv:Giro',
		booked_on: '2026-10-10',
		value_on: null,
		amount: eur(-4000),
		instructed_amount: null,
		counterparty_name: 'REWE',
		counterparty_ref: null,
		counterparty_bic: null,
		purpose: 'Groceries',
		booking_text: null,
		end_to_end_id: null,
		mandate_ref: null,
		raw: { Buchungstext: 'Kartenzahlung' },
		run: {
			id: 5,
			importer: 'csv',
			instance_id: 2,
			instance_label: 'Giro file',
			started_at: '2026-10-11T08:00:00Z',
			finished_at: '2026-10-11T08:00:05Z'
		},
		duplicate_of: null,
		entry_id: 10,
		origin: 'import',
		booking: null,
		...over
	};
}
