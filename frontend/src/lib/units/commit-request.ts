// The two requests a unit's draft makes, defined once: the panel's flow and the review queue's
// "commit as seen" both build them here, so a commit from the rows is the panel's own commit.
import type { Draft } from './draft.js';
import type { UnitDraftRequest, UnitPreview } from './types.js';

/** What committing the draft would do: the draft as it stands, with the versions it was loaded at. */
export function previewRequest(draft: Draft): UnitDraftRequest {
	return draft.toRequest();
}

/** The commit of a draft on the preview that was shown: the versions the preview named. */
export function commitRequest(
	draft: Draft,
	preview: Pick<UnitPreview, 'versions'>
): UnitDraftRequest {
	return draft.toRequest(preview.versions);
}
