// What the account's statement shows about its items, as words and keys: the marker line of a
// balance record, the "duplicate of" label, the cursor's identity. The server computed every number
// (architecture §4.1, "The account statement"); this only formats them.
import { formatDate, formatMoney } from '#lib/format/index.js';
import type { DuplicateOf, StatementItem, StatementRecord } from '#lib/types/domain.js';

/** Depots and other assets are investment accounts: their difference is a valuation (spec §3.3). */
export function isInvestment(kind: string): boolean {
	return kind === 'depot' || kind === 'asset';
}

/** One item's identity across refetches: ids of sources and records are separate sequences. */
export function itemKey(item: Pick<StatementItem, 'kind' | 'id'>): string {
	return `${item.kind}:${item.id}`;
}

export const sourceKey = (id: number): string => `source:${id}`;

/** "duplicate of 12 Oct 2026 · −40.00" */
export function duplicateLabel(of: DuplicateOf, locale: string): string {
	return `duplicate of ${formatDate(of.booked_on, locale)} · ${formatMoney(of.amount.amount, of.amount.currency, { locale })}`;
}

/** The marker's kind word: "Reported balance" or "Manual balance". */
export function recordKindLabel(record: Pick<StatementRecord, 'record_kind'>): string {
	return record.record_kind === 'reported' ? 'Reported balance' : 'Manual balance';
}

/**
 * What the ledger does not explain about a record (spec §3.10): "expected 1,000.00 · difference −3.50",
 * on an investment account "· valuation 20.00"; expected is the balance less the difference. Nothing
 * where there is no difference. The anchor always says the opening it sets: "opening 1,000.00".
 */
export function recordGap(
	record: Pick<StatementRecord, 'anchor' | 'balance' | 'difference'>,
	{ investment, locale }: { investment: boolean; locale: string }
): string | null {
	const { balance, difference } = record;
	const money = (minor: number, showPlus: boolean) =>
		formatMoney(minor, balance.currency, { locale, showPlus });
	if (record.anchor) return `opening ${money(difference.amount, false)}`;
	if (difference.amount === 0) return null;
	return `expected ${money(balance.amount - difference.amount, false)} · ${investment ? 'valuation' : 'difference'} ${money(difference.amount, true)}`;
}

/** "3 bookings dated before it arrived later": the movements a reported record does not count. */
export function lateArrivalsLabel(record: Pick<StatementRecord, 'late_arrivals'>): string | null {
	const n = record.late_arrivals;
	if (n <= 0) return null;
	return `${n} ${n === 1 ? 'booking' : 'bookings'} dated before it arrived later`;
}

/** The record that was asked to be shown the cursor again after a refetch: its key, else a neighbour's. */
export function cursorAfterRefetch(
	items: readonly StatementItem[],
	key: string | null,
	previousIndex: number
): string | null {
	if (items.length === 0) return null;
	if (key !== null && items.some((item) => itemKey(item) === key)) return key;
	return itemKey(items[Math.min(Math.max(previousIndex, 0), items.length - 1)]);
}
