// The controls of the reports, in the URL (reports.md: shared controls). The period, the account
// and tag filters use the ledger's own parameter names; `kind`, `step` and `mode` are the
// reports'. Whatever arrives from a URL is validated and never thrown on: what cannot be understood
// is the default. Serialising is canonical (fixed order, sorted ids, defaults of the report left
// out), so the same controls are always the same URL.
import { fromSearchParams } from '#lib/ledger/filter.js';
import { datePresets } from '#lib/ledger/presets.js';
import type { Kind, Step } from './shapes.js';

export type ReportId = 'by-category' | 'over-time' | 'balances';
export type TimeMode = 'income-expense' | 'category';

export type ReportParams = {
	from: string;
	to: string;
	kind: Kind;
	step: Step;
	mode: TimeMode;
	accountIds: number[];
	tagIds: number[];
};

export const STEPS: readonly { step: Step; label: string }[] = [
	{ step: 'month', label: 'Month' },
	{ step: 'quarter', label: 'Quarter' },
	{ step: 'year', label: 'Year' }
];

export const REPORT_TABS: readonly { href: string; label: string; id: ReportId }[] = [
	{ href: '/reports/by-category', label: 'By category', id: 'by-category' },
	{ href: '/reports/over-time', label: 'Over time', id: 'over-time' },
	{ href: '/reports/balances', label: 'Balances', id: 'balances' }
];

/** The range a report opens on: the month so far for the split, the last 12 months for the trends. */
export function defaultRange(report: ReportId, today: string): { from: string; to: string } {
	const id = report === 'by-category' ? 'this-month' : 'last-12-months';
	const preset = datePresets(today).find((p) => p.id === id)!;
	return { from: preset.from, to: preset.to };
}

export function parseParams(
	search: URLSearchParams | string,
	report: ReportId,
	today: string
): ReportParams {
	const params = typeof search === 'string' ? new URLSearchParams(search) : search;
	const filter = fromSearchParams(params);
	const fallback = defaultRange(report, today);
	// one end given is a range open on the other: the default's other end
	let from = filter.from ?? fallback.from;
	let to = filter.to ?? fallback.to;
	if (from > to) [from, to] = [to, from];
	const step = params.get('step');
	return {
		from,
		to,
		kind: params.get('kind') === 'income' ? 'income' : 'expense',
		step: step === 'quarter' || step === 'year' ? step : 'month',
		mode: params.get('mode') === 'category' ? 'category' : 'income-expense',
		accountIds: filter.account_id,
		tagIds: filter.tag_id
	};
}

/** The controls as a query: only what differs from the report's defaults, plus the period when it does. */
export function toQuery(params: ReportParams, report: ReportId, today: string): URLSearchParams {
	const query = new URLSearchParams();
	const fallback = defaultRange(report, today);
	if (params.from !== fallback.from || params.to !== fallback.to) {
		query.set('from', params.from);
		query.set('to', params.to);
	}
	if (report !== 'balances') {
		for (const id of [...params.accountIds].sort((a, b) => a - b))
			query.append('account_id', String(id));
		for (const id of [...params.tagIds].sort((a, b) => a - b)) query.append('tag_id', String(id));
	}
	const byCategory =
		report === 'by-category' || (report === 'over-time' && params.mode === 'category');
	if (byCategory && params.kind === 'income') query.set('kind', 'income');
	if (report === 'over-time') {
		if (params.step !== 'month') query.set('step', params.step);
		if (params.mode === 'category') query.set('mode', 'category');
	}
	return query;
}

/**
 * What the tabs carry from one report to the next: the period when the address names one, and
 * the account and tag filters. The kind, the step and the mode belong to one report.
 */
export function sharedQuery(search: URLSearchParams | string): string {
	const params = typeof search === 'string' ? new URLSearchParams(search) : search;
	const shared = new URLSearchParams();
	for (const name of ['from', 'to', 'account_id', 'tag_id']) {
		for (const value of params.getAll(name)) shared.append(name, value);
	}
	return shared.toString();
}
