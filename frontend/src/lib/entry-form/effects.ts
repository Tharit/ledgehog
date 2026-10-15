// What an edit or a delete does, in words: the static §5.6 warning, and the dry runs' answers as
// a short list (edit) or one sentence (delete).
import type { SourceDeleteCounts, SourceEditEffects } from '#lib/api/types.js';
import { formatMoney } from '#lib/format/index.js';

/** Spec §5.6: always shown above Save; it is the confirmation (decision D214). */
export const EDIT_WARNING =
	"Entries that cannot absorb the change are collapsed into one, a pair whose amounts no longer match is broken, and the entries' values are derived again.";

function plural(n: number, one: string, many: string): string {
	return `${n} ${n === 1 ? one : many}`;
}

/** The consequences a dry run reports, one line each; empty when it reports none. */
export function summarizeEdit(effects: SourceEditEffects): string[] {
	const lines: string[] = [];
	const collapsed = effects.collapsed_entry_ids.length;
	if (collapsed > 0) {
		lines.push(
			`${plural(collapsed, 'split entry is', 'split entries are')} collapsed into the original.`
		);
	}
	const unpaired = effects.unpaired_entry_ids.length;
	if (unpaired > 0) {
		lines.push(
			`${plural(unpaired, 'entry loses its counterpart', 'entries lose their counterpart')}; the transfer pair is broken.`
		);
	}
	const rederived = effects.rederived_entry_ids.length;
	if (rederived > 0) {
		lines.push(`Values are derived again for ${plural(rederived, 'entry', 'entries')}.`);
	}
	const followed = effects.followed_entry_ids.length;
	if (followed > 0) {
		lines.push(
			followed === 1
				? '1 linked counter-leg follows the new amount'
				: `${followed} linked counter-legs follow the new amount`
		);
	}
	const returned = effects.returned_to_review_ids.length;
	if (returned > 0) {
		lines.push(`${plural(returned, 'entry returns', 'entries return')} to review.`);
	}
	return lines;
}

/** "Removes 1 entry (confirmed), 2 tags, and sends 1 partner back to review." */
export function summarizeDelete(counts: SourceDeleteCounts): string {
	const entries = plural(counts.entries, 'entry', 'entries');
	const confirmed =
		counts.confirmed_entries === 0
			? ''
			: counts.confirmed_entries === counts.entries
				? ' (confirmed)'
				: ` (${counts.confirmed_entries} confirmed)`;
	const items = [`removes ${entries}${confirmed}`];
	if (counts.tag_memberships > 0) items.push(plural(counts.tag_memberships, 'tag', 'tags'));
	if (counts.freed_documents > 0) {
		items.push(`frees ${plural(counts.freed_documents, 'document', 'documents')}`);
	}
	if (counts.partners_returning_to_review > 0) {
		items.push(
			`sends ${plural(counts.partners_returning_to_review, 'partner', 'partners')} back to review`
		);
	}
	const text =
		items.length === 1
			? items[0]
			: items.length === 2
				? `${items[0]} and ${items[1]}`
				: `${items.slice(0, -1).join(', ')}, and ${items[items.length - 1]}`;
	return text.charAt(0).toUpperCase() + text.slice(1) + '.';
}

/** An entry in a notice: "−12.50 EUR · groceries". */
export function describeEntry(
	entry: { amount: { amount: number; currency: string }; display_text: string | null },
	locale = 'en'
): string {
	const money = formatMoney(entry.amount.amount, entry.amount.currency, {
		locale,
		showCurrency: true,
		showPlus: false
	});
	const text = entry.display_text?.trim();
	return text ? `${money} · ${text}` : money;
}
