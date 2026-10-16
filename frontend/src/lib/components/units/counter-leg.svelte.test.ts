import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { account, entry } from '#lib/ledger/fixtures.js';
import { buildLookups } from '#lib/ledger/lookups.js';
import { ruleNames } from '#lib/stores/rule-names.svelte.js';
import type { UnitDraftRequest, UnitOffer, UnitTransfer } from '#lib/units/types.js';
import {
	consequence,
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

// 3: an unsynced EUR account (same currency); 5: an unsynced USD account (cross-currency)
const lookups = buildLookups({
	accounts: [
		account({ id: 1, name: 'Giro' }),
		account({ id: 2, name: 'Savings' }),
		account({ id: 3, name: 'Cash', synced: false }),
		account({ id: 5, name: 'Dollar cash', currency: 'USD', synced: false })
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

const eur = (amount: number) => ({ amount, currency: 'EUR' });
const leg = (counter: number) =>
	entry({
		id: 1,
		unit_key: 1,
		type: 'transfer',
		account_id: 1,
		counter_account_id: counter,
		amount: eur(-10000),
		source_transaction_id: 5,
		review_flags: ['unconfirmed'],
		derivation: {}
	});

const sameOffer = (over: Partial<UnitOffer> = {}) =>
	offerOut({
		kind: 'counter_leg',
		entry_id: null,
		account_id: 3,
		booked_on: '2026-10-12',
		amount: eur(10000),
		description: null,
		counter_leg: {
			booked_on: '2026-10-12',
			purpose: 'Rent',
			amount: eur(10000),
			needs_received_amount: false
		},
		...over
	});
const crossOffer = (over: Partial<UnitOffer> = {}) =>
	offerOut({
		kind: 'counter_leg',
		entry_id: null,
		account_id: 5,
		booked_on: '2026-10-12',
		amount: null,
		description: null,
		counter_leg: {
			booked_on: '2026-10-12',
			purpose: 'Rent',
			amount: null,
			needs_received_amount: true
		},
		...over
	});

/** The synthetic row of the counter-leg, as the preview shows it. */
const ghostRow = (tempId: number, amount = eur(10000), accountId = 3) =>
	previewRowOf(
		entry({
			id: tempId,
			unit_key: 1,
			type: 'transfer',
			account_id: accountId,
			counter_account_id: 1,
			booked_on: '2026-10-12',
			amount,
			description: 'Rent',
			source_transaction_id: tempId,
			derivation: {}
		}),
		{
			original: false,
			in_unit: true,
			counter_leg_for: 1,
			transfer: transferOut({ state: 'paired' })
		}
	);

const isCounterLeg = (request: UnitDraftRequest) =>
	request.entries?.find((e) => e.id === 1)?.pairing?.mode === 'counter_leg';
const tempIdOf = (request: UnitDraftRequest) =>
	request.entries?.find((e) => e.id === 1)?.pairing?.counter_leg?.temp_id as number;

type Options = {
	counter: number;
	transfer: (request: UnitDraftRequest) => UnitTransfer;
	extra?: (request: UnitDraftRequest, out: ReturnType<typeof preview>) => void;
};

async function open({ counter, transfer, extra }: Options) {
	const shown = unit({ anchor_entry_id: 1, entries: [leg(counter)] });
	vi.mocked(getUnit).mockResolvedValue(shown);
	vi.mocked(previewUnit).mockImplementation(async (request: UnitDraftRequest) => {
		const out = preview(shown);
		out.rows[0].transfer = transfer(request);
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

async function pickCounterLeg(dialog: HTMLElement) {
	await fireEvent.click(within(dialog).getByRole('button', { name: /partner…/ }));
	const list = await screen.findByRole('listbox', { name: 'Partner candidates' });
	await fireEvent.click(within(list).getByRole('option', { name: /Create the other side/ }));
}

beforeEach(() => {
	vi.resetAllMocks();
	ruleNames.reset();
	vi.mocked(listRules).mockResolvedValue([]);
});
afterEach(() => cleanup());

describe('the counter-leg in the partner popover', () => {
	it('is the last group, "New": the account, and for the same currency what it receives', async () => {
		const { dialog } = await open({
			counter: 3,
			transfer: () => transferOut({ state: 'unmatched', offers: [sameOffer()] })
		});
		await fireEvent.click(within(dialog).getByRole('button', { name: 'Choose partner…' }));
		const list = await screen.findByRole('listbox', { name: 'Partner candidates' });

		expect(
			[...list.querySelectorAll('[data-slot="command-group"]')].map((g) =>
				g.getAttribute('data-group')
			)
		).toEqual(['new']);
		expect(within(list).getByText('New')).toBeInTheDocument();
		const row = within(list).getByRole('option');
		expect(row).toHaveTextContent('Create the other side in');
		expect(row).toHaveTextContent('Cash');
		expect(row.querySelector('[data-slot="offer-hint"]')).toHaveTextContent(
			/Receives \S?100\.00 EUR on Oct 12, 2026/
		);
	});

	it('is selectable for a cross-currency leg, which says the user enters the amount', async () => {
		const { dialog } = await open({
			counter: 5,
			transfer: () => transferOut({ state: 'unmatched', offers: [crossOffer()] })
		});
		await fireEvent.click(within(dialog).getByRole('button', { name: 'Choose partner…' }));
		const list = await screen.findByRole('listbox', { name: 'Partner candidates' });

		const row = within(list).getByRole('option');
		expect(row).toHaveTextContent('Dollar cash');
		expect(row).toHaveTextContent('You enter the amount received');
		expect(row).not.toHaveAttribute('aria-disabled', 'true');
	});

	it('marks the proposed counter-leg', async () => {
		const { dialog } = await open({
			counter: 3,
			transfer: () =>
				transferOut({
					state: 'unmatched',
					offers: [sameOffer({ proposed: true })]
				})
		});
		await fireEvent.click(within(dialog).getByRole('button', { name: 'Choose partner…' }));
		const list = await screen.findByRole('listbox', { name: 'Partner candidates' });

		expect(
			within(list).getByRole('option').querySelector('[data-tag="proposed"]')
		).toHaveTextContent('proposed');
	});

	it('picking it sends the counter-leg pairing with a client-issued negative id that stays', async () => {
		const { dialog, panel } = await open({
			counter: 3,
			transfer: (request) =>
				isCounterLeg(request)
					? transferOut({ state: 'unmatched', offers: [sameOffer()] })
					: transferOut({ state: 'unmatched', offers: [sameOffer()] })
		});
		expect(panel.flow.isDirty).toBe(false);

		await pickCounterLeg(dialog);

		await waitFor(() =>
			expect(lastRequest().entries).toEqual([
				{
					id: 1,
					pairing: { mode: 'counter_leg', counter_leg: { temp_id: -1, received_amount: null } }
				}
			])
		);
		expect(panel.flow.isDirty).toBe(true);
		await waitFor(() => expect(screen.queryByRole('listbox')).toBeNull());

		// another change: the same id again
		panel.flow.setField(1, 'category', 11);
		await waitFor(() => expect(requests().length).toBeGreaterThan(2));
		expect(tempIdOf(lastRequest())).toBe(-1);
	});
});

describe('the block of a pending counter-leg', () => {
	const picked = (request: UnitDraftRequest) =>
		transferOut({
			state: 'paired',
			offers: [sameOffer()],
			partner: {
				entry_id: tempIdOf(request),
				account_id: 3,
				booked_on: '2026-10-12',
				amount: eur(10000),
				description: 'Rent'
			}
		});

	it('says the other side is created when you commit, and what it creates', async () => {
		const { dialog } = await open({
			counter: 3,
			transfer: (request) =>
				isCounterLeg(request) ? picked(request) : transferOut({ offers: [sameOffer()] }),
			extra: (request, out) => {
				if (isCounterLeg(request)) {
					out.rows.push(ghostRow(tempIdOf(request)));
					out.units[0].entry_ids.push(tempIdOf(request));
				}
			}
		});
		await pickCounterLeg(dialog);

		await waitFor(() =>
			expect(partnerOf(dialog)).toHaveTextContent('The other side is created when you commit')
		);
		const row = partnerOf(dialog);
		// the group below shows the account, date and amount: the row does not repeat them
		await waitFor(() => expect(row.querySelector('[data-slot="counter-leg-creates"]')).toBeNull());
		expect(row).not.toHaveTextContent('Oct 12, 2026');
		expect(row).toHaveTextContent('picked by you');
		expect(row.querySelector('[data-proposal]')).toBeNull();
		// same currency: no input
		expect(within(dialog).queryByLabelText('Amount received')).toBeNull();
		// another partner stays available
		expect(
			within(dialog).getByRole('button', { name: 'Pick another partner…' })
		).toBeInTheDocument();
	});

	it('shows a proposed counter-leg italic with its evidence, and no edit in the draft', async () => {
		const { dialog, panel } = await open({
			counter: 3,
			transfer: () =>
				transferOut({
					state: 'paired',
					offers: [sameOffer({ proposed: true })],
					proposed_counter_leg: true,
					partner: {
						entry_id: -3,
						account_id: 3,
						booked_on: '2026-10-12',
						amount: eur(10000),
						description: 'Rent'
					}
				}),
			extra: (_request, out) => {
				out.rows.push(ghostRow(-3));
			}
		});

		const row = partnerOf(dialog);
		const line = row.querySelector('[data-slot="partner-leg"]')!;
		expect(line).toHaveAttribute('data-proposal');
		expect(line.className).toContain('italic');
		expect(line).toHaveTextContent('The other side is created when you commit');
		expect(row).toHaveTextContent('proposed: no open offer');
		expect(panel.flow.isDirty).toBe(false);
		expect(lastRequest().entries).toEqual([]);
		expect(
			within(dialog).getByRole('button', { name: 'Pick another partner…' })
		).toBeInTheDocument();
	});

	it('asks for the amount received of a cross-currency leg, with its currency, and sends it', async () => {
		const { dialog } = await open({
			counter: 5,
			transfer: () => transferOut({ state: 'unmatched', offers: [crossOffer()] }),
			extra: (request, out) => {
				if (isCounterLeg(request)) {
					out.problems = [problem('received_amount_required', { entry_id: 1 })];
				}
			}
		});
		await pickCounterLeg(dialog);

		const input = await within(dialog).findByLabelText('Amount received');
		expect(input.closest('[data-slot="received-amount"]')).toHaveTextContent('USD');
		// the required problem is said at the field
		await waitFor(() =>
			expect(
				within(input.closest('[data-slot="received-amount"]') as HTMLElement).getByRole('alert')
			).toHaveTextContent('Enter the amount received in USD.')
		);

		await fireEvent.input(input, { target: { value: '90.50' } });

		await waitFor(() =>
			expect(lastRequest().entries![0].pairing).toEqual({
				mode: 'counter_leg',
				counter_leg: { temp_id: -1, received_amount: 9050 }
			})
		);
	});

	it('rejects an ambiguous amount received at the field', async () => {
		const { dialog, panel } = await open({
			counter: 5,
			transfer: () => transferOut({ state: 'unmatched', offers: [crossOffer()] })
		});
		await pickCounterLeg(dialog);
		const input = await within(dialog).findByLabelText('Amount received');

		await fireEvent.input(input, { target: { value: '1,000' } });

		const field = input.closest('[data-slot="received-amount"]') as HTMLElement;
		expect(await within(field).findByRole('alert')).toHaveTextContent('Write the decimals out');
		expect(input).toHaveAttribute('aria-invalid', 'true');
		expect(panel.flow.commitReason).toBe('An amount is not valid.');
	});

	it('Reset to proposal takes the pick back', async () => {
		const { dialog, panel } = await open({
			counter: 3,
			transfer: (request) =>
				isCounterLeg(request) ? picked(request) : transferOut({ offers: [sameOffer()] }),
			extra: (request, out) => {
				if (isCounterLeg(request)) out.rows.push(ghostRow(tempIdOf(request)));
			}
		});
		await pickCounterLeg(dialog);
		await waitFor(() => expect(isCounterLeg(lastRequest())).toBe(true));

		await fireEvent.click(within(dialog).getByRole('button', { name: 'Reset to proposal' }));

		await waitFor(() => expect(lastRequest().entries).toEqual([]));
		expect(panel.flow.isDirty).toBe(false);
	});
});

describe('the ghost group', () => {
	async function openWithGhost() {
		return open({
			counter: 3,
			transfer: (request) =>
				isCounterLeg(request)
					? transferOut({
							state: 'paired',
							offers: [sameOffer()],
							partner: {
								entry_id: tempIdOf(request),
								account_id: 3,
								booked_on: '2026-10-12',
								amount: eur(10000),
								description: 'Rent'
							}
						})
					: transferOut({ offers: [sameOffer()] }),
			extra: (request, out) => {
				if (isCounterLeg(request)) out.rows.push(ghostRow(tempIdOf(request)));
			}
		});
	}

	it('shows the created entry read-only after the real group, with no controls', async () => {
		const { dialog } = await openWithGhost();
		await pickCounterLeg(dialog);

		await waitFor(() =>
			expect(dialog.querySelectorAll('[data-slot="source-group"]')).toHaveLength(2)
		);
		const group = dialog.querySelector<HTMLElement>('[data-ghost]')!;
		const header = group.querySelector('[data-slot="group-header"]')!;
		expect(header).toHaveTextContent('Cash');
		expect(header).toHaveTextContent('created when you commit');
		// the account only: date and amount are in the block below
		expect(header).not.toHaveTextContent('Oct 12, 2026');
		expect(header).not.toHaveTextContent('100.00');
		expect(header.className).toContain('bg-muted');
		expect(group.className).toContain('opacity');

		const block = group.querySelector<HTMLElement>('[data-slot="counter-leg-block"]')!;
		expect(block.className).toContain('border-dashed');
		expect(block.querySelector('[data-slot="counter-leg-type"]')).toHaveTextContent('Transfer');
		expect(block.querySelector('[data-slot="counter-leg-amount"]')).toHaveTextContent('100.00');
		expect(block.querySelector('[data-slot="counter-leg-date"]')).toHaveTextContent('Oct 12, 2026');
		expect(block.querySelector('[data-slot="counter-leg-purpose"]')).toHaveTextContent('Rent');
		expect(block.querySelector('[data-slot="counter-leg-provenance"]')).toHaveTextContent(
			'created for Giro'
		);

		// nothing to edit or split in it
		expect(group.querySelectorAll('input, textarea, select')).toHaveLength(0);
		expect(within(group).queryByRole('button')).toBeNull();
		expect(within(group).queryByText('Split entry')).toBeNull();
		expect(group.querySelector('[data-slot="entry-editor"]')).toBeNull();
		expect(within(group).queryByText('Tags')).toBeNull();
		// the real leg still splits
		expect(within(dialog).getAllByRole('button', { name: 'Split entry' })).toHaveLength(1);
	});

	it('has no pair line above the groups', async () => {
		const { dialog } = await openWithGhost();
		await pickCounterLeg(dialog);

		await waitFor(() =>
			expect(dialog.querySelectorAll('[data-slot="source-group"]')).toHaveLength(2)
		);
		expect(dialog.querySelector('[data-slot="pair-line"]')).toBeNull();
	});
});

describe('a follower in the consequences', () => {
	it('shows a linked counter-leg that follows the new amount as a changed row with its text and amount', async () => {
		const follower = previewRowOf(
			entry({
				id: 9,
				unit_key: 9,
				type: 'transfer',
				account_id: 3,
				booked_on: '2026-10-12',
				amount: eur(7000),
				description: 'Rent counter-leg',
				source_transaction_id: 60,
				derivation: {}
			}),
			{ original: true, in_unit: false }
		);
		const { dialog } = await open({
			counter: 3,
			transfer: () => transferOut({ state: 'unmatched', offers: [sameOffer()] }),
			extra: (_request, out) => {
				out.rows.push(follower);
				out.consequences = [consequence('changed', follower)];
			}
		});

		const changed = dialog.querySelector<HTMLElement>(
			'[data-slot="consequences"][data-kind="changed"]'
		)!;
		expect(changed).toHaveTextContent('Rent counter-leg');
		expect(changed).toHaveTextContent('70.00');
		expect(changed).toHaveTextContent('Cash');
	});
});
