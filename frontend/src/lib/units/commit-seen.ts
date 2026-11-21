// One unit committed as its row showed it (views/review-queue.md): read the unit anew, preview it
// with an empty draft exactly as opening the panel does, commit only if the values are those the
// row showed, and then as the panel's commit would. Never throws: a refusal is a reason.
import { ApiError, commitUnit, getUnit, previewUnit } from '#lib/api/index.js';
import { Draft, type FieldValue } from './draft.js';
import { commitRequest, previewRequest } from './commit-request.js';
import { describeProblem, draftErrorText, problemSentence } from './problems.js';
import { changedSince, changedText, type Changed } from './selection.js';
import { problemsOf } from './unit-draft-flow.svelte.js';
import type { Unit, UnitCommit, UnitProblem } from './types.js';

export type SeenResult = { ok: true; out: UnitCommit } | { ok: false; reason: string };

export type SeenOptions = {
	locale: string;
	/** words a changed value (a category's name rather than its id) */
	name: (field: Changed['field'], value: FieldValue) => string;
};

/** What a refusal of the server says, in a few words (the panel's wording, shortened). */
export function refusalText(error: unknown, problemText: (problem: UnitProblem) => string): string {
	if (!(error instanceof ApiError)) return 'The server could not be reached.';
	switch (error.code) {
		case 'conflict':
		case 'unit_moved':
			return 'The unit changed meanwhile.';
		case 'stale_reference':
			return 'Something it uses no longer exists.';
		case 'not_found':
			return 'The unit no longer exists.';
		case 'try_again':
			return 'The commit was interrupted before it wrote anything.';
		case 'invalid_draft':
			return (
				draftErrorText((error.details as { code?: string } | null)?.code) ??
				'This cannot be committed as it stands.'
			);
		case 'network_error':
			return 'The server could not be reached.';
	}
	const problems = problemsOf(error);
	if (error.status === 422 && problems.length > 0) return problemsText(problems, problemText);
	return 'The commit did not go through.';
}

function problemsText(
	problems: readonly UnitProblem[],
	problemText: (problem: UnitProblem) => string
): string {
	return problems.length === 1
		? problemText(problems[0])
		: `${problems.length} problems to resolve.`;
}

export async function commitAsSeen(seen: Unit, options: SeenOptions): Promise<SeenResult> {
	const currency = (entryId: number | null) =>
		(seen.entries.find((e) => e.id === entryId) ?? seen.entries[0]).amount.currency;
	const problemText = (problem: UnitProblem) =>
		problemSentence(describeProblem(problem, { locale: options.locale, currency }));
	try {
		const unit = await getUnit(seen.anchor_entry_id);
		const draft = Draft.of(unit);
		const preview = await previewUnit(previewRequest(draft));
		const changed = changedSince(seen.entries, preview);
		if (changed) return { ok: false, reason: changedText(changed, options.name) };
		if (preview.problems.length > 0)
			return { ok: false, reason: problemsText(preview.problems, problemText) };
		return { ok: true, out: await commitUnit(commitRequest(draft, preview)) };
	} catch (error) {
		return { ok: false, reason: refusalText(error, problemText) };
	}
}
