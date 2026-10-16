import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, commitUnit, getUnit, previewUnit } from '#lib/api/index.js';
import { entry } from '#lib/ledger/fixtures.js';
import {
	committed,
	documentSummary,
	preview,
	previewRowOf,
	problem,
	rowDocument,
	unit
} from './fixtures.js';
import type { PreviewRow, UnitPreview } from './types.js';
import { UnitDraftFlow, type FlowHost } from './unit-draft-flow.svelte.js';

vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	previewUnit: vi.fn(),
	commitUnit: vi.fn(),
	getUnit: vi.fn()
}));

const e = entry({
	id: 1,
	version: 3,
	unit_key: 1,
	source_transaction_id: 5,
	amount: { amount: -4731, currency: 'EUR' }
});
const loaded = unit({ anchor_entry_id: 1, entries: [e] });
const doc = documentSummary();

function host(): FlowHost & { [K in keyof FlowHost]: ReturnType<typeof vi.fn> } {
	return {
		locale: vi.fn(() => 'en'),
		unitChanged: vi.fn(),
		patch: vi.fn(),
		reloadLookups: vi.fn().mockResolvedValue(undefined),
		addTag: vi.fn(),
		previewed: vi.fn(),
		committed: vi.fn()
	} as never;
}

const settle = async () => {
	for (let i = 0; i < 5; i++) await Promise.resolve();
};

function setup(document?: { entryId: number; id: number; version: number }) {
	const h = host();
	const flow = new UnitDraftFlow(h);
	flow.begin(loaded, document);
	return { flow, h };
}

function error(status: number, code: string, details: unknown = null) {
	return new ApiError(status, code, 'x', details);
}

/** The preview the server answers: the original row carries `document`, plus the extra rows and problems. */
function answer(
	document: ReturnType<typeof rowDocument> | null,
	extra: { rows?: PreviewRow[]; problems?: UnitPreview['problems'] } = {}
): UnitPreview {
	const base = preview(loaded);
	base.rows = [previewRowOf(e, { document }), ...(extra.rows ?? [])];
	base.problems = extra.problems ?? [];
	return base;
}

/** A row made from a line: a new row with a server id. */
function lineRow(id: number, lineNo: number, amount: number): PreviewRow {
	return previewRowOf(e, {
		id,
		original: false,
		version: null,
		amount: { amount, currency: 'EUR' },
		document_line: { document_id: 7, line_no: lineNo, description: `Line ${lineNo}` }
	});
}

const lastRequest = () => vi.mocked(previewUnit).mock.calls.at(-1)![0];
const original = (request: ReturnType<typeof lastRequest>) =>
	request.entries?.find((entry) => entry.id === 1);

const required = rowDocument({ suggestions: [doc], decision_required: true });
const decisionRequired = problem('document_decision_required', { entry_id: 1, field: 'document' });

beforeEach(() => {
	vi.useFakeTimers();
	vi.resetAllMocks();
	vi.mocked(previewUnit).mockResolvedValue(answer(null));
	vi.mocked(getUnit).mockResolvedValue(loaded);
});
afterEach(() => vi.useRealTimers());

describe('opening with a document picked', () => {
	it('previews the pick at once, as the first request', async () => {
		const { flow } = setup({ entryId: 1, id: 7, version: 2 });
		await settle();

		expect(original(lastRequest())!.document).toEqual({
			mode: 'pick',
			document_id: 7,
			document_version: 2,
			decline_split: false
		});
		expect(flow.draft?.documentEdit(1)).toEqual({ mode: 'pick', documentId: 7, version: 2 });
		expect(flow.isDirty).toBe(true);
	});

	it('picks on the original entry of the transaction, whichever entry was opened', async () => {
		const sibling = entry({ id: 2, version: 4, unit_key: 1, source_transaction_id: 5 });
		const two = unit({ anchor_entry_id: 2, entries: [e, sibling] });
		const flow = new UnitDraftFlow(host());
		flow.begin(two, { entryId: 2, id: 7, version: 2 });

		expect(flow.draft?.documentEdit(1)).toBeDefined();
		expect(flow.draft?.documentEdit(2)).toBeUndefined();
	});
});

describe('choosing the document', () => {
	it('previews a pick with the version the user saw', async () => {
		const { flow } = setup();
		await settle();

		flow.pickDocument(1, { id: 7, version: 2 });
		await settle();

		expect(original(lastRequest())!.document).toMatchObject({
			mode: 'pick',
			document_id: 7,
			document_version: 2
		});
	});

	it('previews none, re-resolve and the split along the lines', async () => {
		const { flow } = setup();
		await settle();

		flow.noDocument(1);
		expect(original(lastRequest())!.document).toMatchObject({ mode: 'none' });
		flow.reresolveDocument(1);
		expect(original(lastRequest())!.document).toMatchObject({ mode: 'reresolve' });
		flow.splitAlongLines(1, { id: 7, version: 2 });
		expect(original(lastRequest())!.document).toMatchObject({
			mode: 'split_along_lines',
			document_id: 7
		});
		flow.declineSplit(1);
		expect(original(lastRequest())!.document).toMatchObject({ mode: 'pick', decline_split: true });
		flow.resetDocument(1);
		expect(original(lastRequest())).toBeUndefined();
	});
});

describe('committing where a document is suggested or awaited', () => {
	it('is not possible without the decision, and sends nothing the server would refuse', async () => {
		vi.mocked(previewUnit).mockResolvedValue(answer(required, { problems: [decisionRequired] }));
		const { flow } = setup();
		await settle();

		expect(flow.commitReason).toBe(
			'A document is suggested or expected for this transaction. Pick one, or commit without a document.'
		);
		await flow.commit();

		expect(commitUnit).not.toHaveBeenCalled();
	});

	it('is possible once the user chose to commit without a document, and sends none', async () => {
		vi.mocked(previewUnit).mockImplementation(async (request) => {
			const decided = original(request)?.document?.mode === 'none';
			return decided
				? answer(rowDocument({ suggestions: [doc] }))
				: answer(required, { problems: [decisionRequired] });
		});
		vi.mocked(commitUnit).mockResolvedValue(committed(loaded));
		const { flow, h } = setup();
		await settle();
		expect(flow.commitReason).not.toBeNull();

		flow.noDocument(1);
		await settle();
		expect(flow.commitReason).toBeNull();
		await flow.commit();

		expect(vi.mocked(commitUnit).mock.calls[0][0].entries).toEqual([
			{ id: 1, document: { mode: 'none', decline_split: false } }
		]);
		expect(h.committed).toHaveBeenCalled();
	});

	it('is possible with a pick, which sends its id and version', async () => {
		vi.mocked(previewUnit).mockImplementation(async (request) =>
			original(request)?.document?.mode === 'pick'
				? answer(rowDocument({ document: doc }))
				: answer(required, { problems: [decisionRequired] })
		);
		vi.mocked(commitUnit).mockResolvedValue(committed(loaded));
		const { flow } = setup();
		await settle();

		flow.pickDocument(1, { id: 7, version: 2 });
		await settle();
		await flow.commit();

		expect(vi.mocked(commitUnit).mock.calls[0][0].entries![0]!.document).toMatchObject({
			mode: 'pick',
			document_id: 7,
			document_version: 2
		});
	});

	it('shows a commit refused for the decision as a problem, and keeps the draft', async () => {
		// the preview that follows the refusal says what the server judged
		vi.mocked(previewUnit)
			.mockResolvedValueOnce(answer(null))
			.mockResolvedValue(answer(required, { problems: [decisionRequired] }));
		vi.mocked(commitUnit).mockRejectedValueOnce(
			error(422, 'document_decision_required', { problems: [decisionRequired] })
		);
		const { flow } = setup();
		await settle();

		await flow.commit();
		await settle();

		expect(flow.notice).toBeNull();
		expect(flow.problemTexts[0]!.text.text).toMatch(/suggested or expected/);
	});
});

describe('the split along the lines', () => {
	const proposed = () =>
		answer(
			rowDocument({
				document: doc,
				split: { document_id: 7, available: true, proposed: true, replaces_stored_split: false }
			}),
			{ rows: [lineRow(-900, 2, -3231)] }
		);

	it('takes the proposed rows over without another preview, and is no change', async () => {
		vi.mocked(previewUnit).mockResolvedValue(proposed());
		const { flow } = setup();
		await settle();
		const calls = vi.mocked(previewUnit).mock.calls.length;

		expect(flow.draft?.lineRows).toMatchObject([
			{ id: -900, sourceEntryId: 1, documentLine: { documentId: 7, lineNo: 2 } }
		]);
		expect(vi.mocked(previewUnit).mock.calls.length).toBe(calls);
		expect(flow.isDirty).toBe(false);
		expect(flow.stale).toBe(false);
	});

	it('echoes every row of it in the next request, and in the commit', async () => {
		vi.mocked(previewUnit).mockResolvedValue(proposed());
		vi.mocked(commitUnit).mockResolvedValue(committed(loaded));
		const { flow } = setup();
		await settle();

		flow.setText(1, 'note', 'checked');
		await vi.advanceTimersByTimeAsync(300);
		expect(lastRequest().entries).toEqual([
			{ id: 1, note: 'checked' },
			{
				id: -900,
				source_entry_id: 1,
				amount: -3231,
				document_line: { document_id: 7, line_no: 2 }
			}
		]);

		await flow.commit();
		expect(vi.mocked(commitUnit).mock.calls[0][0].entries!.map((x) => x.id)).toEqual([1, -900]);
	});

	it('is refused with "keep one entry": the row goes and decline_split is sent', async () => {
		vi.mocked(previewUnit).mockResolvedValue(proposed());
		const { flow } = setup();
		await settle();

		flow.declineSplit(1);

		expect(flow.draft?.lineRows).toEqual([]);
		expect(original(lastRequest())!.document).toEqual({ mode: 'keep', decline_split: true });
	});

	it('forgets the rows the server drops, such as those of a document that is no longer the transaction’s', async () => {
		vi.mocked(previewUnit).mockResolvedValueOnce(proposed());
		const { flow } = setup();
		await settle();
		expect(flow.draft?.lineRows).toHaveLength(1);

		vi.mocked(previewUnit).mockResolvedValue(answer(rowDocument({ document: doc })));
		flow.pickDocument(1, { id: 8, version: 1 });
		await settle();

		expect(flow.draft?.lineRows).toEqual([]);
	});
});

describe('a document that is not what the user saw', () => {
	it('drops a pick the preview says changed, tells the user and previews again', async () => {
		vi.mocked(previewUnit).mockResolvedValue(answer(null));
		const { flow } = setup();
		await settle();
		vi.mocked(previewUnit).mockResolvedValueOnce(
			answer(null, {
				problems: [
					problem('document_changed', {
						entry_id: 1,
						field: 'document',
						detail: { document_id: 7 }
					})
				]
			})
		);
		flow.pickDocument(1, { id: 7, version: 2 });
		await settle();

		expect(flow.draft?.documentEdit(1)).toBeUndefined();
		expect(flow.notice).toMatchObject({ kind: 'conflict' });
		expect(flow.notice?.text).toMatch(/changed after you saw it/);
		expect(original(lastRequest())).toBeUndefined();
	});

	it('drops a pick another transaction carries', async () => {
		const { flow } = setup();
		await settle();
		vi.mocked(previewUnit).mockResolvedValueOnce(
			answer(null, {
				problems: [
					problem('document_taken', { entry_id: 1, field: 'document', detail: { document_id: 7 } })
				]
			})
		);
		flow.pickDocument(1, { id: 7, version: 2 });
		await settle();

		expect(flow.draft?.documentEdit(1)).toBeUndefined();
		expect(flow.notice?.text).toMatch(/carried by another transaction/);
	});

	it('drops a pick of a document that is gone, like any other stale choice', async () => {
		const { flow, h } = setup();
		await settle();
		vi.mocked(previewUnit).mockResolvedValueOnce(
			answer(null, {
				problems: [
					problem('stale_reference', { entry_id: 1, field: 'document_id', detail: { id: 7 } })
				]
			})
		);
		flow.pickDocument(1, { id: 7, version: 2 });
		await settle();

		expect(flow.draft?.documentEdit(1)).toBeUndefined();
		expect(h.reloadLookups).toHaveBeenCalled();
		expect(flow.notice?.text).toBe('The document you chose no longer exists. Choose again.');
	});

	it('keeps a pick of the wrong provider, shown as the problem it is', async () => {
		const { flow } = setup();
		await settle();
		vi.mocked(previewUnit).mockResolvedValue(
			answer(null, {
				problems: [problem('document_provider_mismatch', { entry_id: 1, field: 'document' })]
			})
		);
		flow.pickDocument(1, { id: 7, version: 2 });
		await settle();

		expect(flow.draft?.documentEdit(1)).toBeDefined();
		expect(flow.commitReason).toMatch(/another provider/);
	});
});

describe('a commit refused for the document', () => {
	async function refused(failure: ApiError) {
		const ctx = setup();
		await settle();
		ctx.flow.pickDocument(1, { id: 7, version: 2 });
		await settle();
		vi.mocked(commitUnit).mockRejectedValueOnce(failure);
		await ctx.flow.commit();
		await settle();
		return ctx;
	}

	it('unit_moved, taken: reads the unit again, the pick is gone, and says why', async () => {
		const now = unit({
			anchor_entry_id: 1,
			entries: [entry({ id: 1, version: 5, unit_key: 1, source_transaction_id: 5 })]
		});
		vi.mocked(getUnit).mockResolvedValue(now);

		const { flow, h } = await refused(
			error(409, 'unit_moved', { reason: 'taken', document_id: 7 })
		);

		expect(getUnit).toHaveBeenCalledWith(1);
		expect(h.unitChanged).toHaveBeenCalledWith(now);
		expect(flow.draft?.documentEdit(1)).toBeUndefined();
		expect(flow.draft?.versions).toEqual({ 1: 5 });
		expect(flow.notice).toMatchObject({ kind: 'conflict' });
		expect(flow.notice?.text).toMatch(/carried by another transaction/);
		expect(h.committed).not.toHaveBeenCalled();
	});

	it('unit_moved, version: the same, saying the document changed', async () => {
		const { flow } = await refused(error(409, 'unit_moved', { reason: 'version', document_id: 7 }));

		expect(flow.draft?.documentEdit(1)).toBeUndefined();
		expect(flow.notice?.text).toMatch(/changed after you saw it/);
	});

	it('unit_moved for any other reason keeps the pick', async () => {
		const { flow } = await refused(error(409, 'unit_moved', { anchor_entry_id: 1 }));

		expect(flow.draft?.documentEdit(1)).toBeDefined();
		expect(flow.notice?.text).toMatch(/changed shape/);
	});

	it('stale_reference of the document: forgets the pick like the other stale cases', async () => {
		const { flow, h } = await refused(
			error(409, 'stale_reference', { field: 'document_id', entity: 'document', id: 7 })
		);

		expect(flow.draft?.documentEdit(1)).toBeUndefined();
		expect(h.reloadLookups).toHaveBeenCalled();
		expect(flow.notice).toMatchObject({ kind: 'conflict' });
		expect(flow.notice?.text).toMatch(/document you chose no longer exists/);
	});

	it.each([
		['document_not_original', 'original entry of a transaction'],
		['invalid_document', 'cannot be used as it stands']
	])('says an invalid draft by its %s code', async (code, text) => {
		const { flow } = await refused(error(422, 'invalid_draft', { code }));

		expect(flow.notice?.kind).toBe('error');
		expect(flow.notice?.text).toContain(text);
	});
});

describe('editing the amount of a row of the split along the lines', () => {
	const twoLines = () =>
		answer(
			rowDocument({
				document: doc,
				split: { document_id: 7, available: true, proposed: true, replaces_stored_split: false }
			}),
			{ rows: [lineRow(-900, 1, -2000), lineRow(-901, 2, -3000), lineRow(-902, 3, -1000)] }
		);

	/** A server that echoes the rows the request names once it names any, else proposes them. */
	function echoing() {
		vi.mocked(previewUnit).mockImplementation(async (request) => {
			const named = request.entries!.filter((x) => x.document_line);
			if (named.length === 0) return twoLines();
			const base = twoLines();
			base.rows = [base.rows[0], ...base.rows.filter((r) => named.some((x) => x.id === r.id))];
			return base;
		});
	}

	it('keeps the row, its place and its last amount through a preview when the text is cleared', async () => {
		echoing();
		const { flow } = setup();
		await settle();
		expect(flow.draft?.lineRows.map((r) => r.id)).toEqual([-900, -901, -902]);

		flow.setAmountText(-901, '');
		await vi.advanceTimersByTimeAsync(500); // typing alone previews nothing
		await settle();
		expect(flow.draft?.lineRows.map((r) => r.id)).toEqual([-900, -901, -902]);
		flow.applyAmountText(-901);
		await vi.advanceTimersByTimeAsync(500);
		await settle();

		expect(flow.draft?.lineRows.map((r) => r.id)).toEqual([-900, -901, -902]);
		expect(flow.draft?.edit(-901).amount).toBe(-3000);
		expect(flow.draft!.toRequest().entries!.map((x) => x.id)).toEqual([-900, -901, -902]);
		expect(flow.commitReason).toBe('An amount is not valid.');

		flow.setAmountText(-901, '35.00');
		flow.applyAmountText(-901);
		await settle();

		expect(flow.draft?.edit(-901).amount).toBe(-3500);
		expect(lastRequest().entries!.find((x) => x.id === -901)!.amount).toBe(-3500);
		expect(flow.commitReason).not.toBe('An amount is not valid.');
	});

	it('drops a row the client left out of nothing: syncLineRows only forgets what the server dropped', async () => {
		echoing();
		const { flow } = setup();
		await settle();

		// the server drops a row of its own accord (the document is no longer the transaction’s)
		vi.mocked(previewUnit).mockResolvedValue(answer(rowDocument({ document: doc })));
		flow.pickDocument(1, { id: 8, version: 1 });
		await settle();

		expect(flow.draft?.lineRows).toEqual([]);
	});

	it('removes a row on the explicit action, and refuses the split when the last one goes', async () => {
		echoing();
		const { flow } = setup();
		await settle();

		flow.removeSplit(-901);
		await settle();
		expect(lastRequest().entries!.map((x) => x.id)).toEqual([-900, -902]);

		flow.removeSplit(-900);
		flow.removeSplit(-902);
		expect(flow.draft?.lineRows).toEqual([]);
		expect(original(lastRequest())!.document).toEqual({ mode: 'keep', decline_split: true });
	});
});
