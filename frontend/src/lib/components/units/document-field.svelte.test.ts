import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { documentDetail, documentRow } from '#lib/documents/fixtures.js';
import { account, category, entry, payee } from '#lib/ledger/fixtures.js';
import { buildLookups } from '#lib/ledger/lookups.js';
import { ruleNames } from '#lib/stores/rule-names.svelte.js';
import {
	committed,
	documentSummary,
	preview,
	previewRowOf,
	problem,
	rowDocument,
	unit
} from '#lib/units/fixtures.js';
import { UnitPanel, type PanelNav } from '#lib/units/panel.svelte.js';
import type { PreviewRow, RowDocument, UnitDraftRequest } from '#lib/units/types.js';
import UnitPanelView from './unit-panel.svelte';

// components never import the API, not even in tests: the mocks come from here
const api = vi.hoisted(() => ({
	getUnit: vi.fn(),
	listRules: vi.fn(),
	previewUnit: vi.fn(),
	commitUnit: vi.fn(),
	listDocuments: vi.fn(),
	getDocument: vi.fn()
}));
vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	...api
}));
const { getUnit, listRules, previewUnit, commitUnit, listDocuments, getDocument } = api;

const lookups = buildLookups({
	accounts: [account({ id: 1, name: 'Giro' })],
	categories: [category({ id: 10, name: 'Groceries' })],
	payees: [payee({ id: 20, name: 'Amazon' })]
});

function nav(): PanelNav {
	const stack = ['/review'];
	let at = 0;
	return {
		url: () => new URL(stack[at], 'http://x.test'),
		push: (url) => {
			stack.splice(at + 1);
			stack.push(url);
			at++;
		},
		replace: (url) => (stack[at] = url),
		back: () => at--
	};
}

const e = entry({
	id: 1,
	version: 3,
	unit_key: 1,
	source_transaction_id: 5,
	account_id: 1,
	amount: { amount: -4731, currency: 'EUR' },
	booked_on: '2026-10-09',
	type: 'flow',
	category_id: 10,
	derivation: {},
	review_flags: ['unconfirmed', 'document_suggested']
});
const shown = unit({ anchor_entry_id: 1, entries: [e] });

/** `document` of the original's row, as a function of the request (the server answers the draft). */
type Say = RowDocument | null | ((request: UnitDraftRequest) => RowDocument | null);

async function open(
	say: Say,
	options: {
		problems?: (request: UnitDraftRequest) => ReturnType<typeof problem>[];
		rows?: (request: UnitDraftRequest) => PreviewRow[];
	} = {}
) {
	vi.mocked(getUnit).mockResolvedValue(shown);
	vi.mocked(previewUnit).mockImplementation(async (request: UnitDraftRequest) => {
		const out = preview(shown);
		out.rows[0].document = typeof say === 'function' ? say(request) : say;
		out.rows.push(...(options.rows?.(request) ?? []));
		out.problems = options.problems?.(request) ?? [];
		return out;
	});
	const panel = new UnitPanel(nav());
	render(UnitPanelView, { props: { panel, lookups, locale: 'en' } });
	panel.open(1);
	const dialog = await screen.findByRole('dialog', { name: /./ });
	await waitFor(() => expect(panel.flow.previewStatus).toBe('ready'));
	return { panel, dialog };
}

const requests = () => vi.mocked(previewUnit).mock.calls.map((c) => c[0] as UnitDraftRequest);
const lastRequest = () => requests().at(-1)!;
const originalOf = (request: UnitDraftRequest) => request.entries?.find((x) => x.id === 1);
const fieldOf = (dialog: HTMLElement) =>
	dialog.querySelector<HTMLElement>('[data-slot="document"]');
const settled = (panel: UnitPanel) => waitFor(() => expect(panel.flow.previewStatus).toBe('ready'));

beforeEach(() => {
	vi.resetAllMocks();
	ruleNames.reset();
	vi.mocked(listRules).mockResolvedValue([]);
	vi.mocked(listDocuments).mockResolvedValue({
		documents: [],
		total: 0,
		limit: 20,
		offset: 0
	});
});
afterEach(() => cleanup());

describe('the document field', () => {
	it('is not there where the preview has nothing to say', async () => {
		const { dialog } = await open(null);

		expect(fieldOf(dialog)).toBeNull();
	});

	it('shows the document the transaction carries, with the words for how it was matched', async () => {
		const { dialog } = await open(
			rowDocument({
				stored_document_id: 7,
				document: documentSummary(),
				key: { pass: 'matcher_decision', basis: {} }
			})
		);

		const field = fieldOf(dialog)!;
		expect(field).toHaveAttribute('data-state', 'linked');
		expect(field).toHaveTextContent('amazon');
		expect(field).toHaveTextContent('Oct 8, 2026');
		expect(field).toHaveTextContent('47.31');
		expect(field).toHaveTextContent('Amazon · Order 304-7');
		expect(field).toHaveTextContent('2 lines');
		expect(field).toHaveTextContent('document matched');
		expect(within(field).getByRole('button', { name: 'Pick another document…' })).toBeVisible();
		expect(within(field).getByRole('button', { name: 'Look for a document' })).toBeVisible();
	});

	it('shows a document matched with a proposal in italic, to check the split', async () => {
		const { dialog } = await open(
			rowDocument({
				document: documentSummary(),
				key: { pass: 'matcher_proposal', basis: {} }
			})
		);

		const evidence = fieldOf(dialog)!.querySelector('[data-slot="evidence"]')!;
		expect(evidence).toHaveTextContent('document matched — check the split');
		expect(evidence).toHaveAttribute('data-proposal');
	});

	it('says a stored decision of no document', async () => {
		const { dialog } = await open(rowDocument({ key: { pass: 'user', basis: {} } }));

		const field = fieldOf(dialog)!;
		expect(field).toHaveAttribute('data-state', 'none');
		expect(field).toHaveTextContent('No document');
	});

	it('takes the document picked by hand from the list of the payee’s provider', async () => {
		vi.mocked(listDocuments).mockResolvedValue({
			documents: [documentRow({ id: 21, version: 4, title: 'Order 21', merchant_name: null })],
			total: 1,
			limit: 20,
			offset: 0
		});
		const { dialog, panel } = await open(
			rowDocument({ suggestions: [documentSummary()], decision_required: true })
		);

		await fireEvent.click(
			within(fieldOf(dialog)!).getByRole('button', { name: 'Pick a document…' })
		);
		const list = await screen.findByRole('listbox', { name: 'Documents' });
		const found = await within(list).findByRole('option', { name: /Order 21/ });

		expect(listDocuments).toHaveBeenCalledWith(
			{ provider: ['amazon'], q: '', fully_charged: false },
			expect.anything()
		);
		await fireEvent.click(found);
		await settled(panel);

		expect(originalOf(lastRequest())!.document).toEqual({
			mode: 'pick',
			document_id: 21,
			document_version: 4,
			decline_split: false
		});
	});

	it('offers the suggestions nearest first, with what they share with the entry', async () => {
		const { dialog, panel } = await open((request) =>
			originalOf(request)?.document?.mode === 'pick'
				? rowDocument({
						document: documentSummary({ id: 8, version: 6 }),
						key: { pass: 'user', basis: {} }
					})
				: rowDocument({
						decision_required: true,
						suggestions: [
							documentSummary({ id: 7, occurred_on: '2026-10-09' }),
							documentSummary({
								id: 8,
								version: 6,
								occurred_on: '2026-10-06',
								total: { amount: -5000, currency: 'EUR' }
							})
						]
					})
		);
		const field = fieldOf(dialog)!;
		expect(field).toHaveTextContent('2 documents are suggested');

		await fireEvent.click(within(field).getByRole('button', { name: 'Pick a document…' }));
		const list = await screen.findByRole('listbox', { name: 'Documents' });
		const options = within(list).getAllByRole('option');

		expect(options[0]).toHaveTextContent('exact amount · same day');
		expect(options[1]).toHaveTextContent('2.69 more · 3 days before');
		await fireEvent.click(options[1]);
		await settled(panel);

		expect(originalOf(lastRequest())!.document).toMatchObject({
			mode: 'pick',
			document_id: 8,
			document_version: 6
		});
		expect(field).toHaveAttribute('data-state', 'picked');
		expect(field).toHaveTextContent('picked by you');
		expect(within(field).getByRole('button', { name: 'Pick another document…' })).toBeVisible();
	});

	it('"None of these" decides there is no document, and Reset to proposal takes it back', async () => {
		const { dialog, panel } = await open((request) =>
			originalOf(request)?.document?.mode === 'none'
				? rowDocument({ suggestions: [documentSummary()] })
				: rowDocument({ suggestions: [documentSummary()], decision_required: true })
		);
		const field = fieldOf(dialog)!;

		await fireEvent.click(within(field).getByRole('button', { name: 'Pick a document…' }));
		const list = await screen.findByRole('listbox', { name: 'Documents' });
		await fireEvent.click(within(list).getByRole('option', { name: 'None of these' }));
		await settled(panel);

		expect(originalOf(lastRequest())!.document).toMatchObject({ mode: 'none' });
		expect(field).toHaveAttribute('data-state', 'none');
		expect(field).toHaveTextContent('no document');

		await fireEvent.click(within(field).getByRole('button', { name: 'Reset to proposal' }));
		await settled(panel);

		expect(originalOf(lastRequest())).toBeUndefined();
		expect(field).toHaveAttribute('data-state', 'open');
	});

	it('resolves again on request: the decision and the link are dropped', async () => {
		const { dialog, panel } = await open(
			rowDocument({ document: documentSummary(), key: { pass: 'matcher_decision', basis: {} } })
		);

		await fireEvent.click(
			within(fieldOf(dialog)!).getByRole('button', { name: 'Look for a document' })
		);
		await settled(panel);

		expect(originalOf(lastRequest())!.document).toMatchObject({ mode: 'reresolve' });
		expect(fieldOf(dialog)).toHaveTextContent('Matched again when you commit');
	});

	it('offers to look for a document where the matcher decided there is none', async () => {
		const { dialog, panel } = await open(
			rowDocument({ key: { pass: 'matcher_decision', basis: {} } })
		);

		const field = fieldOf(dialog)!;
		await fireEvent.click(within(field).getByRole('button', { name: 'Look for a document' }));
		await settled(panel);

		expect(originalOf(lastRequest())!.document).toMatchObject({ mode: 'reresolve' });
		expect(field).toHaveTextContent('Matched again when you commit');
	});

	it('does not offer it where documents are only suggested', async () => {
		const { dialog } = await open(
			rowDocument({ suggestions: [documentSummary()], decision_required: true })
		);

		expect(
			within(fieldOf(dialog)!).queryByRole('button', { name: 'Look for a document' })
		).toBeNull();
	});

	it('shows the lines of the document only when asked, fetched once, the entry’s own line marked', async () => {
		vi.mocked(getDocument).mockResolvedValue(documentDetail({ id: 7 }));
		const { dialog } = await open(
			rowDocument({
				stored_document_id: 7,
				document: documentSummary(),
				key: { pass: 'matcher_decision', basis: {} }
			})
		);
		const field = fieldOf(dialog)!;
		expect(getDocument).not.toHaveBeenCalled();
		expect(field.querySelector('[data-slot="document-lines"]')).toBeNull();

		const toggle = within(field).getByRole('button', { name: 'Show lines' });
		expect(toggle).toHaveAttribute('aria-expanded', 'false');
		await fireEvent.click(toggle);

		expect(await within(field).findByText('USB cable')).toBeVisible();
		expect(within(field).getByText('Book')).toBeVisible();
		expect(getDocument).toHaveBeenCalledTimes(1);
		expect(getDocument.mock.calls[0][0]).toBe(7);
		expect(within(field).getByRole('button', { name: 'Hide lines' })).toHaveAttribute(
			'aria-expanded',
			'true'
		);

		await fireEvent.click(within(field).getByRole('button', { name: 'Hide lines' }));
		expect(field.querySelector('[data-slot="document-lines"]')).toBeNull();
		await fireEvent.click(within(field).getByRole('button', { name: 'Show lines' }));
		expect(await within(field).findByText('USB cable')).toBeVisible();
		expect(getDocument).toHaveBeenCalledTimes(1);
	});

	it('says when the lines could not be loaded', async () => {
		vi.mocked(getDocument).mockRejectedValue(new Error('down'));
		const { dialog } = await open(
			rowDocument({ stored_document_id: 7, document: documentSummary(), key: null })
		);
		const field = fieldOf(dialog)!;

		await fireEvent.click(within(field).getByRole('button', { name: 'Show lines' }));

		expect(await within(field).findByText('The lines could not be loaded.')).toBeVisible();
	});

	it('has no lines toggle where no document is carried', async () => {
		const { dialog } = await open(rowDocument({ key: { pass: 'user', basis: {} } }));

		expect(within(fieldOf(dialog)!).queryByRole('button', { name: 'Show lines' })).toBeNull();
	});

	it('says a payee with no provider has nothing to find by hand', async () => {
		const { dialog } = await open(rowDocument({ key: { pass: 'user', basis: {} } }));

		await fireEvent.click(
			within(fieldOf(dialog)!).getByRole('button', { name: 'Pick a document…' })
		);

		expect(await screen.findByText(/Set a document provider on the payee/)).toBeVisible();
		expect(listDocuments).not.toHaveBeenCalled();
	});
});

describe('waiting for a document', () => {
	const decision = problem('document_decision_required', { entry_id: 1, field: 'document' });
	const waiting = (request: UnitDraftRequest) =>
		originalOf(request)?.document?.mode === 'none'
			? rowDocument({ waiting: { provider: 'amazon', covered_through: '2026-10-12' } })
			: rowDocument({
					waiting: { provider: 'amazon', covered_through: '2026-10-12' },
					decision_required: true
				});
	const needsDecision = (request: UnitDraftRequest) =>
		originalOf(request)?.document?.mode === 'none' ? [] : [decision];

	it('says what is awaited and how far the provider is covered', async () => {
		const { dialog } = await open(waiting, { problems: needsDecision });

		expect(fieldOf(dialog)).toHaveTextContent(
			/Waiting for a document from amazon, covered through Oct 12, 2026/
		);
	});

	it('says a provider that has not synced yet', async () => {
		const { dialog } = await open(
			rowDocument({
				waiting: { provider: 'amazon', covered_through: null },
				decision_required: true
			}),
			{ problems: () => [decision] }
		);

		expect(fieldOf(dialog)).toHaveTextContent('Waiting for a document from amazon, not synced yet');
	});

	it('holds the commit back with the reason, and never sends one the server would refuse', async () => {
		const { dialog, panel } = await open(waiting, { problems: needsDecision });

		const commit = within(dialog).getByRole('button', { name: 'Commit' });
		expect(commit).toBeDisabled();
		expect(panel.flow.commitReason).toMatch(/Pick one, or commit without a document/);
		await fireEvent.keyDown(dialog, { key: 'Enter', ctrlKey: true });
		await Promise.resolve();

		expect(commitUnit).not.toHaveBeenCalled();
	});

	it('commits without a document only after the user chose it, and then sends none', async () => {
		vi.mocked(commitUnit).mockResolvedValue(committed(shown));
		const { dialog, panel } = await open(waiting, { problems: needsDecision });
		const field = fieldOf(dialog)!;

		await fireEvent.click(within(field).getByRole('button', { name: 'Commit without a document' }));
		await settled(panel);

		expect(originalOf(lastRequest())!.document).toEqual({ mode: 'none', decline_split: false });
		expect(field).toHaveAttribute('data-state', 'none');
		expect(within(field).queryByRole('button', { name: 'Commit without a document' })).toBeNull();
		const commit = within(dialog).getByRole('button', { name: 'Commit' });
		expect(commit).toBeEnabled();

		await fireEvent.click(commit);
		await waitFor(() => expect(commitUnit).toHaveBeenCalled());
		expect(vi.mocked(commitUnit).mock.calls[0][0].entries).toEqual([
			{ id: 1, document: { mode: 'none', decline_split: false } }
		]);
	});

	it('does not offer the choice where no decision is required', async () => {
		const { dialog } = await open(
			rowDocument({ document: documentSummary(), key: { pass: 'matcher_decision', basis: {} } })
		);

		expect(
			within(fieldOf(dialog)!).queryByRole('button', { name: 'Commit without a document' })
		).toBeNull();
	});
});

describe('the split along the lines', () => {
	const linked = (over: Partial<NonNullable<RowDocument['split']>>) =>
		rowDocument({
			stored_document_id: 7,
			document: documentSummary(),
			key: { pass: 'matcher_decision', basis: {} },
			split: {
				document_id: 7,
				available: true,
				proposed: false,
				replaces_stored_split: false,
				...over
			}
		});
	const lineRow = (id: number, lineNo: number, amount: number) =>
		previewRowOf(e, {
			id,
			original: false,
			version: null,
			amount: { amount, currency: 'EUR' },
			document_line: { document_id: 7, line_no: lineNo, description: `Line ${lineNo}` }
		});

	it('is offered as an explicit choice, and sent as split_along_lines with the document’s version', async () => {
		const { dialog, panel } = await open(linked({}));

		await fireEvent.click(
			within(fieldOf(dialog)!).getByRole('button', { name: 'Split along the lines' })
		);
		await settled(panel);

		const sent = originalOf(lastRequest())!;
		expect(sent.document).toEqual({
			mode: 'split_along_lines',
			document_id: 7,
			document_version: 2,
			decline_split: false
		});
		expect(lastRequest().anchor_entry_id).toBe(1);
	});

	it('names what it deletes where it replaces an existing split', async () => {
		const { dialog } = await open(linked({ replaces_stored_split: true }));

		expect(fieldOf(dialog)).toHaveTextContent(/replaces the existing split/);
		expect(fieldOf(dialog)).toHaveTextContent(/listed\s+under Deleted/);
	});

	it('is not offered where it is unavailable', async () => {
		const { dialog } = await open(linked({ available: false }));

		expect(
			within(fieldOf(dialog)!).queryByRole('button', { name: 'Split along the lines' })
		).toBeNull();
	});

	it('shows the proposed rows like the other split rows, each with its line, and no change yet', async () => {
		const { dialog, panel } = await open(linked({ proposed: true }), {
			rows: (request) =>
				request.entries?.length ? [] : [lineRow(-900, 2, -3231), lineRow(-901, 3, -500)]
		});
		await waitFor(() => expect(panel.flow.draft?.lineRows).toHaveLength(2));

		const editors = dialog.querySelectorAll('[data-slot="entry-editor"]');
		expect(editors).toHaveLength(3);
		expect(dialog).toHaveTextContent('Line 2 of the document');
		expect(dialog).toHaveTextContent('Line 3 of the document');
		expect(fieldOf(dialog)).toHaveTextContent('one entry per line');
		expect(panel.flow.isDirty).toBe(false);
	});

	it('is refused by "Keep one entry": the rows go and decline_split is sent', async () => {
		const { dialog, panel } = await open(linked({ proposed: true }), {
			rows: (request) => (request.entries?.length ? [] : [lineRow(-900, 2, -3231)])
		});
		await waitFor(() => expect(panel.flow.draft?.lineRows).toHaveLength(1));

		await fireEvent.click(within(fieldOf(dialog)!).getByRole('button', { name: 'Keep one entry' }));
		await settled(panel);

		expect(originalOf(lastRequest())!.document).toEqual({ mode: 'keep', decline_split: true });
		expect(lastRequest().entries!.every((x) => x.id > 0)).toBe(true);
		expect(panel.flow.draft?.lineRows).toEqual([]);
	});

	it('echoes the proposed row once it is edited, and offers to reset the split', async () => {
		const { dialog, panel } = await open(linked({ proposed: true }), {
			rows: (request) =>
				request.entries?.some((x) => x.id === -900) || !request.entries?.length
					? [lineRow(-900, 2, -3231)]
					: []
		});
		await waitFor(() => expect(panel.flow.draft?.lineRows).toHaveLength(1));
		expect(
			within(fieldOf(dialog)!).queryByRole('button', { name: 'Reset split to proposal' })
		).toBeNull();

		const row = dialog.querySelector<HTMLElement>('[data-entry-id="-900"]')!;
		await fireEvent.input(within(row).getByLabelText('Note'), { target: { value: 'cables' } });
		await waitFor(() =>
			expect(lastRequest().entries!.find((x) => x.id === -900)).toMatchObject({
				source_entry_id: 1,
				amount: -3231,
				note: 'cables',
				document_line: { document_id: 7, line_no: 2 }
			})
		);

		await settled(panel);
		await fireEvent.click(
			within(fieldOf(dialog)!).getByRole('button', { name: 'Reset split to proposal' })
		);
		await settled(panel);

		// the proposal again: the server's rows are taken over, with no edit of the user's
		await waitFor(() => expect(panel.flow.draft?.lineRows).toHaveLength(1));
		expect(panel.flow.draft?.edit(-900).note).toBeUndefined();
		expect(panel.flow.isDirty).toBe(false);
	});
});
