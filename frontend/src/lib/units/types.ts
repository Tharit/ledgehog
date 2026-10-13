// The unit shapes (spec §6), from the generated API types.
import type { Entry } from '#lib/types/domain.js';

type Schemas = import('../types/api.js').components['schemas'];

export type Unit = Schemas['UnitOut'];
export type UnitState = Schemas['UnitStateOut'];
export type UnitReason = UnitState['reasons'][number];
export type QueueSection = Schemas['QueueSectionOut'];
export type SectionKind = QueueSection['kind'];
export type ReviewQueue = Schemas['ReviewQueueOut'];
export type NewUnitCount = Schemas['NewCountOut'];

// The draft, its preview and its commit (architecture §4.1, spec §6).
export type UnitDraftRequest = Schemas['UnitDraftIn'];
export type DraftEntryRequest = Schemas['UnitDraftEntryIn'];
export type FieldDraftRequest = Schemas['UnitFieldDraftIn'];
export type UnitPreview = Schemas['UnitPreviewOut'];
export type PreviewRow = Schemas['UnitPreviewRowOut'];
export type PreviewField = Schemas['UnitFieldOut'];
export type UnitProblem = Schemas['UnitProblemOut'];
export type UnitConsequence = Schemas['UnitConsequenceOut'];
export type ConsequenceKind = UnitConsequence['kind'];
export type UnitSplit = Schemas['UnitSplitOut'];
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
	/** entries the user's action resolved */
	resolved?: readonly number[];
	/** entries that returned to review */
	returned_to_review?: readonly number[];
	/** entries that no longer exist */
	removed_entry_ids?: readonly number[];
	/** entries the action created (the rows of a split): inserted next to `anchor_entry_id` */
	created?: readonly number[];
	/** the entry the unit was opened on: where `created` rows go */
	anchor_entry_id?: number;
};
