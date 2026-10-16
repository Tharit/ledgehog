import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { account } from '#lib/ledger/fixtures.js';
import { entry } from '#lib/ledger/fixtures.js';
import { buildLookups } from '#lib/ledger/lookups.js';
import { rule } from '#lib/rules/fixtures.js';
import { ruleNames } from '#lib/stores/rule-names.svelte.js';
import type { PreviewRow, UnitDraftRequest } from '#lib/units/types.js';
import { documentSummary, preview, previewRowOf, rowDocument, unit } from '#lib/units/fixtures.js';
import { UnitPanel, type PanelNav } from '#lib/units/panel.svelte.js';
import UnitPanelView from './unit-panel.svelte';

// The amount of a split entry is typed locally: it is applied (and previewed) when the field is
// left or Enter is pressed, never while it is typed in. A text that is no amount over a row that
// already has one changes nothing but the field's own error: no row moves, none goes.
const api = vi.hoisted(() => ({
	getUnit: vi.fn(),
	listRules: vi.fn(),
	previewUnit: vi.fn(),
	commitUnit: vi.fn(),
	createTag: vi.fn()
}));
vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	...api
}));
const { getUnit, listRules, previewUnit } = api;

const lookups = buildLookups({ accounts: [account({ id: 1, name: 'Giro' })] });

function nav(): PanelNav {
	const stack = ['/review'];
	return {
		url: () => new URL(stack[0], 'http://x.test'),
		push: () => {},
		replace: () => {},
		back: () => {}
	};
}

const original = entry({
	id: 1,
	unit_key: 1,
	source_transaction_id: 5,
	amount: { amount: -10000, currency: 'EUR' }
});
const sibling = entry({
	id: 2,
	unit_key: 1,
	source_transaction_id: 5,
	amount: { amount: -2500, currency: 'EUR' }
});

const rowFor = (id: number, amount: number, over: Partial<PreviewRow> = {}) =>
	previewRowOf(entry({ id, amount: { amount, currency: 'EUR' } }), {
		version: null,
		original: false,
		source_transaction_id: 5,
		...over
	});

/** What a server answers: the new rows the request echoes in its order, the original as residual. */
function answer(base: ReturnType<typeof unit>, request: UnitDraftRequest, withLines = false) {
	const out = preview(base);
	const echoed = (request.entries ?? []).filter((e) => e.id < 0 && e.amount != null);
	const lines = echoed.some((e) => e.document_line)
		? echoed
		: withLines
			? [
					{ id: -900, amount: -2000, document_line: { document_id: 7, line_no: 1 } },
					{ id: -901, amount: -3000, document_line: { document_id: 7, line_no: 2 } },
					{ id: -902, amount: -1000, document_line: { document_id: 7, line_no: 3 } }
				]
			: echoed;
	const first = out.rows[0];
	const extra = out.rows.slice(1).map((r) => {
		const sent = (request.entries ?? []).find((e) => e.id === r.id);
		return sent?.amount != null ? { ...r, amount: { ...r.amount, amount: sent.amount } } : r;
	});
	const taken = lines.reduce((s, e) => s + (e.amount ?? 0), 0);
	const rows = [
		{
			...first,
			amount: { ...first.amount, amount: first.amount.amount - taken },
			document: withLines ? rowDocument({ document: documentSummary() }) : first.document
		},
		...extra,
		...lines.map((e) =>
			rowFor(e.id, e.amount ?? 0, {
				document_line: 'document_line' in e ? (e.document_line as never) : undefined
			})
		)
	];
	out.rows = rows as PreviewRow[];
	return out;
}

async function openPanel(shown: ReturnType<typeof unit>, withLines = false) {
	vi.mocked(getUnit).mockResolvedValue(shown);
	vi.mocked(previewUnit).mockImplementation(async (request: UnitDraftRequest) =>
		answer(shown, request, withLines)
	);
	const panel = new UnitPanel(nav());
	render(UnitPanelView, { props: { panel, lookups, locale: 'en' } });
	panel.open(shown.anchor_entry_id);
	const dialog = await screen.findByRole('dialog', { name: /./ });
	await waitFor(() => expect(panel.flow.previewStatus).toBe('ready'));
	return { panel, dialog };
}

const lastRequest = (): UnitDraftRequest =>
	vi.mocked(previewUnit).mock.calls.at(-1)![0] as UnitDraftRequest;
const calls = () => vi.mocked(previewUnit).mock.calls.length;
const commitButton = (dialog: HTMLElement) =>
	within(dialog).getByRole('button', { name: 'Commit' });
/** The text of every amount field, in the order the rows stand. */
const amounts = (dialog: HTMLElement) =>
	[...dialog.querySelectorAll<HTMLInputElement>('[data-slot="amount-field"] input')].map(
		(i) => i.value
	);
const field = (dialog: HTMLElement, index: number): HTMLInputElement =>
	dialog.querySelectorAll<HTMLInputElement>('[data-slot="amount-field"] input')[index];
/** Let the preview a change schedules come and go: what is counted next is the field's doing. */
const rest = () => new Promise((r) => setTimeout(r, 450));
const newAmount = (dialog: HTMLElement) =>
	within(dialog).findByLabelText<HTMLInputElement>('Amount of the new split');
const type = (input: HTMLElement, value: string) => fireEvent.input(input, { target: { value } });

beforeEach(() => {
	vi.resetAllMocks();
	ruleNames.reset();
	vi.mocked(listRules).mockResolvedValue([rule({ id: 3, name: 'Rewe' })]);
});
afterEach(cleanup);

/** The original with two added rows of 20.00 and 30.00, settled. */
async function threeRegular() {
	const shown = unit({ anchor_entry_id: 1, entries: [original] });
	const opened = await openPanel(shown);
	for (const [id, text] of [
		[-1, '20.00'],
		[-2, '30.00']
	] as const) {
		opened.panel.flow.addSplit(1);
		opened.panel.flow.setAmountText(id, text);
		opened.panel.flow.applyAmountText(id);
		await waitFor(() => expect(opened.panel.flow.previewStatus).toBe('ready'));
	}
	await waitFor(() => expect(amounts(opened.dialog)).toEqual(['20.00', '30.00']));
	return opened;
}

describe('typing an amount', () => {
	it('is local: nothing is previewed until the field is left', async () => {
		const { dialog, panel } = await openPanel(unit({ anchor_entry_id: 1, entries: [original] }));
		panel.flow.addSplit(1);
		const input = await newAmount(dialog);
		await rest();
		const before = calls();

		await type(input, '1');
		await type(input, '12');
		await type(input, '12.5');
		await new Promise((r) => setTimeout(r, 450)); // past the preview delay

		expect(calls()).toBe(before);
		await fireEvent.blur(input);
		await waitFor(() =>
			expect(lastRequest().entries).toEqual([{ id: -1, source_entry_id: 1, amount: -1250 }])
		);
	});

	it('applies on Enter as well', async () => {
		const { dialog, panel } = await openPanel(unit({ anchor_entry_id: 1, entries: [original] }));
		panel.flow.addSplit(1);
		const input = await newAmount(dialog);

		await type(input, '12.00');
		await fireEvent.keyDown(input, { key: 'Enter' });

		await waitFor(() =>
			expect(lastRequest().entries).toEqual([{ id: -1, source_entry_id: 1, amount: -1200 }])
		);
	});

	it('a valid number typed and cleared before the field is left sends nothing', async () => {
		const { dialog, panel } = await openPanel(unit({ anchor_entry_id: 1, entries: [original] }));
		panel.flow.addSplit(1);
		const input = await newAmount(dialog);
		await rest();
		const before = calls();

		await type(input, '12.00');
		await type(input, '');
		await fireEvent.blur(input);
		await new Promise((r) => setTimeout(r, 450));

		expect(calls()).toBe(before);
		expect(panel.flow.draft?.pendingSplits).toHaveLength(1);
	});

	it('blur with the text unchanged does nothing', async () => {
		const { dialog, panel } = await openPanel(unit({ anchor_entry_id: 1, entries: [original] }));
		panel.flow.addSplit(1);
		const input = await newAmount(dialog);
		await fireEvent.focus(input);
		await rest();
		const before = calls();

		await fireEvent.blur(input);

		expect(calls()).toBe(before);
		expect(panel.flow.amountErrors[-1]).toBeUndefined();
		expect(panel.flow.commitReason).toBe('Enter the amount of the new split.');
	});
});

describe('an amount that is no amount, over a row that has one', () => {
	it.each([
		['empty', ''],
		['zero', '0'],
		['zero with decimals', '0.00'],
		['not a number', 'abc']
	])('%s: a regular split keeps its place and its amount', async (_name, text) => {
		const { dialog, panel } = await threeRegular();
		await rest();
		const before = calls();

		await type(field(dialog, 0), text);
		await fireEvent.blur(field(dialog, 0));
		await new Promise((r) => setTimeout(r, 450));

		expect(calls()).toBe(before);
		expect(lastRequest().entries).toEqual([
			{ id: -1, source_entry_id: 1, amount: -2000 },
			{ id: -2, source_entry_id: 1, amount: -3000 }
		]);
		expect(panel.flow.draft?.splits.map((s) => s.id)).toEqual([-1, -2]);
		expect(panel.flow.draft?.pendingSplits).toEqual([]);
		// the field says what was typed, the preview keeps the last valid amount
		expect(field(dialog, 0).value).toBe(text);
		expect(field(dialog, 1).value).toBe('30.00');
		expect(panel.flow.preview?.rows.filter((r) => r.id < 0).map((r) => r.id)).toEqual([-1, -2]);
	});

	it('is said at the field, and holds the commit back', async () => {
		const { dialog, panel } = await threeRegular();

		await type(field(dialog, 0), '');
		await fireEvent.blur(field(dialog, 0));

		expect(panel.flow.commitReason).toBe('An amount is not valid.');
		expect(await within(dialog).findByRole('alert')).toBeInTheDocument();
		await waitFor(() => expect(commitButton(dialog)).toBeDisabled());

		// a number again: the error goes, the amount is applied
		await type(field(dialog, 0), '25.00');
		await fireEvent.blur(field(dialog, 0));
		await waitFor(() =>
			expect(lastRequest().entries).toEqual([
				{ id: -1, source_entry_id: 1, amount: -2500 },
				{ id: -2, source_entry_id: 1, amount: -3000 }
			])
		);
		expect(panel.flow.commitReason).not.toBe('An amount is not valid.');
		expect(within(dialog).queryByRole('alert')).toBeNull();
	});

	it('a split along a document’s lines keeps every row, in order', async () => {
		const { dialog, panel } = await openPanel(
			unit({ anchor_entry_id: 1, entries: [original] }),
			true
		);
		await waitFor(() => expect(amounts(dialog)).toEqual(['20.00', '30.00', '10.00']));
		await rest();
		const before = calls();

		await type(field(dialog, 1), '');
		await fireEvent.blur(field(dialog, 1));
		await new Promise((r) => setTimeout(r, 450));

		expect(calls()).toBe(before);
		expect(panel.flow.draft?.lineRows.map((s) => s.id)).toEqual([-900, -901, -902]);
		expect(panel.flow.preview?.rows.filter((r) => r.id < 0).map((r) => r.id)).toEqual([
			-900, -901, -902
		]);
		expect(field(dialog, 1).value).toBe('');
		expect(field(dialog, 2).value).toBe('10.00');
		expect(panel.flow.commitReason).toBe('An amount is not valid.');
	});

	it('a stored extra entry of a split changes nothing either', async () => {
		const { dialog, panel } = await openPanel(
			unit({ anchor_entry_id: 1, entries: [original, sibling] })
		);
		await rest();
		const before = calls();
		const input = within(dialog).getByLabelText('Amount');

		await type(input, '');
		await fireEvent.blur(input);

		expect(calls()).toBe(before);
		expect(panel.flow.draft?.edit(2).amount).toBeUndefined();
		expect(panel.flow.commitReason).toBe('An amount is not valid.');
	});
});

describe('a newly added row that has no amount yet', () => {
	it('stays pending on focus and blur, with no error and no request', async () => {
		const { dialog, panel } = await openPanel(unit({ anchor_entry_id: 1, entries: [original] }));
		panel.flow.addSplit(1);
		const input = await newAmount(dialog);
		await rest();
		const before = calls();

		await fireEvent.focus(input);
		await type(input, '');
		await fireEvent.blur(input);

		expect(calls()).toBe(before);
		expect(panel.flow.amountErrors[-1]).toBeUndefined();
		expect(panel.flow.draft?.pendingSplits).toHaveLength(1);
		expect(panel.flow.commitReason).toBe('Enter the amount of the new split.');
	});
});
