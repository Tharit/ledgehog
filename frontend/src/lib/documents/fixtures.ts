// Test fixtures for documents: whole API objects with sensible defaults.
import type { DocumentDetail, DocumentRow } from '#lib/types/domain.js';

export function documentRow(over: Partial<DocumentRow> = {}): DocumentRow {
	return {
		id: 1,
		version: 1,
		provider: 'amazon',
		external_id: 'A-1',
		importer_instance_id: null,
		occurred_on: '2026-10-08',
		total: { amount: -4731, currency: 'EUR' },
		merchant_name: 'Amazon',
		title: 'Order 304-1',
		line_count: 2,
		booking: null,
		not_booked: { reason: 'no_account', currency: 'EUR', account_id: null, start: null },
		...over
	};
}

export function documentDetail(over: Partial<DocumentDetail> = {}): DocumentDetail {
	return {
		...documentRow(),
		booking: null,
		lines: [
			{
				line_no: 1,
				description: 'USB cable',
				amount: { amount: -1500, currency: 'EUR' },
				qty: 2
			},
			{
				line_no: 2,
				description: 'Book',
				amount: { amount: -3231, currency: 'EUR' },
				qty: null
			}
		],
		...over
	};
}
