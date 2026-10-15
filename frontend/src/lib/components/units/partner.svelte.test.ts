import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { account, entry } from '#lib/ledger/fixtures.js';
import { buildLookups } from '#lib/ledger/lookups.js';
import { accounts as accountDialog } from '#lib/accounts/controller.svelte.js';
import { ruleNames } from '#lib/stores/rule-names.svelte.js';
import type { UnitDraftRequest, UnitPreview, UnitTransfer } from '#lib/units/types.js';
import {
	offerOut,
	preview,
	previewRowOf,
	problem,
	transferOut,
	unit
} from '#lib/units/fixtures.js';
import { UnitPanel, type PanelNav } from '#lib/units/panel.svelte.js';
import UnitPanelView from './unit-panel.svelte';

// components never import the API, not even in tests: the mocks come from here
const api = vi.hoisted(() => ({
	getUnit: vi.fn(),
	listRules: vi.fn(),
	previewUnit: vi.fn(),
	commitUnit: vi.fn()
}));
vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	...api
}));
const { getUnit, listRules, previewUnit } = api;

const lookups = buildLookups({
	accounts: [
		account({ id: 1, name: 'Giro' }),
		account({ id: 2, name: 'Savings' }),
		account({ id: 3, name: 'Dollar cash', currency: 'USD', synced: false }),
		account({ id: 4, name: 'Card' })
	],
	categories: [],
	payees: [],
	tags: []
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

const OUT = { amount: -5000, currency: 'EUR' };
const leg = (over = {}) =>
	entry({
		id: 1,
		unit_key: 1,
		type: 'transfer',
		account_id: 1,
		counter_account_id: 2,
		amount: OUT,
		source_transaction_id: 5,
		review_flags: ['unconfirmed'],
		derivation: {},
		...over
	});

const partnerRow = () =>
	previewRowOf(
		entry({
			id: 2,
			unit_key: 1,
			type: 'transfer',
			account_id: 2,
			counter_account_id: 1,
			amount: { amount: 5000, currency: 'EUR' },
			booked_on: '2026-10-10',
			source_transaction_id: 6,
			derivation: {}
		}),
		{ original: true, in_unit: true, transfer: transferOut({ state: 'paired' }) }
	);

type Options = {
	entryOver?: Record<string, unknown>;
	/** what the preview says of the anchor's leg */
	transfer: UnitTransfer | ((request: UnitDraftRequest) => UnitTransfer);
	/** more of the preview, per request */
	extra?: (request: UnitDraftRequest, out: UnitPreview) => void;
};

async function openTransfer({ entryOver, transfer, extra }: Options) {
	const shown = unit({ anchor_entry_id: 1, entries: [leg(entryOver)] });
	vi.mocked(getUnit).mockResolvedValue(shown);
	vi.mocked(previewUnit).mockImplementation(async (request: UnitDraftRequest) => {
		const out = preview(shown);
		out.rows[0].transfer = typeof transfer === 'function' ? transfer(request) : transfer;
		extra?.(request, out);
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
const partnerOf = (dialog: HTMLElement) =>
	dialog.querySelector<HTMLElement>('[data-slot="partner"]')!;
const trigger = (dialog: HTMLElement, name = 'Choose partner…') =>
	within(dialog).getByRole('button', { name });

async function openList(dialog: HTMLElement, name?: string) {
	await fireEvent.click(trigger(dialog, name));
	return screen.findByRole('listbox', { name: 'Partner candidates' });
}

beforeEach(() => {
	vi.resetAllMocks();
	ruleNames.reset();
	vi.mocked(listRules).mockResolvedValue([]);
});
afterEach(() => cleanup());

describe('the partner row of a transfer leg', () => {
	it('shows a pair’s partner with how the pair was made, and offers another', async () => {
		const { dialog } = await openTransfer({
			entryOver: { derivation: { counterpart: { pass: 'matcher_decision', basis: {} } } },
			transfer: transferOut({
				state: 'paired',
				partner: {
					entry_id: 2,
					account_id: 2,
					booked_on: '2026-10-10',
					amount: { amount: 5000, currency: 'EUR' },
					description: 'Transfer in'
				}
			})
		});

		const row = partnerOf(dialog);
		expect(row).toHaveTextContent('Paired with Savings');
		expect(row).toHaveTextContent('Oct 10, 2026');
		expect(row).toHaveTextContent('50.00');
		expect(row).toHaveTextContent('matched automatically'); // the evidence line
		expect(row.querySelector('[data-proposal]')).toBeNull();
		expect(trigger(dialog, 'Pick another partner…')).toBeInTheDocument();
	});

	it('shows the proposed offer of an unpaired leg as a proposal, italic, with its evidence', async () => {
		const { dialog } = await openTransfer({
			transfer: transferOut({
				state: 'unmatched',
				offers: [offerOut({ entry_id: 2, proposed: true })],
				proposal: { kind: 'entry', entry_id: 2 },
				proposed_pick: { entry_id: 2 }
			})
		});

		const row = partnerOf(dialog);
		expect(row.querySelector('[data-slot="partner-leg"]')).toHaveAttribute('data-proposal');
		expect(row.querySelector('[data-slot="partner-leg"]')!.className).toContain('italic');
		expect(row).toHaveTextContent('Savings');
		expect(row).not.toHaveTextContent('Paired with');
		expect(row).toHaveTextContent('proposed: exact match');
		expect(trigger(dialog)).toBeInTheDocument();
	});

	it.each([
		[
			'waiting',
			{ state: 'waiting', waiting_for: { account_id: 2, synced_through: '2026-10-05' } },
			2,
			'Waiting for Savings. Its import has not reached the matching window yet (synced through Oct 5, 2026).'
		],
		[
			'unmatched with a synced counter-account',
			{ state: 'unmatched' },
			4,
			'The partner is missing from Card’s import. Import what is missing, or convert this to a flow if it is not a transfer.'
		],
		[
			'unmatched with no counter-account',
			{ state: 'unmatched' },
			null,
			'Choose where the money went.'
		]
	] as const)('says why a leg has no partner: %s', async (_name, state, counter, sentence) => {
		const { dialog } = await openTransfer({
			entryOver: { counter_account_id: counter },
			transfer: transferOut(state as Partial<UnitTransfer>)
		});

		expect(partnerOf(dialog)).toHaveTextContent('No partner yet');
		expect(partnerOf(dialog).querySelector('[data-slot="partner-state"]')).toHaveTextContent(
			sentence
		);
	});

	it('says the other side is created, for an unsynced counter-account', async () => {
		const { dialog } = await openTransfer({
			entryOver: { counter_account_id: 3 },
			transfer: transferOut({ state: 'unmatched' })
		});

		expect(partnerOf(dialog)).toHaveTextContent('No partner yet');
		expect(partnerOf(dialog).querySelector('[data-slot="partner-state"]')).toHaveTextContent(
			'No partner. Create the other side on Dollar cash.'
		);
	});

	it('says an account is needed and opens Add account locked to the currency', async () => {
		const open = vi.spyOn(accountDialog, 'openAdd').mockImplementation(() => {});
		const { dialog } = await openTransfer({
			entryOver: { counter_account_id: null },
			transfer: transferOut({ state: 'needs_account', needs_account: { currency: 'USD' } })
		});

		expect(partnerOf(dialog)).toHaveTextContent('Needs an account in USD');
		expect(within(dialog).queryByRole('button', { name: 'Choose partner…' })).toBeNull();
		await fireEvent.click(within(dialog).getByRole('button', { name: 'Add account' }));

		expect(open.mock.calls[0][0]?.currency).toBe('USD');
		open.mock.calls[0][0]?.onadded?.(account({ id: 8, name: 'Cash USD', currency: 'USD' }));
		await waitFor(() =>
			expect(lastRequest().entries![0].counter_account).toEqual({ mode: 'fixed', value: 8 })
		);
		open.mockRestore();
	});

	it('keeps the stored partner row where the preview has said nothing of the leg', async () => {
		const shown = unit({
			anchor_entry_id: 1,
			entries: [
				leg({
					partner: {
						entry_id: 2,
						account_id: 2,
						booked_on: '2026-10-10',
						amount: { amount: 5000, currency: 'EUR' }
					}
				})
			]
		});
		vi.mocked(getUnit).mockResolvedValue(shown);
		vi.mocked(previewUnit).mockResolvedValue(preview(shown));
		const panel = new UnitPanel(nav());
		render(UnitPanelView, { props: { panel, lookups } });
		panel.open(1);
		const dialog = await screen.findByRole('dialog');
		await waitFor(() => expect(panel.flow.previewStatus).toBe('ready'));

		expect(within(dialog).getByText('Partner leg')).toBeInTheDocument();
		expect(within(dialog).queryByRole('button', { name: /partner…/ })).toBeNull();
	});
});

describe('the partner popover', () => {
	const fee = {
		types_as_transfer: false,
		fee: { difference: { amount: 250, currency: 'EUR' }, larger_entry_id: 3 },
		breaks_pair_with: []
	};
	const offers = [
		// the server's order is shown as it is: an inexact open offer ahead of an exact one
		offerOut({
			entry_id: 3,
			account_id: 4,
			booked_on: '2026-10-12',
			amount: { amount: 5250, currency: 'EUR' },
			description: 'Card payoff',
			exact: false,
			effect: fee
		}),
		offerOut({
			entry_id: 2,
			account_id: 2,
			description: 'Transfer in',
			proposed: true,
			exact: true
		}),
		offerOut({
			entry_id: 5,
			kind: 'untyped_entry',
			account_id: 2,
			description: 'Unknown deposit',
			effect: { types_as_transfer: true, fee: null, breaks_pair_with: [] }
		}),
		offerOut({
			entry_id: 6,
			kind: 'paired_elsewhere',
			account_id: 2,
			description: 'Already taken',
			paired_with: {
				entry_id: 9,
				account_id: 4,
				booked_on: '2026-10-08',
				amount: { amount: -5000, currency: 'EUR' },
				description: null
			},
			effect: { types_as_transfer: false, fee: null, breaks_pair_with: [9] }
		}),
		offerOut({ kind: 'counter_leg', entry_id: null, account_id: 3, description: null })
	];
	const transfer = () => transferOut({ state: 'unmatched', offers });

	it('lists the offers in the server’s order and groups, with their marks and one-line hints', async () => {
		const { dialog } = await openTransfer({ transfer: transfer() });

		const list = await openList(dialog);

		const headings = [...list.querySelectorAll('[data-slot="command-group"]')].map((g) =>
			g.getAttribute('data-group')
		);
		expect(headings).toEqual(['open', 'paired_elsewhere', 'new']);
		expect(within(list).getByText('Open')).toBeInTheDocument();
		expect(within(list).getByText('Paired elsewhere')).toBeInTheDocument();
		const rows = within(list).getAllByRole('option');
		expect(rows.map((r) => r.getAttribute('data-offer'))).toEqual([
			'3',
			'2',
			'5',
			'6',
			'counter-leg'
		]);

		// inexact: no tag, a fee hint
		expect(rows[0]).toHaveTextContent('Card');
		expect(rows[0]).toHaveTextContent('Oct 12, 2026');
		expect(rows[0]).toHaveTextContent('52.50');
		expect(rows[0]).toHaveTextContent('Card payoff');
		expect(rows[0].querySelector('[data-tag="exact"]')).toBeNull();
		expect(rows[0]).toHaveTextContent('differs by 2.50: the difference becomes a separate flow');
		// exact and proposed
		expect(rows[1].querySelector('[data-tag="exact"]')).toHaveTextContent('exact');
		expect(rows[1].querySelector('[data-tag="proposed"]')).toHaveTextContent('proposed');
		// not yet typed
		expect(rows[2]).toHaveTextContent('not yet typed');
		expect(rows[2]).toHaveTextContent('will be typed as a transfer');
		// paired elsewhere
		expect(rows[3].querySelector('[data-slot="offer-paired"]')).toHaveTextContent(
			/paired with Card · Oct 8, 2026 · \S?50\.00/
		);
		expect(rows[3]).not.toHaveTextContent('breaks');
		// no caption under the heading: the heading and the row's "paired with" say it
		expect(list.querySelector('[data-slot="group-caption"]')).toBeNull();
		// the counter-leg: last, in its own group
		expect(within(list).getByText('New')).toBeInTheDocument();
		expect(rows[4]).toHaveTextContent('Create the other side in');
		expect(rows[4]).toHaveTextContent('Dollar cash');
	});

	it('scrolls when long', async () => {
		const { dialog } = await openTransfer({ transfer: transfer() });
		const list = await openList(dialog);

		expect(list.className).toContain('max-h-72');
		expect(list.className).toContain('overflow-y-auto');
	});

	it('says there are no candidates in an empty window', async () => {
		const { dialog } = await openTransfer({ transfer: transferOut({ state: 'unmatched' }) });

		await fireEvent.click(trigger(dialog));

		expect(await screen.findByText('No candidates in this window')).toBeInTheDocument();
		expect(screen.queryByRole('option')).toBeNull();
	});

	it('loads more candidates by widening the window of the next preview, 30 then 90 days', async () => {
		const { dialog } = await openTransfer({
			transfer: transferOut({ state: 'unmatched', offers, has_more: true })
		});
		await openList(dialog);
		expect(vi.mocked(previewUnit).mock.calls.at(-1)![2]).toBeNull();

		await fireEvent.click(screen.getByRole('button', { name: 'Load more candidates' }));
		await waitFor(() => expect(vi.mocked(previewUnit).mock.calls.at(-1)![2]).toBe(30));
		await waitFor(() =>
			expect(screen.getByRole('button', { name: 'Load more candidates' })).toBeEnabled()
		);
		await fireEvent.click(screen.getByRole('button', { name: 'Load more candidates' }));
		await waitFor(() => expect(vi.mocked(previewUnit).mock.calls.at(-1)![2]).toBe(90));

		// nothing wider: the link is gone and the window is named
		await waitFor(() =>
			expect(screen.queryByRole('button', { name: 'Load more candidates' })).toBeNull()
		);
		expect(screen.getByText('Candidates within 90 days.')).toBeInTheDocument();
	});

	it('shows no "Load more candidates" without more', async () => {
		const { dialog } = await openTransfer({ transfer: transfer() });
		await openList(dialog);

		expect(screen.queryByRole('button', { name: 'Load more candidates' })).toBeNull();
	});

	it('finds a candidate by what is written on it', async () => {
		const { dialog } = await openTransfer({ transfer: transfer() });
		const list = await openList(dialog);

		await fireEvent.input(screen.getByLabelText('Search candidates'), {
			target: { value: 'unknown' }
		});

		expect(within(list).getAllByRole('option')).toHaveLength(1);
		expect(within(list).getByRole('option')).toHaveTextContent('Unknown deposit');
	});

	it('picking an offer is a draft edit: the pairing goes into the request and the draft is dirty', async () => {
		const picked = (request: UnitDraftRequest) =>
			request.entries?.some((e) => e.pairing?.mode === 'pick');
		const { dialog, panel } = await openTransfer({
			transfer: (request) =>
				picked(request)
					? transferOut({
							state: 'paired',
							partner: {
								entry_id: 2,
								account_id: 2,
								booked_on: '2026-10-10',
								amount: { amount: 5000, currency: 'EUR' },
								description: 'Transfer in'
							}
						})
					: transfer(),
			extra: (request, out) => {
				if (!picked(request)) return;
				out.rows.push(partnerRow());
				out.units[0].entry_ids.push(2);
			}
		});
		const list = await openList(dialog);
		expect(panel.flow.isDirty).toBe(false);

		await fireEvent.click(within(list).getByRole('option', { name: /Transfer in/ }));

		await waitFor(() =>
			expect(lastRequest().entries).toEqual([
				{ id: 1, pairing: { mode: 'pick', partner_entry_id: 2 } }
			])
		);
		expect(panel.flow.isDirty).toBe(true);
		// the popover closed, and the partner's leg joined the unit as a group of its own
		await waitFor(() => expect(screen.queryByRole('listbox')).toBeNull());
		await waitFor(() =>
			expect(dialog.querySelectorAll('[data-slot="source-group"]')).toHaveLength(2)
		);
		const headers = [...dialog.querySelectorAll('[data-slot="group-header"]')];
		expect(headers.map((h) => h.textContent)).toEqual([
			expect.stringContaining('Giro'),
			expect.stringContaining('Savings')
		]);
		expect(within(dialog).getByText('picked by you')).toBeInTheDocument();
	});

	it('Reset takes the pick back', async () => {
		const { dialog, panel } = await openTransfer({ transfer: transfer() });
		const list = await openList(dialog);
		await fireEvent.click(within(list).getByRole('option', { name: /Transfer in/ }));
		await waitFor(() => expect(lastRequest().entries).toHaveLength(1));

		await fireEvent.click(within(dialog).getByRole('button', { name: 'Reset' }));

		await waitFor(() => expect(lastRequest().entries).toEqual([]));
		expect(panel.flow.isDirty).toBe(false);
	});

	it('"Reset to proposal" takes back the pick only', async () => {
		const { dialog } = await openTransfer({ transfer: transfer() });
		const list = await openList(dialog);
		await fireEvent.click(within(list).getByRole('option', { name: /Transfer in/ }));
		await waitFor(() => expect(lastRequest().entries).toHaveLength(1));

		await fireEvent.click(within(dialog).getByRole('button', { name: 'Reset to proposal' }));

		await waitFor(() => expect(lastRequest().entries).toEqual([]));
	});

	it('re-resolving leaves no pick in the request', async () => {
		const { dialog, panel } = await openTransfer({ transfer: transfer() });
		const list = await openList(dialog);
		await fireEvent.click(within(list).getByRole('option', { name: /Transfer in/ }));
		await waitFor(() => expect(lastRequest().entries).toHaveLength(1));

		panel.flow.reresolve(true);

		await waitFor(() => expect(lastRequest()).toMatchObject({ reresolve_all: true, entries: [] }));
	});

	it('moves with ↑ ↓, picks with Enter', async () => {
		const { dialog } = await openTransfer({ transfer: transfer() });
		await openList(dialog);
		const find = screen.getByLabelText('Search candidates');

		await fireEvent.keyDown(find, { key: 'ArrowDown' });
		await fireEvent.keyDown(find, { key: 'ArrowDown' });
		await fireEvent.keyDown(find, { key: 'Enter' });

		await waitFor(() =>
			expect(lastRequest().entries![0].pairing).toEqual({ mode: 'pick', partner_entry_id: 5 })
		);
	});

	it('closes with Esc, and the panel stays', async () => {
		const { dialog } = await openTransfer({ transfer: transfer() });
		await openList(dialog);

		await fireEvent.keyDown(screen.getByLabelText('Search candidates'), { key: 'Escape' });

		await waitFor(() => expect(screen.queryByRole('listbox')).toBeNull());
		expect(screen.getByRole('dialog', { name: /./ })).toBeInTheDocument();
		expect(lastRequest().entries).toEqual([]);
	});

	it('opens with p, from the panel', async () => {
		const { dialog } = await openTransfer({ transfer: transfer() });

		await fireEvent.keyDown(dialog, { key: 'p' });

		expect(await screen.findByRole('listbox', { name: 'Partner candidates' })).toBeInTheDocument();
	});

	it('x still turns the transfer into a flow, with no pairing in the request', async () => {
		const { dialog } = await openTransfer({ transfer: transfer() });
		const list = await openList(dialog);
		await fireEvent.click(within(list).getByRole('option', { name: /Transfer in/ }));
		await waitFor(() => expect(lastRequest().entries![0].pairing).toBeDefined());

		await fireEvent.keyDown(dialog, { key: 'x' });

		await waitFor(() =>
			expect(lastRequest().entries![0].type).toEqual({ mode: 'fixed', value: 'flow' })
		);
		expect(lastRequest().entries![0].pairing).toBeUndefined();
	});
});

describe('the fee of a picked pair', () => {
	const offers = [offerOut({ entry_id: 2, exact: false })];
	const suggested = { source_entry_id: 1, amount: { amount: 250, currency: 'EUR' } };
	const unequal = () =>
		problem('pair_unequal', {
			entry_id: 1,
			detail: { partner: 2, difference: 250 },
			suggested_split: suggested
		});

	it('is split off by itself, once, right after the pick: "Created", and the manual link stays for the rest', async () => {
		const { dialog, panel } = await openTransfer({
			transfer: transferOut({ state: 'unmatched', offers }),
			extra: (request, out) => {
				const picked = request.entries?.some((e) => e.pairing?.mode === 'pick');
				const split = request.entries?.find((e) => e.id === -1);
				if (picked && !split) out.problems = [unequal()];
				if (split) {
					const created = previewRowOf(
						entry({ id: -1, amount: { amount: split.amount ?? 0, currency: 'EUR' } }),
						{ version: null, original: false, source_transaction_id: 5 }
					);
					out.rows.push(created);
					out.consequences = [{ entry_id: -1, kind: 'created', version: null, row: created }];
				}
			}
		});
		const list = await openList(dialog);

		await fireEvent.click(within(list).getByRole('option'));

		await waitFor(() =>
			expect(lastRequest().entries).toContainEqual(
				expect.objectContaining({ id: -1, source_entry_id: 1, amount: -250 })
			)
		);
		expect(await within(dialog).findByRole('region', { name: 'Created' })).toBeInTheDocument();
		// applied once: another preview does not split again
		panel.flow.setText(1, 'note', 'x');
		await waitFor(() => expect(panel.flow.previewStatus).toBe('ready'));
		expect(
			requests()
				.at(-1)!
				.entries!.filter((e) => e.id < 0)
		).toHaveLength(1);
	});

	it('leaves the manual "Split off the difference" where the suggestion was not applied', async () => {
		const { dialog, panel } = await openTransfer({
			transfer: transferOut({ state: 'unmatched', offers }),
			extra: (_request, out) => {
				out.problems = [unequal()];
			}
		});
		const link = await within(dialog).findByRole('button', { name: 'Split off the difference' });

		await fireEvent.click(link);

		await waitFor(() => expect(panel.flow.draft?.splits).toHaveLength(1));
		expect(panel.flow.draft?.edit(-1).amount).toBe(-250);
	});
});

describe('the problems of a pick', () => {
	it('says in words that the partner is not offered or already in the unit', async () => {
		const { dialog } = await openTransfer({
			transfer: transferOut({ state: 'unmatched' }),
			extra: (_request, out) => {
				out.problems = [
					problem('partner_not_offered', { entry_id: 1 }),
					problem('partner_in_unit', { entry_id: 1 })
				];
			}
		});

		const list = within(dialog).getByRole('list', { name: 'Problems' });
		expect(list).toHaveTextContent(
			'This entry is not offered as a partner (wrong account, direction or date).'
		);
		expect(list).toHaveTextContent('This entry is already part of this unit.');
	});
});
