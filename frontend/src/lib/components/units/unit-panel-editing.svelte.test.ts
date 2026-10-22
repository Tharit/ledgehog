import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { account, category, entry, payee, tag } from '#lib/ledger/fixtures.js';
import { buildLookups } from '#lib/ledger/lookups.js';
import { rule, source } from '#lib/rules/fixtures.js';
import { accounts as accountDialog } from '#lib/accounts/controller.svelte.js';
import { lookupsStore } from '#lib/stores/lookups.svelte.js';
import { ruleNames } from '#lib/stores/rule-names.svelte.js';
import type { UnitDraftRequest } from '#lib/units/types.js';
import {
	apiError,
	committed,
	consequence,
	fieldOut,
	preview,
	previewRowOf,
	problem,
	unit
} from '#lib/units/fixtures.js';
import { UnitPanel, type PanelNav } from '#lib/units/panel.svelte.js';
import { registerUnitSource } from '#lib/units/sources.js';
import UnitPanelView from './unit-panel.svelte';

// components never import the API, not even in tests: the mocks come from here
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
const { getUnit, listRules, previewUnit, commitUnit, createTag } = api;

const lookups = buildLookups({
	accounts: [
		account({ id: 1, name: 'Giro' }),
		account({ id: 2, name: 'Savings' }),
		account({ id: 3, name: 'Dollar cash', currency: 'USD' })
	],
	categories: [category({ id: 10, name: 'Groceries' }), category({ id: 11, name: 'Dining' })],
	payees: [payee({ id: 20, name: 'REWE' }), payee({ id: 21, name: 'Aldi' })],
	tags: [tag({ id: 30, name: 'Lisbon trip' }), tag({ id: 31, name: 'Holiday' })]
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

/** The preview a server would answer for a draft over `base`: just enough to see the panel react. */
function fakePreview(base: ReturnType<typeof unit>, draft: UnitDraftRequest) {
	const out = preview(base);
	for (const e of draft.entries ?? []) {
		const row = out.rows.find((r) => r.id === e.id);
		if (!row) continue;
		if (e.category?.mode === 'fixed')
			row.fields.category = fieldOut(e.category.value ?? null, { pass: 'user' });
		if (e.payee?.mode === 'fixed')
			row.fields.payee = fieldOut(e.payee.value ?? null, { pass: 'user' });
		if (e.type?.mode === 'fixed')
			row.fields.type = fieldOut(e.type.value ?? null, { pass: 'user' });
		if (e.tags) {
			const { add = [], remove = [] } = e.tags;
			row.tag_ids = [...row.tag_ids.filter((t) => !remove.includes(t)), ...add];
		}
		if (e.category?.mode === 'reresolve') {
			row.fields.category = fieldOut(11, { pass: 'history', basis: { agree: 1, of: 1 } });
		}
	}
	const splits = (draft.entries ?? []).filter((e) => e.id < 0);
	if (splits.length > 0) {
		const original = out.rows[0];
		const taken = splits.reduce((sum, e) => sum + (e.amount ?? 0), 0);
		for (const s of splits) {
			// a new row starts with what the original stores, the change on top
			const inherited = base.entries[0].tag_ids.filter((t) => !(s.tags?.remove ?? []).includes(t));
			out.rows.push(
				previewRowOf(
					entry({
						id: s.id,
						amount: { amount: s.amount ?? 0, currency: 'EUR' },
						tag_ids: [...inherited, ...(s.tags?.add ?? [])]
					}),
					{
						version: null,
						original: false,
						source_transaction_id: original.source_transaction_id
					}
				)
			);
		}
		original.amount = { amount: original.amount.amount - taken, currency: 'EUR' };
		out.splits = [
			{
				source_transaction_id: original.source_transaction_id,
				source_amount: base.entries[0].amount,
				residual_entry_id: original.id,
				residual_amount: original.amount,
				entry_ids: [original.id, ...splits.map((s) => s.id)]
			}
		];
	}
	return out;
}

async function openPanel(
	shown = unit({ anchor_entry_id: 1 }),
	props: Record<string, unknown> = {}
) {
	vi.mocked(getUnit).mockResolvedValue(shown);
	vi.mocked(previewUnit).mockImplementation(async (draft: UnitDraftRequest) =>
		fakePreview(shown, draft)
	);
	const panel = new UnitPanel(nav());
	render(UnitPanelView, { props: { panel, lookups, locale: 'en', ...props } });
	panel.open(shown.anchor_entry_id);
	const dialog = await screen.findByRole('dialog', { name: /./ });
	await waitFor(() => expect(panel.flow.previewStatus).toBe('ready'));
	return { panel, dialog };
}

const lastRequest = (): UnitDraftRequest =>
	vi.mocked(previewUnit).mock.calls.at(-1)![0] as UnitDraftRequest;

const commitButton = (dialog: HTMLElement) =>
	within(dialog).getByRole('button', { name: 'Commit' });

beforeEach(() => {
	vi.resetAllMocks();
	ruleNames.reset();
	vi.mocked(listRules).mockResolvedValue([rule({ id: 3, name: 'Rewe' })]);
});

async function openMenu(dialog: HTMLElement) {
	await fireEvent.keyDown(
		within(dialog).getByRole('button', { name: 'More actions for this unit' }),
		{
			key: 'Enter'
		}
	);
	await screen.findByRole('menu');
}

describe('the preview region', () => {
	it('says the state a commit leads to in plain words', async () => {
		const { dialog } = await openPanel(
			unit({ anchor_entry_id: 1, state: { confirmed: false, reasons: ['non_standing_keys'] } })
		);
		const region = within(dialog).getByRole('region', { name: 'Preview' });
		expect(region).toHaveTextContent('After this commit: Proposals to check');
	});

	it.each([
		[{ confirmed: true, reasons: [] }, 'Confirmed'],
		[{ confirmed: false, reasons: ['unpaired_transfer'] }, 'Waits for its partner'],
		[{ confirmed: false, reasons: ['incomplete'] }, 'Stays unclassified']
	] as const)('says %j as "%s"', async (state, words) => {
		const shown = unit({ anchor_entry_id: 1 });
		vi.mocked(getUnit).mockResolvedValue(shown);
		vi.mocked(previewUnit).mockResolvedValue(
			preview(shown, { state: { ...state, reasons: [...state.reasons] } })
		);
		const panel = new UnitPanel(nav());
		render(UnitPanelView, { props: { panel, lookups } });
		panel.open(1);
		const dialog = await screen.findByRole('dialog');

		expect(await within(dialog).findByText(words, { selector: 'strong' })).toBeInTheDocument();
	});

	it('says "Checking what would change…" politely while a preview is on its way', async () => {
		const { panel, dialog } = await openPanel();
		vi.mocked(previewUnit).mockImplementation(() => new Promise(() => {}));

		panel.flow.setField(1, 'category', 11);

		const status = await within(dialog).findByText('Checking what would change…');
		expect(status).toHaveAttribute('aria-live', 'polite');
	});

	it('has no status row while nothing is being checked; the live region stays for screen readers', async () => {
		const { dialog } = await openPanel();
		const region = within(dialog).getByRole('region', { name: 'Preview' });

		const status = region.querySelector('[data-slot="preview-status"]')!;

		expect(status).toHaveAttribute('aria-live', 'polite');
		expect(status).toHaveClass('sr-only');
		expect(status.textContent?.trim()).toBe('');
		// the first thing in the box is the result, not an empty row
		expect(region.firstElementChild).toBe(status.parentElement);
		expect(status.parentElement).toHaveClass('contents');
	});

	it('groups the consequences by effect, each a row that can be opened', async () => {
		const shown = unit({ anchor_entry_id: 1 });
		const left = previewRowOf(
			entry({ id: 9, version: 2, unit_key: 9, description: 'Partner leg' })
		);
		const gone = previewRowOf(entry({ id: 8, version: 2, unit_key: 9 }));
		vi.mocked(getUnit).mockResolvedValue(shown);
		vi.mocked(previewUnit).mockResolvedValue(
			preview(shown, {
				consequences: [
					consequence('left_behind', left),
					consequence('deleted', gone),
					consequence('returns_to_review', previewRowOf(entry({ id: 7, version: 1, unit_key: 7 })))
				]
			})
		);
		const panel = new UnitPanel(nav());
		render(UnitPanelView, { props: { panel, lookups } });
		panel.open(1);
		const dialog = await screen.findByRole('dialog');

		const returns = await within(dialog).findByRole('region', { name: 'Returns to review' });
		expect(returns).toHaveTextContent('Returns to review (1)');
		expect(within(dialog).getByRole('region', { name: 'Deleted' })).toBeInTheDocument();
		const behind = within(dialog).getByRole('region', { name: 'Left behind' });
		// returns-to-review comes before deleted, which comes before left behind
		const order = [...dialog.querySelectorAll('[data-slot="consequences"]')].map(
			(el) => (el as HTMLElement).dataset.kind
		);
		expect(order).toEqual(['returns_to_review', 'deleted', 'left_behind']);

		vi.mocked(getUnit).mockResolvedValue(unit({ anchor_entry_id: 9 }));
		await fireEvent.click(behind.querySelector('[data-entry-id="9"]')!);
		await waitFor(() => expect(panel.unitId).toBe(9));
	});

	it('asks before opening a consequence row from a dirty panel', async () => {
		const shown = unit({ anchor_entry_id: 1 });
		const other = previewRowOf(entry({ id: 9, version: 2, unit_key: 9 }));
		vi.mocked(getUnit).mockResolvedValue(shown);
		vi.mocked(previewUnit).mockResolvedValue(
			preview(shown, { consequences: [consequence('changed', other)] })
		);
		const panel = new UnitPanel(nav());
		render(UnitPanelView, { props: { panel, lookups } });
		panel.open(1);
		const dialog = await screen.findByRole('dialog', { name: /./ });
		await waitFor(() => expect(panel.flow.previewStatus).toBe('ready'));
		panel.flow.reresolve();
		await waitFor(() => expect(panel.flow.previewStatus).toBe('ready'));

		await fireEvent.click(
			await within(dialog)
				.findByText('Changed (1)')
				.then(() => dialog.querySelector('[data-entry-id="9"]')!)
		);

		expect(await screen.findByRole('dialog', { name: 'Discard changes?' })).toBeInTheDocument();
		expect(panel.unitId).toBe(1);
	});

	it('writes problems in plain words, with the remedy of the spec', async () => {
		const shown = unit({ anchor_entry_id: 1 });
		vi.mocked(getUnit).mockResolvedValue(shown);
		vi.mocked(previewUnit).mockResolvedValue(
			preview(shown, {
				problems: [
					problem('residual_zero', { entry_id: 1 }),
					problem('pair_unequal', { entry_id: 1, detail: { partner: 2, difference: -100 } }),
					problem('currency_rule', {
						entry_id: 1,
						field: 'counter_account',
						detail: { required: 'USD', actual: 'EUR' }
					})
				]
			})
		);
		const panel = new UnitPanel(nav());
		render(UnitPanelView, { props: { panel, lookups } });
		panel.open(1);
		const dialog = await screen.findByRole('dialog');

		const list = await within(dialog).findByRole('list', { name: 'Problems' });
		expect(list).toHaveTextContent('The split leaves nothing for the original entry.');
		expect(list).toHaveTextContent('Make the new amounts smaller, or remove one.');
		expect(list).toHaveTextContent('The two legs of this transfer differ by 1.00.');
		expect(list).toHaveTextContent('Split the difference off the larger leg as a flow');
		expect(list).toHaveTextContent('This transfer needs an account in USD, not EUR.');
		expect(
			within(list).getByRole('button', { name: 'Split off the difference' })
		).toBeInTheDocument();
	});
});

describe('Commit', () => {
	it('is enabled on an untouched unit once the preview is in: committing accepts what is shown', async () => {
		const { dialog } = await openPanel();
		expect(commitButton(dialog)).toBeEnabled();
	});

	it('is disabled while the preview loads, with that as its reason', async () => {
		const shown = unit({ anchor_entry_id: 1 });
		vi.mocked(getUnit).mockResolvedValue(shown);
		vi.mocked(previewUnit).mockImplementation(() => new Promise(() => {}));
		const panel = new UnitPanel(nav());
		render(UnitPanelView, { props: { panel, lookups } });
		panel.open(1);
		const dialog = await screen.findByRole('dialog');
		await waitFor(() => expect(panel.status).toBe('ready'));

		expect(commitButton(dialog)).toBeDisabled();
		expect(panel.flow.commitReason).toBe('Checking what would change…');
	});

	it('is disabled while a problem stands, with the problem as the reason', async () => {
		const shown = unit({ anchor_entry_id: 1 });
		vi.mocked(getUnit).mockResolvedValue(shown);
		vi.mocked(previewUnit).mockResolvedValue(
			preview(shown, { problems: [problem('own_counter_account', { entry_id: 1 })] })
		);
		const panel = new UnitPanel(nav());
		render(UnitPanelView, { props: { panel, lookups } });
		panel.open(1);
		const dialog = await screen.findByRole('dialog');
		await waitFor(() => expect(panel.flow.previewStatus).toBe('ready'));

		expect(commitButton(dialog)).toBeDisabled();
		expect(panel.flow.commitReason).toBe('A transfer cannot go to its own account.');
	});

	it('commits with Ctrl+Enter, from anywhere in the panel', async () => {
		const shown = unit({ anchor_entry_id: 1 });
		const { dialog } = await openPanel(shown);
		vi.mocked(commitUnit).mockResolvedValue(committed(shown));

		await fireEvent.keyDown(dialog, { key: 'Enter', ctrlKey: true });

		await waitFor(() => expect(commitUnit).toHaveBeenCalledTimes(1));
	});

	it('commits with Meta+Enter from inside a field', async () => {
		const shown = unit({ anchor_entry_id: 1 });
		const { dialog } = await openPanel(shown);
		vi.mocked(commitUnit).mockResolvedValue(committed(shown));
		const note = within(dialog).getByLabelText('Note');

		await fireEvent.keyDown(note, { key: 'Enter', metaKey: true });

		await waitFor(() => expect(commitUnit).toHaveBeenCalledTimes(1));
	});

	it('is never committed by Enter alone, in a field or out of it', async () => {
		const { dialog } = await openPanel();
		await fireEvent.keyDown(within(dialog).getByLabelText('Note'), { key: 'Enter' });
		await fireEvent.keyDown(dialog, { key: 'Enter' });
		expect(commitUnit).not.toHaveBeenCalled();
	});

	it('commits from the button, and says what it is doing', async () => {
		const shown = unit({ anchor_entry_id: 1 });
		const { dialog } = await openPanel(shown);
		let release!: () => void;
		vi.mocked(commitUnit).mockImplementation(
			() => new Promise((resolve) => (release = () => resolve(committed(shown))))
		);

		await fireEvent.click(commitButton(dialog));

		expect(await within(dialog).findByRole('button', { name: 'Committing…' })).toBeDisabled();
		release();
	});
});

describe('editing a value', () => {
	it('c opens the category picker; choosing a category previews the draft at once', async () => {
		const { dialog } = await openPanel();

		await fireEvent.keyDown(dialog, { key: 'c' });
		await fireEvent.input(await screen.findByLabelText('Search category'), {
			target: { value: 'din' }
		});
		await fireEvent.click(await screen.findByRole('option', { name: /Dining/ }));

		await waitFor(() =>
			expect(lastRequest().entries).toEqual([{ id: 1, category: { mode: 'fixed', value: 11 } }])
		);
		// what the server said comes back into the field
		await waitFor(() =>
			expect(within(dialog).getByRole('button', { name: 'Category' })).toHaveTextContent('Dining')
		);
	});

	it('names the proposal when the user picks the very value it shows', async () => {
		const { dialog } = await openPanel();

		await fireEvent.keyDown(dialog, { key: 'c' });
		await fireEvent.click(await screen.findByRole('option', { name: /Groceries/ }));

		await waitFor(() =>
			expect(lastRequest().entries![0].category).toEqual({
				mode: 'fixed',
				value: 10,
				shown_basis: { pass: 'history', basis: { agree: 3, of: 4, since: '2026-03-14' } }
			})
		);
	});

	it('y opens the payee picker', async () => {
		const { dialog } = await openPanel();

		await fireEvent.keyDown(dialog, { key: 'y' });

		expect(await screen.findByLabelText('Search payee')).toBeInTheDocument();
	});

	it('leaves the panel keys to a field: typing c in the note types, nothing opens', async () => {
		const { dialog } = await openPanel();
		await fireEvent.keyDown(within(dialog).getByLabelText('Note'), { key: 'c' });
		expect(screen.queryByLabelText('Search category')).toBeNull();
	});

	it('offers Reset to proposal only for a value the user changed; a click restores the stored one', async () => {
		const { panel, dialog } = await openPanel(
			unit({
				anchor_entry_id: 1,
				entries: [
					entry({
						id: 1,
						unit_key: 1,
						category_id: 10,
						payee_id: 20,
						derivation: {
							category: { pass: 'rule', basis: { rule_id: 3 } },
							payee: { pass: 'history', basis: { agree: 1, of: 1 } }
						}
					})
				]
			})
		);
		// nothing was changed: no link, neither on the decided category nor on the proposed payee
		expect(within(dialog).queryByRole('button', { name: 'Reset to proposal' })).toBeNull();

		panel.flow.setField(1, 'category', 11);
		const link = await within(dialog).findByRole('button', { name: 'Reset to proposal' });
		expect(within(dialog).getAllByRole('button', { name: 'Reset to proposal' })).toHaveLength(1);
		await fireEvent.click(link);

		// the stored value is back, as a draft with no edit: no "reresolve" asked of the server
		await waitFor(() => expect(lastRequest().entries).toEqual([]));
		expect(panel.flow.isDirty).toBe(false);
		expect(within(dialog).queryByRole('button', { name: 'Reset to proposal' })).toBeNull();
	});

	it('picking the value that is stored makes no edit', async () => {
		const { panel } = await openPanel(
			unit({
				anchor_entry_id: 1,
				entries: [
					entry({
						id: 1,
						unit_key: 1,
						category_id: 10,
						derivation: { category: { pass: 'rule', basis: { rule_id: 3 } } }
					})
				]
			})
		);

		panel.flow.setField(1, 'category', 10);

		expect(panel.flow.isDirty).toBe(false);
	});

	it('edits the description and the note with a debounced preview', async () => {
		const { dialog } = await openPanel();

		await fireEvent.input(within(dialog).getByLabelText('Note'), { target: { value: 'for May' } });

		await waitFor(() => expect(lastRequest().entries).toEqual([{ id: 1, note: 'for May' }]));
	});

	it('shows each value with its basis, proposals italic', async () => {
		const { dialog } = await openPanel();
		expect(within(dialog).getByText('history: 3 of 4 since Mar 2026')).toHaveAttribute(
			'data-proposal',
			'true'
		);
	});
});

const OFFER = 'Create rule from this transaction';
// the nudge link of the panel; the source strip's icon carries the same name (and its own slot)
const nudge = (root: HTMLElement) =>
	within(root)
		.queryAllByRole('link', { name: OFFER })
		.find((link) => link.dataset.slot !== 'add-rule-from-source') ?? null;
const findNudge = async (root: HTMLElement) => {
	await waitFor(() => expect(nudge(root)).not.toBeNull());
	return nudge(root)!;
};

describe('the offer to create a rule from a change', () => {
	const ruled = (derivation: Record<string, unknown>, over = {}) =>
		unit({
			anchor_entry_id: 1,
			entries: [
				entry({
					id: 1,
					unit_key: 1,
					source_transaction_id: 5,
					source: source(),
					category_id: 10,
					payee_id: 20,
					type: 'flow',
					derivation,
					...over
				})
			]
		});

	it('appears next to a category a rule set once the draft changes it, and opens the entry as the example', async () => {
		const { panel, dialog } = await openPanel(
			ruled({ category: { pass: 'rule', basis: { rule_id: 3 } } })
		);
		expect(nudge(dialog)).toBeNull();

		panel.flow.setField(1, 'category', 11);

		const link = await findNudge(dialog);
		expect(link).toHaveAttribute('href', '/settings/rules/new?from=1');
		expect(link).toHaveAttribute('target', '_blank');
		expect(link).toHaveAttribute('data-field', 'category');
	});

	it('goes when the change is taken back', async () => {
		const { panel, dialog } = await openPanel(
			ruled({ category: { pass: 'rule', basis: { rule_id: 3 } } })
		);
		panel.flow.setField(1, 'category', 11);
		await findNudge(dialog);

		panel.flow.revertField(1, 'category');

		await waitFor(() => expect(nudge(dialog)).toBeNull());
	});

	it('also covers a payee a rule set', async () => {
		const { panel, dialog } = await openPanel(
			ruled({ payee: { pass: 'rule', basis: { rule_id: 3 } } })
		);

		panel.flow.setField(1, 'payee', 21);

		const link = await findNudge(dialog);
		expect(link).toHaveAttribute('data-field', 'payee');
	});

	it('is not offered for a value history, the model or the user set', async () => {
		const { panel, dialog } = await openPanel(
			ruled({
				category: { pass: 'history', basis: { agree: 3, of: 4 } },
				payee: { pass: 'user' }
			})
		);

		panel.flow.setField(1, 'category', 11);
		panel.flow.setField(1, 'payee', 21);

		await waitFor(() =>
			expect(within(dialog).getByRole('button', { name: 'Category' })).toHaveTextContent('Dining')
		);
		expect(nudge(dialog)).toBeNull();
	});

	it('is not offered for a rule’s value left as it is, nor for an entry without a source', async () => {
		const { dialog } = await openPanel(
			ruled({ category: { pass: 'rule', basis: { rule_id: 3 } } })
		);
		expect(nudge(dialog)).toBeNull();
		cleanup();

		const bare = await openPanel(
			ruled({ category: { pass: 'rule', basis: { rule_id: 3 } } }, { source: null })
		);
		bare.panel.flow.setField(1, 'category', 11);
		await waitFor(() =>
			expect(within(bare.dialog).getByRole('button', { name: 'Category' })).toHaveTextContent(
				'Dining'
			)
		);
		expect(nudge(bare.dialog)).toBeNull();
	});
});

describe('the line and the document dropped', () => {
	it('shows the description of the entry’s line next to its label, long text cut with a title', async () => {
		const text = 'Coffee capsules, a very long description of the one line of this order';
		const { dialog } = await openPanel(
			unit({
				anchor_entry_id: 1,
				entries: [
					entry({
						id: 1,
						unit_key: 1,
						source_transaction_id: 5,
						document_id: 7,
						document: { id: 7, provider: 'amazon', merchant_name: 'Amazon', line_count: 1 },
						document_line: { line_no: 1, description: text }
					})
				]
			})
		);

		const label = dialog.querySelector('[data-slot="document-line-no"]')!;
		expect(label).toHaveTextContent('Line 1 of the document');
		const description = dialog.querySelector('[data-slot="document-line-description"]')!;
		expect(description).toHaveTextContent(text);
		expect(description).toHaveAttribute('title', text);
		expect(description).toHaveClass('truncate');
	});

	it('shows no line for an entry that has none', async () => {
		const { dialog } = await openPanel();

		expect(dialog.querySelector('[data-slot="document-line-no"]')).toBeNull();
	});

	it('says the document is dropped in the row of a change that takes it off', async () => {
		const shown = unit({ anchor_entry_id: 1 });
		const row = previewRowOf(shown.entries[0], {
			document: {
				stored_document_id: 7,
				document: null,
				key: null,
				suggestions: [],
				waiting: null,
				decision_required: false,
				split: null
			}
		});
		vi.mocked(getUnit).mockResolvedValue(shown);
		vi.mocked(previewUnit).mockResolvedValue(
			preview(shown, { consequences: [consequence('changed', row)] })
		);
		const panel = new UnitPanel(nav());
		render(UnitPanelView, { props: { panel, lookups } });
		panel.open(1);
		const dialog = await screen.findByRole('dialog');

		const changed = await within(dialog).findByRole('region', { name: 'Changed' });
		expect(within(changed).getByText('The document is dropped.')).toBeInTheDocument();
	});

	it('says nothing of a document in a change that leaves it', async () => {
		const shown = unit({ anchor_entry_id: 1 });
		const row = previewRowOf(shown.entries[0]);
		vi.mocked(getUnit).mockResolvedValue(shown);
		vi.mocked(previewUnit).mockResolvedValue(
			preview(shown, { consequences: [consequence('changed', row)] })
		);
		const panel = new UnitPanel(nav());
		render(UnitPanelView, { props: { panel, lookups } });
		panel.open(1);
		const dialog = await screen.findByRole('dialog');

		await within(dialog).findByRole('region', { name: 'Changed' });
		expect(within(dialog).queryByText('The document is dropped.')).toBeNull();
	});
});

describe('type', () => {
	it('x makes a flow a transfer, and the counter-account is chosen next', async () => {
		const { dialog } = await openPanel();

		await fireEvent.keyDown(dialog, { key: 'x' });

		await waitFor(() =>
			expect(lastRequest().entries![0].type).toEqual({ mode: 'fixed', value: 'transfer' })
		);
		expect(await screen.findByLabelText('Search counter-account')).toBeInTheDocument();
	});

	it('a transfer shows its counter account and its partner leg; x turns it back into a flow', async () => {
		const pair = unit({
			anchor_entry_id: 1,
			entries: [
				entry({
					id: 1,
					unit_key: 1,
					type: 'transfer',
					counter_account_id: 2,
					counterpart_entry_id: 2,
					amount: { amount: -5000, currency: 'EUR' },
					partner: {
						entry_id: 2,
						account_id: 2,
						booked_on: '2026-10-10',
						amount: { amount: 5000, currency: 'EUR' }
					}
				})
			]
		});
		const { dialog } = await openPanel(pair);

		expect(within(dialog).getByRole('button', { name: 'Counter account' })).toHaveTextContent(
			'Savings'
		);
		expect(within(dialog).getByText('Partner leg')).toBeInTheDocument();
		expect(within(dialog).queryByRole('button', { name: 'Category' })).toBeNull();

		await fireEvent.keyDown(dialog, { key: 'x' });
		await waitFor(() =>
			expect(lastRequest().entries![0].type).toEqual({ mode: 'fixed', value: 'flow' })
		);
	});

	it('disables the accounts the currency rule rules out, and the entry’s own, with the reason', async () => {
		const shown = unit({
			anchor_entry_id: 1,
			entries: [
				entry({ id: 1, unit_key: 1, type: 'transfer', counter_account_id: 3, account_id: 1 })
			]
		});
		vi.mocked(getUnit).mockResolvedValue(shown);
		vi.mocked(previewUnit).mockResolvedValue(
			preview(shown, {
				problems: [
					problem('currency_rule', {
						entry_id: 1,
						field: 'counter_account',
						detail: { required: 'USD', actual: 'EUR' }
					})
				]
			})
		);
		const panel = new UnitPanel(nav());
		render(UnitPanelView, { props: { panel, lookups } });
		panel.open(1);
		const dialog = await screen.findByRole('dialog');
		await waitFor(() => expect(panel.flow.previewStatus).toBe('ready'));

		await fireEvent.click(within(dialog).getByRole('button', { name: 'Counter account' }));

		const giro = await screen.findByRole('option', { name: /Giro/ });
		expect(giro).toHaveAttribute('aria-disabled', 'true');
		expect(giro).toHaveTextContent('Own account');
		const savings = screen.getByRole('option', { name: /Savings/ });
		expect(savings).toHaveTextContent('Needs USD');
		expect(screen.getByRole('option', { name: /Dollar cash/ })).not.toHaveAttribute(
			'aria-disabled',
			'true'
		);
	});
});

describe('Add account in the counter-account picker', () => {
	const transfer = unit({
		anchor_entry_id: 1,
		entries: [entry({ id: 1, unit_key: 1, type: 'transfer', counter_account_id: null })]
	});

	async function openPicker(problems: ReturnType<typeof problem>[] = []) {
		vi.mocked(getUnit).mockResolvedValue(transfer);
		vi.mocked(previewUnit).mockImplementation(async (draft: UnitDraftRequest) => ({
			...fakePreview(transfer, draft),
			problems
		}));
		const panel = new UnitPanel(nav());
		render(UnitPanelView, { props: { panel, lookups } });
		panel.open(1);
		const dialog = await screen.findByRole('dialog');
		await waitFor(() => expect(panel.flow.previewStatus).toBe('ready'));
		await fireEvent.click(within(dialog).getByRole('button', { name: 'Counter account' }));
		return dialog;
	}

	it('offers an Add account action instead of a link to another tab', async () => {
		await openPicker();

		expect(await screen.findByRole('button', { name: 'Add account' })).toBeInTheDocument();
		expect(screen.queryByText(/opens in a new tab/)).toBeNull();
	});

	it('opens the dialog with no currency when the preview states none', async () => {
		const open = vi.spyOn(accountDialog, 'openAdd').mockImplementation(() => {});
		await openPicker();

		await fireEvent.click(await screen.findByRole('button', { name: 'Add account' }));

		expect(open).toHaveBeenCalledTimes(1);
		expect(open.mock.calls[0][0]?.currency).toBeUndefined();
		open.mockRestore();
	});

	it('locks the currency the currency rule requires, and chooses the new account', async () => {
		const open = vi.spyOn(accountDialog, 'openAdd').mockImplementation(() => {});
		await openPicker([
			problem('currency_rule', {
				entry_id: 1,
				field: 'counter_account',
				detail: { required: 'USD', actual: 'EUR' }
			})
		]);

		await fireEvent.click(await screen.findByRole('button', { name: 'Add account' }));

		expect(open.mock.calls[0][0]?.currency).toBe('USD');
		open.mock.calls[0][0]?.onadded?.(account({ id: 8, name: 'Cash USD', currency: 'USD' }));
		await waitFor(() =>
			expect(lastRequest().entries![0].counter_account).toEqual({ mode: 'fixed', value: 8 })
		);
		open.mockRestore();
	});
});

describe('splits', () => {
	const shown = () =>
		unit({
			anchor_entry_id: 1,
			entries: [
				entry({
					id: 1,
					unit_key: 1,
					source_transaction_id: 5,
					amount: { amount: -4731, currency: 'EUR' },
					source: source({ counterparty_name: 'Amazon' })
				})
			]
		});

	it('s adds a row and puts focus in its amount; the preview shows the residual', async () => {
		const { dialog } = await openPanel(shown());

		await fireEvent.keyDown(dialog, { key: 's' });

		const amount = await within(dialog).findByLabelText('Amount of the new split');
		await waitFor(() => expect(amount).toHaveFocus());
		// nothing to preview until an amount is typed, and Commit says so
		expect(commitButton(dialog)).toBeDisabled();
		expect(await within(dialog).findByRole('button', { name: 'Commit' })).toBeDisabled();

		await fireEvent.input(amount, { target: { value: '12.00' } });
		await fireEvent.blur(amount);
		await waitFor(() =>
			expect(lastRequest().entries).toEqual([{ id: -1, source_entry_id: 1, amount: -1200 }])
		);
		// the original is the residual: the server's figure, not computed here
		const original = within(dialog).getByRole('region', { name: 'Entry 1' });
		await waitFor(() => expect(original).toHaveTextContent('−35.31'));
		expect(within(original).getByText('Residual')).toBeInTheDocument();
		await waitFor(() => expect(commitButton(dialog)).toBeEnabled());
	});

	it('refuses an amount that is not one, under the field, and blocks Commit', async () => {
		const { dialog } = await openPanel(shown());
		await fireEvent.click(within(dialog).getByRole('button', { name: 'Split entry' }));
		const amount = await within(dialog).findByLabelText('Amount of the new split');

		await fireEvent.input(amount, { target: { value: 'twelve' } });

		expect(await within(dialog).findByText('This is not an amount.')).toBeInTheDocument();
		expect(commitButton(dialog)).toBeDisabled();
	});

	it('shows an invalid residual with its words, and holds the commit back', async () => {
		const base = shown();
		vi.mocked(getUnit).mockResolvedValue(base);
		vi.mocked(previewUnit).mockImplementation(async (draft: UnitDraftRequest) => {
			const out = fakePreview(base, draft);
			if ((draft.entries ?? []).length > 0)
				out.problems = [problem('residual_zero', { entry_id: 1 })];
			return out;
		});
		const panel = new UnitPanel(nav());
		render(UnitPanelView, { props: { panel, lookups } });
		panel.open(1);
		const dialog = await screen.findByRole('dialog', { name: /./ });
		await waitFor(() => expect(panel.flow.previewStatus).toBe('ready'));
		await fireEvent.click(within(dialog).getByRole('button', { name: 'Split entry' }));
		const typed = await within(dialog).findByLabelText('Amount of the new split');
		await fireEvent.input(typed, { target: { value: '47.31' } });
		await fireEvent.blur(typed);

		const problems = await within(dialog).findByRole('list', { name: 'Problems' });
		expect(problems).toHaveTextContent('The split leaves nothing for the original entry.');
		expect(commitButton(dialog)).toBeDisabled();
		expect(panel.flow.commitReason).toMatch(/leaves nothing for the original entry/);
	});

	it('removes a split row', async () => {
		const { dialog } = await openPanel(shown());
		await fireEvent.click(within(dialog).getByRole('button', { name: 'Split entry' }));
		await within(dialog).findByLabelText('Amount of the new split');

		await fireEvent.click(within(dialog).getByRole('button', { name: 'Remove split' }));

		expect(within(dialog).queryByLabelText('Amount of the new split')).toBeNull();
	});

	it('lays a split block out: amount and label on the header line, the field in the label-left row, an icon-only remove in the corner', async () => {
		const { dialog } = await openPanel(shown());
		await fireEvent.click(within(dialog).getByRole('button', { name: 'Split entry' }));
		const row = await within(dialog).findByRole('region', { name: 'New split entry' });
		const typed = within(row).getByLabelText('Amount of the new split');
		await fireEvent.input(typed, { target: { value: '12.00' } });
		await fireEvent.blur(typed);

		await waitFor(() =>
			expect(row.querySelector('[data-slot="split-label"]')).toHaveTextContent('Split')
		);
		// the amount is read-only in the header, and the label stands next to it
		const header = row.querySelector('[data-slot="split-label"]')!.parentElement!;
		expect(header).toHaveTextContent('12.00');
		expect(within(header).queryByLabelText('Amount of the new split')).toBeNull();
		// the amount sits in the same label-left / value-right grid as the other rows
		const amountRow = row.querySelector('[data-slot="amount-field"]')!;
		expect(amountRow.tagName).toBe('DD');
		expect(amountRow.previousElementSibling).toHaveTextContent('Amount');
		expect(amountRow.previousElementSibling?.parentElement).toBe(
			row.querySelector('[data-slot="amount-field"]')!.parentElement
		);
		expect(amountRow.parentElement).toHaveClass('grid-cols-[8rem_1fr]');
		const remove = within(row).getByRole('button', { name: 'Remove split' });
		expect(remove.textContent?.trim()).toBe('');
		expect(remove).toHaveClass('absolute', 'top-2', 'right-2');
		expect(row).toHaveClass('relative');
	});

	it('puts "Split entry" in a full-width dashed row under the last block', async () => {
		const { dialog } = await openPanel(shown());

		const button = within(dialog).getByRole('button', { name: 'Split entry' });

		expect(button).toHaveClass('w-full', 'border-dashed');
		expect(button.previousElementSibling).toBe(
			within(dialog).getByRole('region', { name: 'Entry 1' })
		);
		expect(within(dialog).queryByRole('button', { name: 'Add split' })).toBeNull();
	});

	it('shows a split row as a flow only: no type toggle, a dashed block', async () => {
		const { dialog } = await openPanel(shown());
		await fireEvent.click(within(dialog).getByRole('button', { name: 'Split entry' }));
		const row = await within(dialog).findByRole('region', { name: 'New split entry' });

		expect(within(row).queryByRole('group', { name: 'Type' })).toBeNull();
		expect(within(row).getByRole('button', { name: 'Category' })).toBeInTheDocument();
	});
});

describe('re-resolve', () => {
	it('r re-resolves the whole unit as a draft edit that Reset undoes', async () => {
		const { panel, dialog } = await openPanel();

		await fireEvent.keyDown(dialog, { key: 'r' });

		await waitFor(() => expect(lastRequest().reresolve_all).toBe(true));
		expect(
			await within(dialog).findByText(
				/Re-resolved: type, payee, category and counter account are what resolution proposes now/
			)
		).toBeInTheDocument();
		expect(within(dialog).queryByText(/Cancel undoes it/)).toBeNull();
		await fireEvent.click(within(dialog).getByRole('button', { name: 'Reset' }));
		await waitFor(() => expect(panel.flow.isDirty).toBe(false));
		expect(panel.isOpen).toBe(true);
		expect(within(dialog).queryByText(/Re-resolved:/)).toBeNull();
	});

	it('applies to the changes not yet committed too, and keeps the splits and the texts', async () => {
		const { panel, dialog } = await openPanel(
			unit({
				anchor_entry_id: 1,
				entries: [entry({ id: 1, unit_key: 1, source_transaction_id: 5 })]
			})
		);
		panel.flow.setField(1, 'category', 11);
		panel.flow.setText(1, 'note', 'mine');
		panel.flow.addSplit(1);
		panel.flow.setAmountText(-1, '5.00');
		panel.flow.applyAmountText(-1);
		await waitFor(() => expect(panel.flow.previewStatus).toBe('ready'));

		await fireEvent.keyDown(dialog, { key: 'r' });

		await waitFor(() => expect(lastRequest().reresolve_all).toBe(true));
		expect(lastRequest().entries).toEqual([
			{ id: 1, note: 'mine' },
			{ id: -1, source_entry_id: 1, amount: -500 }
		]);
		expect(panel.flow.draft?.fieldEdit(1, 'category')).toBeUndefined();
	});

	it('Reset discards every change without re-resolving, and the panel stays open', async () => {
		const { panel, dialog } = await openPanel();
		panel.flow.setField(1, 'category', 11);
		panel.flow.setText(1, 'note', 'mine');
		await waitFor(() => expect(panel.flow.isDirty).toBe(true));

		await openMenu(dialog);
		await fireEvent.click(await screen.findByRole('menuitem', { name: 'Reset' }));

		await waitFor(() => expect(panel.flow.isDirty).toBe(false));
		expect(panel.isOpen).toBe(true);
		await waitFor(() => expect(panel.flow.previewStatus).toBe('ready'));
		expect(lastRequest()).toMatchObject({ entries: [], reresolve_all: false });
	});

	it('Reset is disabled while there is nothing to reset', async () => {
		const { panel, dialog } = await openPanel();
		expect(within(dialog).getByRole('button', { name: 'Reset' })).toBeDisabled();

		panel.flow.setField(1, 'category', 11);

		await waitFor(() =>
			expect(within(dialog).getByRole('button', { name: 'Reset' })).toBeEnabled()
		);
	});

	it('is in the ⋯ menu too', async () => {
		const { dialog } = await openPanel();

		await openMenu(dialog);
		await fireEvent.click(await screen.findByRole('menuitem', { name: /Re-resolve/ }));

		await waitFor(() => expect(lastRequest().reresolve_all).toBe(true));
	});
});

describe('keeping a draft', () => {
	it('Esc on a clean panel closes it', async () => {
		const { panel, dialog } = await openPanel();
		await fireEvent.keyDown(dialog, { key: 'Escape' });
		await waitFor(() => expect(panel.isOpen).toBe(false));
	});

	it('Esc on a dirty draft asks in a decision dialog with Cancel focused', async () => {
		const { panel, dialog } = await openPanel();
		await fireEvent.keyDown(dialog, { key: 'r' });
		await waitFor(() => expect(panel.flow.isDirty).toBe(true));

		await fireEvent.keyDown(dialog, { key: 'Escape' });

		const asking = await screen.findByRole('dialog', { name: 'Discard changes?' });
		await waitFor(() =>
			expect(within(asking).getByRole('button', { name: 'Cancel' })).toHaveFocus()
		);
		expect(panel.isOpen).toBe(true);
	});

	it('Enter does not confirm the decision; Cancel keeps editing', async () => {
		const { panel, dialog } = await openPanel();
		await fireEvent.keyDown(dialog, { key: 'r' });
		await fireEvent.keyDown(dialog, { key: 'Escape' });
		const asking = await screen.findByRole('dialog', { name: 'Discard changes?' });

		await fireEvent.keyDown(within(asking).getByRole('button', { name: 'Cancel' }), {
			key: 'Enter'
		});
		expect(panel.isOpen).toBe(true);
		await fireEvent.click(within(asking).getByRole('button', { name: 'Cancel' }));

		await waitFor(() =>
			expect(screen.queryByRole('dialog', { name: 'Discard changes?' })).toBeNull()
		);
		expect(panel.isOpen).toBe(true);
		expect(panel.flow.isDirty).toBe(true);
	});

	it('the close button and the step keys ask too', async () => {
		const off = registerUnitSource({ neighbour: () => 9, patch: () => {} });
		const { panel, dialog } = await openPanel();
		await fireEvent.keyDown(dialog, { key: 'r' });

		await fireEvent.keyDown(dialog, { key: ']' });

		expect(await screen.findByRole('dialog', { name: 'Discard changes?' })).toBeInTheDocument();
		expect(panel.unitId).toBe(1);
		off();
	});
});

/**
 * A click on the dimmed page: the panel ignores outside clicks for a moment after it opened, and
 * Bits only counts a click as outside when its coordinates are (jsdom lays nothing out: the
 * content's box is empty at 0,0, so the click is placed off it).
 */
async function clickOutside() {
	await new Promise((resolve) => setTimeout(resolve, 350));
	for (const type of ['pointerdown', 'pointerup', 'click']) {
		await fireEvent(
			document.body,
			new MouseEvent(type, { bubbles: true, cancelable: true, button: 0, clientX: -5, clientY: -5 })
		);
	}
}

describe('leaving a dirty panel by the dialog’s own ways out', () => {
	async function dirtyPanel() {
		const shown = unit({
			anchor_entry_id: 1,
			entries: [entry({ id: 1, unit_key: 1, source_transaction_id: 5 })]
		});
		const { panel, dialog } = await openPanel(shown);
		panel.flow.reresolve();
		await waitFor(() => expect(panel.flow.isDirty).toBe(true));
		return { panel, dialog };
	}

	async function expectUsable(panel: UnitPanel, dialog: HTMLElement) {
		expect(panel.isOpen).toBe(true);
		expect(dialog.isConnected).toBe(true);
		expect(dialog).toHaveAttribute('data-state', 'open');
		await fireEvent.click(within(dialog).getByRole('button', { name: 'Split entry' }));
		expect(await within(dialog).findByLabelText('Amount of the new split')).toBeInTheDocument();
	}

	it('a click outside asks first; Cancel keeps the panel open and usable; Discard closes it', async () => {
		const { panel, dialog } = await dirtyPanel();

		await clickOutside();

		const asking = await screen.findByRole('dialog', { name: 'Discard changes?' });
		expect(panel.isOpen).toBe(true);
		expect(dialog.isConnected).toBe(true); // under the nested dialog, not closed beneath it
		await fireEvent.click(within(asking).getByRole('button', { name: 'Cancel' }));
		await waitFor(() =>
			expect(screen.queryByRole('dialog', { name: 'Discard changes?' })).toBeNull()
		);
		await expectUsable(panel, dialog);

		await clickOutside();
		const again = await screen.findByRole('dialog', { name: 'Discard changes?' });
		await fireEvent.click(within(again).getByRole('button', { name: 'Discard' }));
		await waitFor(() => expect(panel.isOpen).toBe(false));
		await waitFor(() => expect(dialog.isConnected).toBe(false));
	});

	it('Esc asks first, and after Cancel the panel is still open and usable', async () => {
		const { panel, dialog } = await dirtyPanel();

		await fireEvent.keyDown(dialog, { key: 'Escape' });
		const asking = await screen.findByRole('dialog', { name: 'Discard changes?' });
		await fireEvent.click(within(asking).getByRole('button', { name: 'Cancel' }));
		await waitFor(() =>
			expect(screen.queryByRole('dialog', { name: 'Discard changes?' })).toBeNull()
		);

		await expectUsable(panel, dialog);
	});

	it('the close button asks first, and after Cancel the panel is still open and usable', async () => {
		const { panel, dialog } = await dirtyPanel();

		await fireEvent.click(within(dialog).getByRole('button', { name: 'Close' }));
		const asking = await screen.findByRole('dialog', { name: 'Discard changes?' });
		await fireEvent.click(within(asking).getByRole('button', { name: 'Cancel' }));
		await waitFor(() =>
			expect(screen.queryByRole('dialog', { name: 'Discard changes?' })).toBeNull()
		);

		await expectUsable(panel, dialog);
	});

	it('a clean panel closes at once by a click outside', async () => {
		const { panel } = await openPanel();

		await clickOutside();

		await waitFor(() => expect(panel.isOpen).toBe(false));
	});
});

describe('taking a choice back (the X) and the empty payee', () => {
	const oneOf = (over: Parameters<typeof entry>[0]) =>
		unit({ anchor_entry_id: 1, entries: [entry({ id: 1, unit_key: 1, ...over })] });
	const removeChoice = (dialog: HTMLElement) =>
		within(dialog).queryByRole('button', { name: 'Remove my choice of category' });
	const clearPayee = (dialog: HTMLElement) =>
		within(dialog).queryByRole('button', { name: 'Clear payee' });

	it('shows the X on a value the user decided, not on one a rule or a proposal decided', async () => {
		const { dialog } = await openPanel(); // category by history, payee by a rule
		expect(removeChoice(dialog)).toBeNull();
		expect(clearPayee(dialog)).not.toBeNull(); // the payee's X: any value, it makes the payee empty
		cleanup();

		const ruled = await openPanel(
			oneOf({ category_id: 10, derivation: { category: { pass: 'rule', basis: { rule_id: 3 } } } })
		);
		expect(removeChoice(ruled.dialog)).toBeNull();
		cleanup();

		const own = await openPanel(
			oneOf({ category_id: 10, derivation: { category: { pass: 'user' } } })
		);
		expect(removeChoice(own.dialog)).not.toBeNull();
	});

	it('a removed category choice is proposed again, and Reset to proposal brings the stored one back', async () => {
		const { panel, dialog } = await openPanel(
			oneOf({ category_id: 10, derivation: { category: { pass: 'user' } } })
		);
		expect(within(dialog).queryByRole('button', { name: 'Reset to proposal' })).toBeNull();

		await fireEvent.click(removeChoice(dialog)!);

		await waitFor(() =>
			expect(lastRequest().entries).toEqual([{ id: 1, category: { mode: 'reresolve' } }])
		);
		await waitFor(() =>
			expect(within(dialog).getByRole('button', { name: 'Category' })).toHaveTextContent('Dining')
		);
		await fireEvent.click(await within(dialog).findByRole('button', { name: 'Reset to proposal' }));

		await waitFor(() => expect(lastRequest().entries).toEqual([]));
		expect(panel.flow.draft?.fieldEdit(1, 'category')).toBeUndefined();
		await waitFor(() =>
			expect(within(dialog).getByRole('button', { name: 'Category' })).toHaveTextContent(
				'Groceries'
			)
		);
		expect(within(dialog).queryByRole('button', { name: 'Reset to proposal' })).toBeNull();
	});

	it('an X that ends in the stored value leaves no Reset link and no change to discard', async () => {
		const shown = oneOf({
			category_id: 10,
			derivation: { category: { pass: 'rule', basis: { rule_id: 3 } } }
		});
		const { panel, dialog } = await openPanel(shown);
		// the rule decides 10 again once the user's pick is taken back
		vi.mocked(previewUnit).mockImplementation(async (draft: UnitDraftRequest) =>
			draft.entries?.[0]?.category?.mode === 'reresolve'
				? preview(shown)
				: fakePreview(shown, draft)
		);
		panel.flow.setField(1, 'category', 11);
		await waitFor(() => expect(removeChoice(dialog)).not.toBeNull()); // the pick is the user's

		await fireEvent.click(removeChoice(dialog)!);

		await waitFor(() => expect(panel.flow.stale).toBe(false));
		await waitFor(() =>
			expect(within(dialog).getByRole('button', { name: 'Category' })).toHaveTextContent(
				'Groceries'
			)
		);
		expect(within(dialog).queryByRole('button', { name: 'Reset to proposal' })).toBeNull();
		expect(panel.flow.isDirty).toBe(false);
		expect(within(dialog).getByRole('button', { name: 'Reset' })).toBeDisabled();
		panel.close();
		expect(panel.leave).toBeNull(); // nothing to discard: no question
	});

	it('the payee X makes it empty, a proposal included: shown muted, set by you, standing', async () => {
		const proposed = oneOf({
			payee_id: 20,
			derivation: { payee: { pass: 'history', basis: { agree: 1, of: 1 } } }
		});
		const { dialog } = await openPanel(proposed);
		expect(clearPayee(dialog)).not.toBeNull(); // a proposal can be cleared too

		await fireEvent.click(clearPayee(dialog)!);

		await waitFor(() =>
			expect(lastRequest().entries).toEqual([{ id: 1, payee: { mode: 'fixed', value: null } }])
		);
		const field = within(dialog).getByRole('button', { name: 'Payee' });
		await waitFor(() => expect(field).toHaveTextContent('No payee'));
		expect(field.className).toMatch(/text-muted-foreground/);
		expect(within(dialog).getByText('set by you')).toBeInTheDocument();
		expect(clearPayee(dialog)).toBeNull(); // nothing left to remove
		expect(within(dialog).getByRole('button', { name: 'Reset to proposal' })).toBeInTheDocument();
	});

	it('an empty payee reads "No payee", muted, decided or not; only a decided one is set by you', async () => {
		const open = await openPanel(oneOf({ payee_id: null }));
		const openField = within(open.dialog).getByRole('button', { name: 'Payee' });
		expect(openField).toHaveTextContent('No payee');
		expect(openField).not.toHaveTextContent('Choose a payee');
		expect(openField.className).toMatch(/text-muted-foreground/);
		expect(within(open.dialog).queryByText('set by you')).toBeNull();
		cleanup();

		const decided = await openPanel(
			oneOf({ payee_id: null, derivation: { payee: { pass: 'user' } } })
		);
		expect(within(decided.dialog).getByRole('button', { name: 'Payee' })).toHaveTextContent(
			'No payee'
		);
		expect(within(decided.dialog).getByText('set by you')).toBeInTheDocument();
	});

	it('a field that may not be empty keeps its prompt', async () => {
		const { dialog } = await openPanel(oneOf({ category_id: null }));
		expect(within(dialog).getByRole('button', { name: 'Category' })).toHaveTextContent(
			'Choose a category…'
		);
	});

	it('the payee list has no "No payee" item: the X empties it', async () => {
		const { dialog } = await openPanel();

		await fireEvent.keyDown(dialog, { key: 'y' });
		const options = await screen.findAllByRole('option');
		expect(options.map((o) => o.textContent)).not.toContain('No payee');
		expect(options).toHaveLength(2); // the two payees, nothing else
	});

	it('a payee picked from the list replaces a payee decided empty', async () => {
		const { dialog } = await openPanel(
			oneOf({ payee_id: null, derivation: { payee: { pass: 'user' } } })
		);

		await fireEvent.keyDown(dialog, { key: 'y' });
		const options = await screen.findAllByRole('option');
		expect(options[0]).toHaveAttribute('data-checked', 'false'); // nothing is selected
		await fireEvent.click(screen.getByRole('option', { name: /Aldi/ }));

		await waitFor(() =>
			expect(lastRequest().entries).toEqual([{ id: 1, payee: { mode: 'fixed', value: 21 } }])
		);
	});

	it('the undecided payee list marks nothing as selected', async () => {
		const { dialog } = await openPanel(oneOf({ payee_id: null }));
		await fireEvent.keyDown(dialog, { key: 'y' });
		const options = await screen.findAllByRole('option');
		expect(options[0]).toHaveAttribute('data-checked', 'false');
	});
});

describe('type buttons', () => {
	it('mark the chosen type as the filled segment of one control', async () => {
		const { dialog } = await openPanel();
		const flowButton = within(dialog).getByRole('button', { name: 'Flow' });
		const transfer = within(dialog).getByRole('button', { name: 'Transfer' });

		expect(flowButton).toHaveAttribute('aria-pressed', 'true');
		expect(transfer).toHaveAttribute('aria-pressed', 'false');
		expect(flowButton).toHaveClass('bg-accent');
		expect(transfer).not.toHaveClass('bg-accent');
		expect(within(dialog).getByRole('group', { name: 'Type' })).toHaveAttribute(
			'data-slot',
			'segmented'
		);
	});

	it('Flow on an entry with no type yet makes a flow, Transfer a transfer', async () => {
		const open = unit({
			anchor_entry_id: 1,
			entries: [entry({ id: 1, unit_key: 1, type: null })]
		});
		const { dialog } = await openPanel(open);

		await fireEvent.click(within(dialog).getByRole('button', { name: 'Flow' }));
		await waitFor(() =>
			expect(lastRequest().entries![0].type).toEqual({ mode: 'fixed', value: 'flow' })
		);
		await fireEvent.click(within(dialog).getByRole('button', { name: 'Transfer' }));
		await waitFor(() =>
			expect(lastRequest().entries![0].type).toEqual({ mode: 'fixed', value: 'transfer' })
		);
	});
});

describe('notices', () => {
	it('shows a conflict in the panel with Reload, and keeps the draft', async () => {
		const shown = unit({ anchor_entry_id: 1 });
		const { panel, dialog } = await openPanel(shown);
		await fireEvent.keyDown(dialog, { key: 'r' });
		await waitFor(() => expect(panel.flow.previewStatus).toBe('ready'));
		vi.mocked(commitUnit).mockRejectedValueOnce(apiError(409, 'conflict'));

		await fireEvent.keyDown(dialog, { key: 'Enter', ctrlKey: true });

		const notice = await within(dialog).findByText(/Someone changed this unit/);
		expect(notice).toBeInTheDocument();
		expect(within(dialog).getByRole('button', { name: 'Reload' })).toBeInTheDocument();
		expect(panel.flow.isDirty).toBe(true);
	});

	it('offers Try again for a commit that was interrupted', async () => {
		const shown = unit({ anchor_entry_id: 1 });
		const { dialog } = await openPanel(shown);
		vi.mocked(commitUnit).mockRejectedValueOnce(apiError(409, 'try_again'));

		await fireEvent.click(commitButton(dialog));

		expect(await within(dialog).findByRole('button', { name: 'Try again' })).toBeInTheDocument();
	});
});

describe('Edit entry and Delete entry', () => {
	const authoredUnit = () =>
		unit({ anchor_entry_id: 1, entries: [entry({ id: 1, unit_key: 1, authored: true })] });

	it('hands the entry to the host when the draft is clean', async () => {
		const onEditEntry = vi.fn();
		const onDeleteEntry = vi.fn();
		const { dialog } = await openPanel(authoredUnit(), { onEditEntry, onDeleteEntry });

		await openMenu(dialog);
		await fireEvent.click(await screen.findByRole('menuitem', { name: 'Edit entry' }));

		expect(onEditEntry).toHaveBeenCalledWith(1);
		expect(onDeleteEntry).not.toHaveBeenCalled();
	});

	it('is disabled while the draft has changes, with the reason', async () => {
		const onEditEntry = vi.fn();
		const onDeleteEntry = vi.fn();
		const { panel, dialog } = await openPanel(authoredUnit(), { onEditEntry, onDeleteEntry });
		await fireEvent.keyDown(dialog, { key: 'r' });
		await waitFor(() => expect(panel.flow.isDirty).toBe(true));

		await openMenu(dialog);

		const edit = await screen.findByRole('menuitem', { name: /Edit entry/ });
		expect(edit).toHaveAttribute('aria-disabled', 'true');
		expect(edit).toHaveTextContent('Commit or discard your changes first');
		expect(screen.getByRole('menuitem', { name: /Delete entry…/ })).toHaveAttribute(
			'aria-disabled',
			'true'
		);
	});

	it('offers neither for an imported entry', async () => {
		const { dialog } = await openPanel(unit({ anchor_entry_id: 1 }), {
			onEditEntry: vi.fn(),
			onDeleteEntry: vi.fn()
		});

		await openMenu(dialog);

		await screen.findByRole('menuitem', { name: /Re-resolve/ });
		expect(screen.queryByRole('menuitem', { name: 'Edit entry' })).toBeNull();
	});
});

describe('tags', () => {
	const tagged = () =>
		unit({ anchor_entry_id: 1, entries: [entry({ id: 1, unit_key: 1, tag_ids: [30] })] });
	const tagsButton = (dialog: HTMLElement) =>
		within(dialog).getByRole('button', { name: 'Add or remove tags' });

	it('shows the chips of the entry and a picker to change them; nothing is proposed', async () => {
		const { dialog } = await openPanel(tagged());

		const field = dialog.querySelector<HTMLElement>('[data-slot="tag-field"]')!;
		expect(within(field).getByText('Lisbon trip')).toBeInTheDocument();
		expect(within(dialog).queryByText(/Saved immediately/)).toBeNull();
		// the chip's remove X and the trigger are the row's only controls
		expect(within(field).getAllByRole('button')).toHaveLength(2);
		expect(within(dialog).getByText('Tags', { selector: 'dt' })).toBeInTheDocument();
	});

	it('each chip has a remove X: in the DOM, hidden by opacity at rest, shown on hover and focus', async () => {
		const { dialog } = await openPanel(tagged());

		const remove = within(dialog).getByRole('button', { name: 'Remove tag Lisbon trip' });
		expect(remove).toHaveAttribute('title', 'Remove tag Lisbon trip');
		expect(remove).toHaveClass('opacity-0');
		expect(remove).toHaveClass('group-hover:opacity-100');
		expect(remove).toHaveClass('group-focus-within:opacity-100');
		expect(remove).toHaveClass('[@media(hover:none)]:opacity-100');
		expect(remove).not.toHaveClass('hidden');
		expect(tagsButton(dialog)).toHaveAttribute('title', 'Add or remove tags');
	});

	it('clicking the X takes the tag off the entry and makes the draft dirty; no confirmation', async () => {
		const { dialog } = await openPanel(tagged());
		expect(within(dialog).getByRole('button', { name: 'Reset' })).toBeDisabled();

		await fireEvent.click(within(dialog).getByRole('button', { name: 'Remove tag Lisbon trip' }));

		await waitFor(() =>
			expect(lastRequest().entries).toEqual([{ id: 1, tags: { add: [], remove: [30] } }])
		);
		await waitFor(() => expect(within(dialog).queryByText('Lisbon trip')).toBeNull());
		expect(within(dialog).getByRole('button', { name: 'Reset' })).toBeEnabled();
		expect(screen.queryByRole('alertdialog')).toBeNull();
		// the panel is still there, and the focus stayed inside it
		expect(dialog.contains(document.activeElement)).toBe(true);
	});

	it.each(['Backspace', 'Delete'])(
		'%s on the focused X removes the tag and nothing else',
		async (key) => {
			const { dialog } = await openPanel(tagged());
			const remove = within(dialog).getByRole('button', { name: 'Remove tag Lisbon trip' });
			remove.focus();

			const notDefault = fireEvent.keyDown(remove, { key });

			expect(await notDefault).toBe(false); // preventDefault was called
			await waitFor(() =>
				expect(lastRequest().entries).toEqual([{ id: 1, tags: { add: [], remove: [30] } }])
			);
			await waitFor(() => expect(within(dialog).queryByText('Lisbon trip')).toBeNull());
			expect(screen.queryByLabelText('Search tags')).toBeNull();
		}
	);

	it('shows "Add tag" for an entry without tags', async () => {
		const { dialog } = await openPanel(
			unit({ anchor_entry_id: 1, entries: [entry({ id: 1, unit_key: 1 })] })
		);
		expect(tagsButton(dialog)).toHaveTextContent('Add tag');
	});

	it('choosing puts a tag on and takes one off; the picker stays open; the change is relative', async () => {
		const { dialog } = await openPanel(tagged());

		await fireEvent.click(tagsButton(dialog));
		await fireEvent.click(await screen.findByRole('option', { name: /Holiday/ }));

		await waitFor(() =>
			expect(lastRequest().entries).toEqual([{ id: 1, tags: { add: [31], remove: [] } }])
		);
		await waitFor(() => expect(within(dialog).getByText('Holiday')).toBeInTheDocument());
		expect(screen.getByLabelText('Search tags')).toBeInTheDocument(); // still open
		expect(screen.getByRole('option', { name: /Holiday/ })).toHaveAttribute('data-checked', 'true');

		await fireEvent.click(screen.getByRole('option', { name: /Lisbon trip/ }));
		await waitFor(() =>
			expect(lastRequest().entries).toEqual([{ id: 1, tags: { add: [31], remove: [30] } }])
		);
		await waitFor(() => expect(within(dialog).queryByText('Lisbon trip')).toBeNull());
	});

	it('t opens the tags of the focused entry; a field keeps its t', async () => {
		const { dialog } = await openPanel(tagged());

		await fireEvent.keyDown(within(dialog).getByLabelText('Note'), { key: 't' });
		expect(screen.queryByLabelText('Search tags')).toBeNull();

		await fireEvent.keyDown(dialog, { key: 't' });
		expect(await screen.findByLabelText('Search tags')).toBeInTheDocument();
	});

	it('lists t in the panel’s keyboard help', async () => {
		const { dialog } = await openPanel(tagged());
		await fireEvent.click(within(dialog).getByRole('button', { name: /Keyboard shortcuts/ }));
		const help = within(dialog).getByRole('region', { name: 'Keyboard shortcuts' });
		expect(help).toHaveTextContent('Tags');
	});

	it('a tag change alone is a change: Reset and Commit are enabled, and it commits', async () => {
		const shown = tagged();
		const { dialog } = await openPanel(shown);
		expect(within(dialog).getByRole('button', { name: 'Reset' })).toBeDisabled();

		await fireEvent.click(tagsButton(dialog));
		await fireEvent.click(await screen.findByRole('option', { name: /Holiday/ }));
		await waitFor(() => expect(lastRequest().entries).toHaveLength(1));
		await waitFor(() => expect(commitButton(dialog)).toBeEnabled());
		expect(within(dialog).getByRole('button', { name: 'Reset' })).toBeEnabled();
		vi.mocked(commitUnit).mockResolvedValue(committed(shown));

		await fireEvent.keyDown(dialog, { key: 'Enter', ctrlKey: true });

		await waitFor(() => expect(commitUnit).toHaveBeenCalled());
		expect(vi.mocked(commitUnit).mock.calls[0][0].entries).toEqual([
			{ id: 1, tags: { add: [31], remove: [] } }
		]);
	});

	it('Reset drops the tag changes', async () => {
		const { dialog } = await openPanel(tagged());
		await fireEvent.click(tagsButton(dialog));
		await fireEvent.click(await screen.findByRole('option', { name: /Holiday/ }));
		await waitFor(() => expect(within(dialog).getByText('Holiday')).toBeInTheDocument());

		await fireEvent.click(within(dialog).getByRole('button', { name: 'Reset' }));

		await waitFor(() => expect(within(dialog).queryByText('Holiday')).toBeNull());
		expect(within(dialog).getByText('Lisbon trip')).toBeInTheDocument();
		await waitFor(() => expect(lastRequest().entries).toEqual([]));
	});

	it('a new split row starts with the original’s tags and changes them on its own', async () => {
		const { panel, dialog } = await openPanel(tagged());

		await fireEvent.keyDown(dialog, { key: 's' });
		let block = await within(dialog).findByRole('region', { name: 'New split entry' });
		expect(within(block).getByText('Lisbon trip')).toBeInTheDocument();
		const typed = within(block).getByLabelText('Amount of the new split');
		await fireEvent.input(typed, { target: { value: '5' } });
		await fireEvent.blur(typed);
		// the amount is previewed when the field is left; the row is the preview's after that
		await waitFor(() => expect(panel.flow.stale).toBe(false));
		block = within(dialog).getByRole('region', { name: 'New split entry' });
		await fireEvent.click(within(block).getByRole('button', { name: 'Add or remove tags' }));
		await fireEvent.click(await screen.findByRole('option', { name: /Lisbon trip/ }));

		await waitFor(() => {
			const split = lastRequest().entries!.find((e) => e.id < 0);
			expect(split?.tags).toEqual({ add: [], remove: [30] });
		});
		await waitFor(() => expect(within(block).queryByText('Lisbon trip')).toBeNull());
		// the original keeps its tag
		const original = within(dialog).getByRole('region', { name: 'Entry 1' });
		expect(within(original).getByText('Lisbon trip')).toBeInTheDocument();
	});

	describe('adding a tag that does not exist', () => {
		afterEach(() => lookupsStore.reset());

		it('offers Add tag only for a new name, creates it at once and puts it on the entry', async () => {
			const { dialog } = await openPanel(tagged());
			vi.mocked(createTag).mockResolvedValue({ tag: tag({ id: 77, name: 'Trip' }) } as never);
			await fireEvent.click(tagsButton(dialog));
			const search = await screen.findByLabelText('Search tags');

			await fireEvent.input(search, { target: { value: 'holiday' } });
			expect(screen.queryByRole('option', { name: /Add tag/ })).toBeNull(); // taken: choose it

			await fireEvent.input(search, { target: { value: 'Trip' } });
			await fireEvent.click(await screen.findByRole('option', { name: 'Add tag “Trip”' }));

			await waitFor(() => expect(createTag).toHaveBeenCalledWith('Trip'));
			expect(lookupsStore.lookups.tags.get(77)?.name).toBe('Trip');
			await waitFor(() =>
				expect(lastRequest().entries).toEqual([{ id: 1, tags: { add: [77], remove: [] } }])
			);
		});

		it('leaves the tag in place when the draft is reset', async () => {
			const { panel, dialog } = await openPanel(tagged());
			vi.mocked(createTag).mockResolvedValue({ tag: tag({ id: 77, name: 'Trip' }) } as never);
			await fireEvent.click(tagsButton(dialog));
			await fireEvent.input(await screen.findByLabelText('Search tags'), {
				target: { value: 'Trip' }
			});
			await fireEvent.click(await screen.findByRole('option', { name: 'Add tag “Trip”' }));
			await waitFor(() => expect(panel.flow.draft?.tagEdit(1)).toBeDefined());

			panel.flow.discard();

			expect(panel.flow.draft?.tagEdit(1)).toBeUndefined();
			expect(lookupsStore.lookups.tags.get(77)).toBeDefined();
		});

		it('says so when the tag could not be created, and changes nothing', async () => {
			const { dialog } = await openPanel(tagged());
			vi.mocked(createTag).mockRejectedValue(apiError(500, 'internal_error'));
			await fireEvent.click(tagsButton(dialog));
			await fireEvent.input(await screen.findByLabelText('Search tags'), {
				target: { value: 'Trip' }
			});
			await fireEvent.click(await screen.findByRole('option', { name: 'Add tag “Trip”' }));

			expect(await within(dialog).findByText(/could not do this/)).toBeInTheDocument();
			expect(lastRequest().entries).toEqual([]);
		});
	});
});
