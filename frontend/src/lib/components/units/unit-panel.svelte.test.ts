import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { account, category, entry, payee, tag } from '#lib/ledger/fixtures.js';
import { buildLookups } from '#lib/ledger/lookups.js';
import { rule, source } from '#lib/rules/fixtures.js';
import { ruleNames } from '#lib/stores/rule-names.svelte.js';
import { apiError, preview, transferOut, unit } from '#lib/units/fixtures.js';
import { UnitPanel, type PanelNav } from '#lib/units/panel.svelte.js';
import { registerUnitSource } from '#lib/units/sources.js';
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
	accounts: [account({ id: 1, name: 'Giro' }), account({ id: 2, name: 'Savings' })],
	categories: [category({ id: 10, name: 'Groceries' })],
	payees: [payee({ id: 20, name: 'REWE' })],
	tags: [tag({ id: 30, name: 'Lisbon trip' })]
});

function nav(start = '/ledger'): PanelNav {
	const stack = [start];
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

async function openPanel(
	shown: ReturnType<typeof unit>,
	id = shown.anchor_entry_id,
	answer: ReturnType<typeof preview> = preview(shown)
) {
	vi.mocked(getUnit).mockResolvedValue(shown);
	vi.mocked(previewUnit).mockResolvedValue(answer);
	const panel = new UnitPanel(nav());
	render(UnitPanelView, { props: { panel, lookups, locale: 'en' } });
	panel.open(id);
	const dialog = await screen.findByRole('dialog');
	await waitFor(() => expect(panel.status).toBe('ready'));
	await waitFor(() => expect(panel.flow.previewStatus).toBe('ready'));
	return { panel, dialog };
}

beforeEach(() => {
	vi.resetAllMocks();
	// a preview that never arrives, unless a test says otherwise
	vi.mocked(previewUnit).mockImplementation(() => new Promise(() => {}));
	ruleNames.reset();
	vi.mocked(listRules).mockResolvedValue([rule({ id: 3, name: 'Rewe' })]);
});

describe('UnitPanel: a flow unit', () => {
	it('is a modal dialog labelled by the unit title, with the state under it', async () => {
		const { dialog } = await openPanel(
			unit({
				anchor_entry_id: 1,
				entries: [entry({ id: 1, unit_key: 1, display_text: 'REWE Markt Berlin' })]
			})
		);

		expect(dialog).toHaveAccessibleName('REWE Markt Berlin');
		expect(dialog).toHaveAttribute('aria-modal', 'true');
		expect(dialog.querySelector('[data-slot="unit-state"]')).toHaveTextContent(
			'Proposals to check'
		);
	});

	it('starts with focus on the panel itself, not on a field, so the step keys work at once', async () => {
		const { dialog } = await openPanel(unit());

		await waitFor(() => expect(dialog).toHaveFocus());
	});

	it('shows each value with its basis; proposals are italic, decided values are not', async () => {
		const { dialog } = await openPanel(unit());

		const history = within(dialog).getByText('history: 3 of 4 since Mar 2026');
		expect(history).toHaveAttribute('data-proposal', 'true');
		expect(history).toHaveClass('italic');
		const rule = await within(dialog).findByRole('link', { name: 'rule: Rewe' });
		expect(rule).toHaveAttribute('href', '/settings/rules/3');
		expect(rule.closest('[data-slot="evidence"]')).not.toHaveAttribute('data-proposal');
		// the proposed category is italic too; the decided payee is not
		expect(within(dialog).getByText('Groceries').closest('[data-proposal]')).toHaveClass('italic');
		expect(within(dialog).getByText('REWE').closest('[data-proposal]')).toBeNull();
	});

	it('says a rule is deleted when the loaded list lacks it', async () => {
		vi.mocked(listRules).mockResolvedValue([]);
		const { dialog } = await openPanel(unit());
		expect(await within(dialog).findByText('rule deleted')).toBeInTheDocument();
	});

	it('shows the source strip: counterparty, purpose, booking text, instructed amount', async () => {
		const { dialog } = await openPanel(
			unit({
				anchor_entry_id: 1,
				entries: [
					entry({
						id: 1,
						unit_key: 1,
						source_transaction_id: 5,
						source: source({
							counterparty_name: 'REWE Markt',
							purpose: 'Card payment 0815',
							booking_text: 'Kartenzahlung',
							instructed_amount: { amount: -5000, currency: 'USD' }
						})
					})
				]
			})
		);

		const strip = within(dialog).getByRole('region', { name: 'Source transaction' });
		expect(strip).toHaveTextContent('REWE Markt');
		expect(strip).toHaveTextContent('Card payment 0815');
		expect(strip).toHaveTextContent('Kartenzahlung');
		expect(strip).toHaveTextContent('USD');
	});

	it('shows the tags of an entry as chips, with a way to change them in the draft', async () => {
		const { dialog } = await openPanel(
			unit({
				anchor_entry_id: 1,
				entries: [entry({ id: 1, unit_key: 1, tag_ids: [30] })]
			})
		);

		expect(within(dialog).getByText('Lisbon trip')).toBeInTheDocument();
		expect(within(dialog).getByRole('button', { name: 'Add or remove tags' })).toBeInTheDocument();
		expect(within(dialog).queryByText(/Saved immediately/)).toBeNull();
	});

	it('has its own keyboard help: [ ] and Esc, opened by the button or by ? inside the panel', async () => {
		const { dialog } = await openPanel(unit());
		const button = within(dialog).getByRole('button', { name: /Keyboard shortcuts/ });

		await fireEvent.click(button);
		const help = within(dialog).getByRole('region', { name: 'Keyboard shortcuts' });
		expect(help).toHaveTextContent('Previous unit');
		expect(help).toHaveTextContent('Next unit');
		expect(help).toHaveTextContent('Esc');
		expect(help).not.toHaveTextContent('Tag the row'); // the list's keys are not the panel's

		await fireEvent.keyDown(dialog, { key: 'Escape' });
		expect(within(dialog).queryByRole('region', { name: 'Keyboard shortcuts' })).toBeNull();
		await fireEvent.keyDown(dialog, { key: '?' });
		expect(within(dialog).getByRole('region', { name: 'Keyboard shortcuts' })).toBeInTheDocument();
	});

	it('Esc closes the help alone: the panel stays open', async () => {
		const { panel, dialog } = await openPanel(unit());
		await fireEvent.keyDown(dialog, { key: '?' });

		await fireEvent.keyDown(dialog, { key: 'Escape' });

		expect(panel.isOpen).toBe(true);
	});

	it('shows the model rationale on demand', async () => {
		const { dialog } = await openPanel(
			unit({
				anchor_entry_id: 1,
				entries: [
					entry({
						id: 1,
						unit_key: 1,
						derivation: { category: { pass: 'llm', basis: { rationale: 'Looks like groceries' } } }
					})
				]
			})
		);

		expect(within(dialog).getByText('suggested by the model')).toBeInTheDocument();
		expect(screen.queryByText('Looks like groceries')).toBeNull();
		await fireEvent.click(within(dialog).getByRole('button', { name: 'Show rationale' }));
		expect(await screen.findByText('Looks like groceries')).toBeInTheDocument();
	});
});

describe('UnitPanel: other units', () => {
	it('shows a split as one block per entry under its one source', async () => {
		const src = source({ counterparty_name: 'Amazon' });
		const { dialog } = await openPanel(
			unit({
				anchor_entry_id: 1,
				entries: [
					entry({
						id: 1,
						unit_key: 1,
						source: src,
						source_transaction_id: 5,
						display_text: 'Amazon'
					}),
					entry({
						id: 2,
						unit_key: 1,
						source: src,
						source_transaction_id: 5,
						display_text: 'Amazon'
					})
				]
			})
		);

		expect(dialog).toHaveAccessibleName('Amazon (split in 2)');
		expect(within(dialog).getAllByRole('region', { name: /^Entry / })).toHaveLength(2);
		expect(within(dialog).getAllByRole('region', { name: 'Source transaction' })).toHaveLength(1);
	});

	it('shows both legs of a pair and each one’s partner', async () => {
		const { dialog } = await openPanel(
			unit({
				anchor_entry_id: 1,
				state: { confirmed: true, reasons: [] },
				entries: [
					entry({
						id: 1,
						unit_key: 1,
						type: 'transfer',
						account_id: 1,
						counter_account_id: 2,
						counterpart_entry_id: 2,
						amount: { amount: -5000, currency: 'EUR' },
						partner: {
							entry_id: 2,
							account_id: 2,
							booked_on: '2026-10-10',
							amount: { amount: 5000, currency: 'EUR' }
						}
					}),
					entry({
						id: 2,
						unit_key: 1,
						type: 'transfer',
						account_id: 2,
						counter_account_id: 1,
						counterpart_entry_id: 1,
						amount: { amount: 5000, currency: 'EUR' },
						partner: {
							entry_id: 1,
							account_id: 1,
							booked_on: '2026-10-09',
							amount: { amount: -5000, currency: 'EUR' }
						}
					})
				]
			})
		);

		expect(dialog).toHaveAccessibleName('Transfer Giro → Savings');
		expect(dialog.querySelector('[data-slot="unit-state"]')).toHaveTextContent('Confirmed');
		expect(within(dialog).getAllByRole('region', { name: /^Entry / })).toHaveLength(2);
		expect(within(dialog).getAllByText('Partner leg')).toHaveLength(2);
	});

	it('shows the source of an authored entry like any other, with a small "Entered by hand"', async () => {
		const { dialog } = await openPanel(
			unit({
				anchor_entry_id: 1,
				entries: [
					entry({
						id: 1,
						unit_key: 1,
						authored: true,
						source_transaction_id: 5,
						display_text: 'Flea market',
						source: source({
							counterparty_name: 'Flea market',
							purpose: 'Chair',
							amount: { amount: -2500, currency: 'EUR' }
						}),
						derivation: {}
					})
				]
			})
		);

		const strip = within(dialog).getByRole('region', { name: 'Source transaction' });
		expect(strip).toHaveTextContent('Amount');
		expect(strip).toHaveTextContent('25.00');
		expect(strip).toHaveTextContent('Flea market');
		expect(strip).toHaveTextContent('Chair');
		expect(within(strip).getByText('Entered by hand')).toBeInTheDocument();
		expect(within(dialog).queryByRole('region', { name: 'Entered by hand' })).toBeNull();
	});

	it('shows the amount of the source transaction in the strip, for an imported entry too', async () => {
		const { dialog } = await openPanel(
			unit({
				anchor_entry_id: 1,
				entries: [
					entry({
						id: 1,
						unit_key: 1,
						source_transaction_id: 5,
						source: source({ amount: { amount: -4731, currency: 'EUR' } })
					})
				]
			})
		);

		const strip = within(dialog).getByRole('region', { name: 'Source transaction' });
		expect(strip).toHaveTextContent('Amount');
		expect(strip).toHaveTextContent('47.31');
		expect(within(strip).queryByText('Entered by hand')).toBeNull();
	});

	it('offers "Create rule from this transaction" in the strip: a new tab, the entry as the example', async () => {
		const { dialog } = await openPanel(
			unit({
				anchor_entry_id: 7,
				entries: [entry({ id: 7, unit_key: 1, source_transaction_id: 5, source: source() })]
			})
		);

		const strip = within(dialog).getByRole('region', { name: 'Source transaction' });
		const link = within(strip).getByRole('link', { name: 'Create rule from this transaction' });
		expect(link).toHaveAttribute('data-slot', 'add-rule-from-source');
		expect(link.textContent?.trim()).toBe('');
		const reveal = link.closest('[data-slot="add-rule-reveal"]')!;
		expect(reveal).toHaveClass(
			'opacity-0',
			'group-hover:opacity-100',
			'group-focus-within:opacity-100',
			'[@media(hover:none)]:opacity-100'
		);
		expect(link).toHaveAttribute('href', '/settings/rules/new?from=7');
		expect(link).toHaveAttribute('target', '_blank');
		expect(link).toHaveAttribute('rel', 'noopener');
	});

	it('offers it for an authored entry that has a source, but not without one or for a derived entry', async () => {
		const authored = await openPanel(
			unit({
				anchor_entry_id: 3,
				entries: [
					entry({
						id: 3,
						unit_key: 1,
						authored: true,
						source_transaction_id: 5,
						source: source(),
						derivation: {}
					})
				]
			})
		);
		expect(
			within(authored.dialog).getByRole('link', { name: 'Create rule from this transaction' })
		).toHaveAttribute('href', '/settings/rules/new?from=3');
		cleanup();

		const bare = await openPanel(
			unit({
				anchor_entry_id: 1,
				entries: [entry({ id: 1, unit_key: 1, authored: true, derivation: {} })]
			})
		);
		expect(
			within(bare.dialog).queryByRole('link', { name: 'Create rule from this transaction' })
		).toBeNull();
		cleanup();

		const derived = await openPanel(
			unit({
				anchor_entry_id: 2,
				entries: [entry({ id: 2, unit_key: 1, type: 'opening', source: null })]
			})
		);
		expect(
			within(derived.dialog).queryByRole('link', { name: 'Create rule from this transaction' })
		).toBeNull();
	});

	it('says "Entered by hand" for an authored entry without a source and shows no source columns', async () => {
		const { dialog } = await openPanel(
			unit({
				anchor_entry_id: 1,
				entries: [
					entry({ id: 1, unit_key: 1, authored: true, display_text: 'Flea market', derivation: {} })
				]
			})
		);

		expect(within(dialog).getByRole('region', { name: 'Entered by hand' })).toHaveTextContent(
			'Entered by hand'
		);
		expect(within(dialog).queryByText('Counterparty')).toBeNull();
	});
});

describe('UnitPanel: states', () => {
	it('shows a skeleton while loading', async () => {
		vi.mocked(getUnit).mockReturnValue(new Promise(() => {}));
		const panel = new UnitPanel(nav());
		render(UnitPanelView, { props: { panel, lookups } });
		panel.open(1);

		const dialog = await screen.findByRole('dialog');
		expect(dialog.querySelectorAll('[data-skeleton]').length).toBeGreaterThan(0);
		expect(dialog).toHaveTextContent('Loading the unit…');
	});

	it('offers Try again when the load failed', async () => {
		vi.mocked(getUnit).mockRejectedValueOnce(apiError(0, 'network_error'));
		const panel = new UnitPanel(nav());
		render(UnitPanelView, { props: { panel, lookups } });
		panel.open(1);
		await screen.findByRole('dialog');
		await screen.findByText('The unit could not be loaded');

		vi.mocked(getUnit).mockResolvedValueOnce(unit());
		await fireEvent.click(screen.getByRole('button', { name: 'Try again' }));

		await waitFor(() => expect(panel.status).toBe('ready'));
	});

	it('says "This entry has no review" for a 404, with Close, and mentions the balance record', async () => {
		vi.mocked(getUnit).mockRejectedValue(apiError(404, 'not_found'));
		const panel = new UnitPanel(nav());
		render(UnitPanelView, { props: { panel, lookups } });
		panel.open(1);
		const dialog = await screen.findByRole('dialog');

		const notice = await within(dialog).findByText(/Derived from a balance record/);
		expect(notice).toBeInTheDocument();
		expect(dialog).toHaveAccessibleName('This entry has no review');
		const close = within(dialog.querySelector('[data-slot="no-review"]') as HTMLElement).getByRole(
			'button',
			{ name: 'Close' }
		);
		await fireEvent.click(close);

		await waitFor(() => expect(panel.isOpen).toBe(false));
		await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
	});
});

describe('UnitPanel: keys', () => {
	it('] and [ step through the list the panel was opened from', async () => {
		const { panel, dialog } = await openPanel(unit({ anchor_entry_id: 4 }));
		const neighbour = vi.fn((id: number, dir: -1 | 1) => (id === 4 ? (dir === 1 ? 9 : 2) : null));
		const off = registerUnitSource({ neighbour, patch: () => {} });
		vi.mocked(getUnit).mockResolvedValue(unit({ anchor_entry_id: 9 }));

		await fireEvent.keyDown(dialog, { key: ']' });

		await waitFor(() => expect(panel.unitId).toBe(9));
		expect(getUnit).toHaveBeenLastCalledWith(9, expect.any(AbortSignal));

		vi.mocked(getUnit).mockResolvedValue(unit({ anchor_entry_id: 2 }));
		neighbour.mockImplementation((id, dir) => (id === 9 && dir === -1 ? 2 : null));
		await fireEvent.keyDown(dialog, { key: '[' });
		await waitFor(() => expect(panel.unitId).toBe(2));
		off();
	});

	it('leaves the keys to a field when focus is in one', async () => {
		const { panel, dialog } = await openPanel(unit({ anchor_entry_id: 4 }));
		const input = document.createElement('input');
		dialog.append(input);
		const step = vi.spyOn(panel, 'step');

		await fireEvent.keyDown(input, { key: ']' });

		expect(step).not.toHaveBeenCalled();
	});

	it('shows where the unit is in the list when the source knows', async () => {
		vi.mocked(getUnit).mockResolvedValue(unit({ anchor_entry_id: 4 }));
		const off = registerUnitSource({
			neighbour: () => null,
			patch: () => {},
			position: () => ({ index: 12, total: 214 })
		});
		const panel = new UnitPanel(nav());
		render(UnitPanelView, { props: { panel, lookups } });
		panel.open(4);

		const dialog = await screen.findByRole('dialog');
		expect(await within(dialog).findByText('12 of 214')).toBeInTheDocument();
		off();
	});

	it('announces stepping politely', async () => {
		const { dialog } = await openPanel(unit());
		expect(dialog.querySelector('[aria-live="polite"]')).not.toBeNull();
	});

	it('closes from the close button and removes the address parameter', async () => {
		const { panel, dialog } = await openPanel(unit());

		await fireEvent.click(within(dialog).getAllByRole('button', { name: 'Close' })[0]);

		await waitFor(() => expect(panel.isOpen).toBe(false));
	});
});

describe('UnitPanel: grouped by source transaction', () => {
	function leg(id: number, account: number, src: number, booked: string, over = {}) {
		const amount = { amount: account === 1 ? -5000 : 5000, currency: 'EUR' };
		return entry({
			id,
			unit_key: 1,
			type: 'transfer',
			account_id: account,
			booked_on: booked,
			amount,
			source_transaction_id: src,
			source: source({ amount, counterparty_name: `Source ${src}` }),
			derivation: { counterpart: { pass: 'matcher_decision' } },
			...over
		});
	}
	const pair = (over = {}) =>
		unit({
			anchor_entry_id: 1,
			state: { confirmed: false, reasons: ['waiting_for_partner'] },
			entries: [leg(1, 1, 5, '2026-10-10', over), leg(2, 2, 6, '2026-10-09')]
		});

	// the preview as the server answers it for a matched pair: each leg names the other
	function pairedPreview(shown: ReturnType<typeof unit>) {
		const answer = preview(shown);
		for (const row of answer.rows) {
			const other = shown.entries.find((e) => e.id !== row.id)!;
			row.transfer = transferOut({
				state: 'paired',
				partner: {
					entry_id: other.id,
					account_id: other.account_id,
					booked_on: other.booked_on,
					amount: other.amount,
					description: 'Other side'
				}
			});
		}
		return answer;
	}

	it('shows a header per source ordered by date, a strip under each, and no pair line', async () => {
		const { dialog } = await openPanel(pair());

		expect(dialog.querySelector('[data-slot="pair-line"]')).toBeNull();
		expect(dialog).not.toHaveTextContent('Transfer between');
		const groups = [...dialog.querySelectorAll('[data-slot="source-group"]')];
		expect(groups).toHaveLength(2);
		const headers = groups.map((g) => g.querySelector('[data-slot="group-header"]')!);
		expect(headers[0]).toHaveTextContent('Savings');
		expect(headers[1]).toHaveTextContent('Giro');
		expect(groups[0]).toHaveTextContent('Source 6');
		expect(groups[1]).toHaveTextContent('Source 5');
		expect(within(dialog).queryByRole('button', { name: 'Pick another partner…' })).toBeNull();
	});

	it('makes each header a divider band that names only the account', async () => {
		const { dialog } = await openPanel(pair());

		const headers = [...dialog.querySelectorAll<HTMLElement>('[data-slot="group-header"]')];
		for (const header of headers) {
			expect(header.className).toContain('bg-muted');
			expect(header.className).toContain('border-b');
			expect(header.className).toContain('font-semibold');
			expect(header).not.toHaveTextContent('50.00');
			expect(header).not.toHaveTextContent('2026');
		}
		expect(headers[0].className).not.toContain('border-t');
		expect(headers[1].className).toContain('border-t');
	});

	it('indents the content of each group under a rule and leaves the preview region full width', async () => {
		const { dialog } = await openPanel(pair());

		const contents = dialog.querySelectorAll<HTMLElement>('[data-slot="group-content"]');
		expect(contents).toHaveLength(2);
		for (const content of contents) {
			expect(content.className).toContain('pl-3');
			expect(content.className).toContain('border-l');
			expect(content.querySelector('[data-slot="source-strip"]')).not.toBeNull();
			expect(content.querySelector('[data-slot="entry-editor"]')).not.toBeNull();
			expect(within(content).getByRole('button', { name: 'Split entry' })).toBeInTheDocument();
		}
		const region = dialog.querySelector<HTMLElement>('[data-slot="preview-region"]')!;
		expect(region.className).toContain('border-t-2');
		expect(region.className).not.toContain('pl-3');
		expect(region.closest('[data-slot="group-content"]')).toBeNull();
		expect(region.closest('[data-slot="source-group"]')).toBeNull();
		expect(region.className).toContain('bg-muted');
	});

	it('says in the partner row only where the partner is and how it came', async () => {
		const shown = pair();
		const { dialog } = await openPanel(shown, undefined, pairedPreview(shown));

		const rows = [...dialog.querySelectorAll<HTMLElement>('[data-slot="partner"]')];
		expect(rows).toHaveLength(2);
		// the groups run Savings (entry 2), then Giro (entry 1)
		expect(rows[0]).toHaveTextContent('Paired with the entry below');
		expect(rows[0].querySelector('[data-slot="partner-leg"]')).toHaveAttribute(
			'data-direction',
			'below'
		);
		expect(rows[1]).toHaveTextContent('Paired with the entry above');
		for (const row of rows) {
			expect(row).toHaveTextContent('matched automatically');
			expect(row).not.toHaveTextContent('Giro');
			expect(row).not.toHaveTextContent('Savings');
			expect(row).not.toHaveTextContent('2026');
			expect(row).not.toHaveTextContent('50.00');
			expect(row.querySelector('[aria-hidden="true"]')).toHaveTextContent(/^[↓↑]$/);
			expect(
				within(row).getByRole('button', { name: 'Pick another partner…' })
			).toBeInTheDocument();
		}
	});

	it('has a Split entry per group, and a split lands under the leg it was split from', async () => {
		const { dialog } = await openPanel(pair());
		const buttons = within(dialog).getAllByRole('button', { name: 'Split entry' });
		expect(buttons).toHaveLength(2);

		await fireEvent.click(buttons[0]);

		const counts = () =>
			[...dialog.querySelectorAll('[data-slot="source-group"]')].map(
				(g) => g.querySelectorAll('[data-slot="entry-editor"]').length
			);
		await waitFor(() => expect(counts()).toEqual([2, 1]));
		const first = dialog.querySelector('[data-slot="source-group"]')!;
		expect(first.querySelector('[data-new]')).not.toBeNull();
	});

	it('marks an authored source in its strip, not in the group header', async () => {
		const { dialog } = await openPanel(pair({ authored: true }));
		const headers = dialog.querySelectorAll('[data-slot="group-header"]');
		for (const header of headers) {
			expect(header.querySelector('[data-slot="authored-hint"]')).toBeNull();
		}
		const strips = dialog.querySelectorAll('[data-slot="source-strip"]');
		expect(strips[1].querySelector('[data-slot="authored-hint"]')).toHaveTextContent(
			'Entered by hand'
		);
		expect(strips[0].querySelector('[data-slot="authored-hint"]')).toBeNull();
	});

	it('keeps a single source plain: no header, no indent, the strip on top', async () => {
		const src = source({ counterparty_name: 'Amazon' });
		const { dialog } = await openPanel(
			unit({
				anchor_entry_id: 1,
				entries: [
					entry({ id: 1, unit_key: 1, source: src, source_transaction_id: 5 }),
					entry({ id: 2, unit_key: 1, source: src, source_transaction_id: 5 })
				]
			})
		);
		expect(dialog.querySelector('[data-slot="group-header"]')).toBeNull();
		expect(dialog.querySelector('[data-slot="pair-line"]')).toBeNull();
		for (const content of dialog.querySelectorAll('[data-slot="group-content"]')) {
			expect(content.className).not.toContain('pl-3');
			expect(content.className).not.toContain('border-l');
		}
		expect(dialog.querySelector('[data-slot="preview-region"]')!.className).not.toContain(
			'border-t-2'
		);
		expect(within(dialog).getAllByRole('button', { name: 'Split entry' })).toHaveLength(1);
		const body = dialog.querySelector('[data-slot="unit-body"]')!;
		expect(body.querySelector('[data-slot="source-strip"]')).not.toBeNull();
	});
});
