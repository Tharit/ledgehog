// What the panel shows of a transaction's document under a draft (spec §5.8, §6; documents view,
// panel section): the document it would carry, how that came about, the suggestions as offers
// with hints, the wait, and the split along the lines. Pure: it reads the preview row's
// `document` and the draft's decision, and decides nothing.
import { formatDate, formatMoney } from '#lib/format/index.js';
import type { Draft, DocumentEdit } from './draft.js';
import { asKey, describeDocumentKey, type Evidence } from './evidence.js';
import type { DocumentSummary, DocumentWaiting, PreviewRow, RowDocument } from './types.js';

/** What the document row is in, in words the panel and its tests name. */
export type DocumentState =
	/** a document is carried (as stored, or as the draft would leave it) */
	| 'linked'
	/** the user picked one in this draft */
	| 'picked'
	/** the user decided there is none */
	| 'none'
	/** the user asked for matching to decide afresh */
	| 'resolve_again'
	/** nothing is carried: documents are suggested, or one is awaited, or neither */
	| 'open';

export type DocumentFieldView = {
	/** the original entry the decision is on */
	entryId: number;
	state: DocumentState;
	/** the document carried, or picked */
	document: DocumentSummary | null;
	evidence: Evidence | null;
	suggestions: readonly DocumentSummary[];
	waiting: DocumentWaiting | null;
	/** a commit is refused until the user picks a document or decides on none */
	decisionRequired: boolean;
	/** the split along the lines of the document the transaction carries */
	split: {
		available: boolean;
		proposed: boolean;
		replacesStoredSplit: boolean;
		document: { id: number; version: number } | null;
	} | null;
	edit: DocumentEdit | undefined;
	/** the user keeps one entry where a split along the lines is proposed */
	declined: boolean;
	/** the provider the payee's documents come from, for finding one by hand */
	provider: string | null;
	/** "Reset to proposal" applies: the draft decides something about the document */
	canReset: boolean;
	/** the split rows were edited, or taken over from the proposal and then changed */
	splitEdited: boolean;
};

/** The words of the wait: "Waiting for a document from amazon, covered through 12 Oct 2026". */
export function waitingText(waiting: DocumentWaiting, locale = 'en'): string {
	return waiting.covered_through === null
		? `Waiting for a document from ${waiting.provider}, not synced yet`
		: `Waiting for a document from ${waiting.provider}, covered through ${formatDate(waiting.covered_through, locale)}`;
}

function days(from: string, to: string): number {
	return Math.round((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / 86_400_000);
}

/**
 * What a suggested document says about itself against the entry: whether it has the exact amount,
 * and how far its date is from the booking. The list is the server's order (nearest first).
 */
export function documentHints(
	document: DocumentSummary,
	entry: { amount: number; currency: string; bookedOn: string | null },
	locale = 'en'
): string[] {
	const hints: string[] = [];
	if (document.total.currency === entry.currency) {
		const off = Math.abs(document.total.amount) - Math.abs(entry.amount);
		hints.push(
			off === 0
				? 'exact amount'
				: `${formatMoney(Math.abs(off), entry.currency, { locale, showPlus: false })} ${off > 0 ? 'more' : 'less'}`
		);
	}
	if (entry.bookedOn !== null) {
		const apart = days(entry.bookedOn, document.occurred_on);
		hints.push(
			apart === 0
				? 'same day'
				: `${Math.abs(apart)} ${Math.abs(apart) === 1 ? 'day' : 'days'} ${apart < 0 ? 'before' : 'after'}`
		);
	}
	return hints;
}

/**
 * The document field of an original entry, or null where there is nothing to show: the preview
 * says nothing (no link, no key, no suggestion, no wait) and the draft decides nothing.
 * `payeeProvider` is the provider of the entry's payee, the last resort for finding one by hand.
 */
export function documentField(
	row: PreviewRow | null,
	draft: Draft,
	id: number,
	payeeProvider: string | null = null
): DocumentFieldView | null {
	const info: RowDocument | null = row?.document ?? null;
	const edit = draft.documentEdit(id);
	const declined = draft.declinesSplit(id);
	if (!info && !edit && !declined) return null;
	const split = info?.split ?? null;
	const key = asKey(info?.key);
	const linked = info?.document ?? null;
	let state: DocumentState;
	let evidence: Evidence | null;
	switch (edit?.mode) {
		case 'none':
			state = 'none';
			evidence = { text: 'no document', proposal: false };
			break;
		case 'reresolve':
			state = 'resolve_again';
			evidence = null;
			break;
		case 'pick':
		case 'split_along_lines':
			state = 'picked';
			evidence = { text: 'picked by you', proposal: false };
			break;
		default:
			state = linked ? 'linked' : key?.pass === 'user' ? 'none' : 'open';
			evidence = describeDocumentKey(key, linked !== null);
	}
	const held = edit && 'documentId' in edit ? edit : null;
	// the document the split would be made along: the one picked, else the one carried
	const along = split
		? held && held.documentId === split.document_id
			? { id: held.documentId, version: held.version }
			: linked && linked.id === split.document_id
				? { id: linked.id, version: linked.version }
				: null
		: null;
	const suggestions = info?.suggestions ?? [];
	const waiting = info?.waiting ?? null;
	return {
		entryId: id,
		state,
		document: state === 'picked' || state === 'linked' ? linked : null,
		evidence,
		suggestions,
		waiting,
		decisionRequired: (info?.decision_required ?? false) && edit?.mode !== 'none' && held === null,
		split: split
			? {
					available: split.available,
					proposed: split.proposed,
					replacesStoredSplit: split.replaces_stored_split,
					document: along
				}
			: null,
		edit,
		declined,
		provider:
			waiting?.provider ?? linked?.provider ?? suggestions[0]?.provider ?? payeeProvider ?? null,
		canReset: edit !== undefined || declined || draft.lineRowsEdited,
		splitEdited: draft.lineRowsEdited
	};
}
