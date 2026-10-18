// The unit shapes (spec §6), from the generated API types.
import type { Entry } from '#lib/types/domain.js';

type Schemas = import('../types/api.js').components['schemas'];

export type Unit = Schemas['UnitOut'];
export type UnitState = Schemas['UnitStateOut'];
export type UnitReason = UnitState['reasons'][number];
export type QueueSection = Schemas['QueueSectionOut'];
export type QueueGroup = Schemas['CurrencyGroupOut'];
export type SectionKind = QueueSection['kind'];
export type ReviewQueue = Schemas['ReviewQueueOut'];
export type QueueCount = Schemas['QueueCountOut'];

// The draft, its preview and its commit (architecture §4.1, spec §6).
export type UnitDraftRequest = Schemas['UnitDraftIn'];
export type DraftEntryRequest = Schemas['UnitDraftEntryIn'];
export type PairingRequest = Schemas['UnitPairingIn'];
export type FieldDraftRequest = Schemas['UnitFieldDraftIn'];
export type UnitPreview = Schemas['UnitPreviewOut'];
export type UnitTransfer = Schemas['UnitTransferOut'];
export type PreviewRow = Schemas['UnitPreviewRowOut'];
export type UnitOffer = Schemas['UnitOfferOut'];
export type PreviewField = Schemas['UnitFieldOut'];
/** The split the server suggests for an unequal pair: the amount's magnitude in minor units. */
export type SuggestedSplit = { source_entry_id: number; amount: number };
export type UnitProblem = Schemas['UnitProblemOut'];
export type UnitConsequence = Schemas['UnitConsequenceOut'];
export type ConsequenceKind = UnitConsequence['kind'];
export type UnitSplit = Schemas['UnitSplitOut'];
// The document part of the draft and of a preview row (spec §5.8, §6).
export type DocumentDraftRequest = Schemas['UnitDocumentDraftIn'];
export type DocumentLineRequest = Schemas['UnitDocumentLineIn'];
export type RowDocument = Schemas['UnitRowDocumentOut'];
export type DocumentSummary = Schemas['UnitDocumentSummaryOut'];
export type RowDocumentLine = Schemas['UnitRowDocumentLineOut'];
export type DocumentSplit = Schemas['UnitDocumentSplitOut'];
export type DocumentWaiting = Schemas['UnitDocumentWaitingOut'];
export type UnitCommit = Schemas['UnitCommitOut'];

/** The sections in the order the queue shows them. */
export const SECTION_ORDER: readonly SectionKind[] = ['pending_review', 'needs_account', 'waiting'];

/**
 * What an action reports it touched (architecture §4.1, the write responses of a later wave):
 * full rows for the entries changed, which of them the action resolved, which came back as a
 * consequence, which returned to review and which were deleted. The contract is fixed here;
 * commit arrives next.
 */
export type Affected = {
	/** the rows as they are now */
	entries: readonly Entry[];
	/** entries of the units the user's action committed: muted until the list is loaded again */
	resolved?: readonly number[];
	/** those of them whose unit is now confirmed: they also get the check */
	confirmed?: readonly number[];
	/** entries that returned to review */
	returned_to_review?: readonly number[];
	/** entries that no longer exist */
	removed_entry_ids?: readonly number[];
	/** entries the action created (the rows of a split): inserted next to `anchor_entry_id` */
	created?: readonly number[];
	/** the entry the unit was opened on: where `created` rows go */
	anchor_entry_id?: number;
};
