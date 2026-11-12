// Test fixtures for the reporting answers: whole API objects with sensible defaults. `line(-12000)`
// is a Line of one entry in EUR; `line(null)` has entries and none could be valued.
import { account } from '#lib/ledger/fixtures.js';
import type { ByCategory, Line, MonthSpend, Overview, SavingsSpan } from './types.js';

export function line(total: number | null = 0, over: Partial<Line> = {}): Line {
	return {
		total: total === null ? null : { amount: total, currency: 'EUR' },
		count: total === 0 ? 0 : 1,
		unvalued: [],
		...over
	};
}

export function span(over: Partial<SavingsSpan> = {}): SavingsSpan {
	return {
		from: '2026-10-01',
		to: '2026-10-20',
		income: line(300000),
		expense: line(-120000),
		unclassified: line(0),
		reconciliations: line(0),
		savings: line(180000),
		rate_bp: 6000,
		incomplete: false,
		...over
	};
}

function month(from: string, to: string, spend: Line): MonthSpend {
	return { from, to, spend };
}

export function overview(over: Partial<Overview> = {}): Overview {
	return {
		as_of: '2026-10-20',
		base_currency: 'EUR',
		net_worth: {
			total: { amount: 12845000, currency: 'EUR' },
			unvalued: [],
			unpaired_transfers: line(0),
			since: { on: '2026-09-30', change: { amount: 120000, currency: 'EUR' } },
			owed_to_you: null,
			you_owe: null
		},
		savings: {
			last_12: span({ from: '2025-10-01', to: '2026-09-30', rate_bp: 4200 }),
			last_month: span({ from: '2026-09-01', to: '2026-09-30', rate_bp: 3500 }),
			this_month: span({ rate_bp: 6000 })
		},
		spend: {
			this_month: {
				from: '2026-10-01',
				to: '2026-10-20',
				spend: line(-124000),
				unclassified_out: line(0),
				reconciliations: line(0)
			},
			last_month: month('2026-09-01', '2026-09-30', line(-261500)),
			last_month_to_date: month('2026-09-01', '2026-09-20', line(-180000))
		},
		data_age: {
			synced: [{ ...account({ id: 1, name: 'Giro' }), data_age_days: 1 }],
			by_hand: []
		},
		...over
	};
}

export function byCategory(over: Partial<ByCategory> = {}): ByCategory {
	return {
		base_currency: 'EUR',
		from: '2026-10-01',
		to: '2026-10-20',
		kind: 'expense',
		total: line(-124000),
		categories: [],
		slices: [],
		other: null,
		unclassified_out: line(0),
		unclassified_in: line(0),
		reconciliations: line(0),
		unconfirmed_count: 0,
		...over
	};
}
