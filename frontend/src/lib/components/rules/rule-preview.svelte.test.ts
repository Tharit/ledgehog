import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import { account, category } from '#lib/ledger/fixtures.js';
import { buildLookups } from '#lib/ledger/lookups.js';
import { preview, previewList, previewRow, source } from '#lib/rules/fixtures.js';
import RulePreview from './rule-preview.svelte';

const lookups = buildLookups({
	accounts: [account({ id: 1, name: 'Giro' })],
	categories: [category({ id: 10, name: 'Groceries' }), category({ id: 11, name: 'Rent' })]
});

const noRows = { matches: [], different_value: [], lost_key: [] };

function setup(props: Record<string, unknown> = {}) {
	const p = (props.preview ?? preview()) as ReturnType<typeof preview>;
	const rows = {
		matches: p.matches.rows,
		different_value: p.different_value.rows,
		lost_key: p.lost_key.rows
	};
	const onmore = vi.fn();
	const onretry = vi.fn();
	render(RulePreview, {
		props: {
			preview: p,
			status: 'ready',
			current: true,
			rows,
			columns: ['counterparty_name'],
			sets: 'category',
			lookups,
			ruleName: (id: number) => (id === 3 ? 'Wallet withdrawals' : undefined),
			onmore,
			onretry,
			...props
		}
	});
	return { onmore, onretry };
}

describe('RulePreview: the result', () => {
	it('leads with how many entries match, split by what the server counted', () => {
		setup({
			preview: preview({
				matches: previewList([previewRow()], 14),
				would_confirm: 6,
				stay_in_review: 3
			})
		});

		expect(screen.getByText(/Matches 14 entries/)).toHaveTextContent(
			'Matches 14 entries: 9 unconfirmed, 5 confirmed.'
		);
		expect(screen.getByText(/Of the 9 unconfirmed/)).toHaveTextContent(
			'Of the 9 unconfirmed: 6 would be confirmed, 3 stay in review. The 5 confirmed entries are not changed.'
		);
	});

	it('uses the singular', () => {
		setup({
			preview: preview({
				matches: previewList([previewRow()], 1),
				would_confirm: 1,
				stay_in_review: 0
			})
		});

		expect(screen.getByText(/Matches 1 entry/)).toHaveTextContent(
			'Matches 1 entry: 1 unconfirmed, 0 confirmed.'
		);
		expect(screen.getByText(/Of the unconfirmed entry/)).toHaveTextContent(
			'Of the unconfirmed entry: 1 would be confirmed, 0 stay in review.'
		);
		expect(screen.queryByText(/not changed/)).toBeNull();
	});

	it('says what happens to a single confirmed match and a single stay', () => {
		setup({
			preview: preview({
				matches: previewList([previewRow()], 3),
				would_confirm: 1,
				stay_in_review: 1
			})
		});

		expect(screen.getByText(/Of the 2 unconfirmed/)).toHaveTextContent(
			'Of the 2 unconfirmed: 1 would be confirmed, 1 stays in review. The confirmed entry is not changed.'
		);
	});

	it('says when nothing matches', () => {
		setup({ preview: preview() });

		expect(screen.getByText('Matches no entries')).toBeInTheDocument();
		expect(screen.queryByText(/would be confirmed/)).toBeNull();
	});

	it('says when there is nothing left to confirm', () => {
		setup({ preview: preview({ matches: previewList([previewRow({ confirmed: true })], 1) }) });

		expect(screen.getByText(/All matches are confirmed and stay unchanged/)).toBeInTheDocument();
	});
});

describe('RulePreview: the matched entries', () => {
	const matched = (rows = [previewRow()], total = rows.length) =>
		preview({ matches: previewList(rows, total) });
	const table = () => screen.getByRole('table', { name: 'Matched entries' });

	it('are a table with headers in two groups', () => {
		setup({ preview: matched() });

		const groups = within(table()).getAllByRole('columnheader');
		const names = groups.map((h) => h.textContent?.trim());
		expect(names.slice(0, 2)).toEqual(['Entry', 'Source transaction']);
		expect(names.slice(2)).toEqual([
			'Booked',
			'Account',
			'Amount',
			'Currently',
			'Counterparty name'
		]);
		expect(within(table()).getByText('Entry')).toHaveAttribute('colspan', '4');
	});

	it('show one source column for every field the conditions read, the counterparty name first', () => {
		setup({
			preview: matched([
				previewRow({ source: source({ purpose: 'Einkauf Markt', mandate_ref: 'M1' }) })
			]),
			columns: ['counterparty_name', 'purpose', 'mandate_ref']
		});

		const headers = within(table())
			.getAllByRole('columnheader')
			.map((h) => h.textContent?.trim());
		expect(headers.slice(-3)).toEqual(['Counterparty name', 'Purpose', 'Mandate reference']);
		expect(within(table()).getByText('Source transaction')).toHaveAttribute('colspan', '3');
		const row = within(table()).getAllByRole('row').at(-1)!;
		expect(row).toHaveTextContent('Landlord GmbH');
		expect(row).toHaveTextContent('Einkauf Markt');
		expect(row).toHaveTextContent('M1');
	});

	it('show the entry: date, account and amount, and what it holds now with its basis', () => {
		setup({
			preview: matched([
				previewRow({
					entry_id: 7,
					current_value: 11,
					current_key: { pass: 'rule', basis: { rule_id: 3 } }
				})
			])
		});

		const row = within(table()).getAllByRole('row').at(-1)!;
		expect(row).toHaveTextContent('Oct 1, 2026');
		expect(row).toHaveTextContent('Giro');
		expect(row).toHaveTextContent('−950.00');
		expect(row).toHaveTextContent('Rent');
		expect(row).toHaveTextContent('rule: Wallet withdrawals');
	});

	it('say "None yet" for an entry that holds nothing for what the rule sets', () => {
		setup({ preview: matched() });

		expect(within(table()).getByText('None yet')).toBeInTheDocument();
	});

	it('show a dash for a source field the entry lacks, and for an entry without a source', () => {
		setup({
			preview: matched([
				previewRow({ entry_id: 1, source: null }),
				previewRow({ entry_id: 2, source: source({ counterparty_name: null }) })
			])
		});

		expect(within(table()).getAllByText('—')).toHaveLength(2);
	});

	it('mark an unconfirmed one and not a confirmed one', () => {
		setup({
			preview: matched([
				previewRow({ entry_id: 1, confirmed: false }),
				previewRow({ entry_id: 2, confirmed: true })
			])
		});

		expect(screen.getAllByRole('img', { name: /Unconfirmed/i })).toHaveLength(1);
	});

	it('name the rule that takes precedence', () => {
		setup({ preview: matched([previewRow({ shadowed_by_rule_id: 3 })]) });

		expect(screen.getByText('Rule “Wallet withdrawals” takes precedence')).toBeInTheDocument();
	});

	it('fall back to the id of a rule that was not loaded', () => {
		setup({ preview: matched([previewRow({ shadowed_by_rule_id: 99 })]) });

		expect(screen.getByText('Rule “#99” takes precedence')).toBeInTheDocument();
	});

	it('have no links at all: rows are plain', () => {
		setup({
			preview: preview({
				matches: previewList([previewRow()], 1),
				different_value: previewList([previewRow({ entry_id: 8, current_value: 11 })], 1),
				lost_key: previewList([previewRow({ entry_id: 9, current_value: 10 })], 1)
			})
		});

		expect(screen.queryAllByRole('link', { hidden: true })).toHaveLength(0);
		expect(screen.queryByLabelText('Show in the ledger')).toBeNull();
	});

	it('scroll inside their own container', () => {
		setup({ preview: matched() });

		expect(table().closest('[data-slot="preview-table"]')?.className).toContain('overflow-x-auto');
	});

	it('say how many of the matches are shown, and ask for more', async () => {
		const { onmore } = setup({ preview: matched([previewRow()], 120) });

		expect(screen.getByText('Showing 1 of 120')).toBeInTheDocument();
		await fireEvent.click(screen.getByRole('button', { name: 'Show more' }));

		expect(onmore).toHaveBeenCalledWith('matches');
	});

	it('have no show-more once everything is shown', () => {
		setup({ preview: matched() });

		expect(screen.queryByRole('button', { name: 'Show more' })).toBeNull();
	});
});

describe('RulePreview: the two lists to check by hand', () => {
	const lists = preview({
		matches: previewList([previewRow()], 1),
		different_value: previewList([previewRow({ entry_id: 8, current_value: 11 })], 2),
		lost_key: previewList(
			[
				previewRow({
					entry_id: 9,
					current_value: 10,
					current_key: { pass: 'rule', basis: { rule_id: 77 } }
				})
			],
			1
		)
	});

	it('are collapsed by default, each with its count', () => {
		setup({ preview: lists });

		const different = screen.getByText(
			/Check by hand: hold a different value that settling leaves/
		);
		const lost = screen.getByText(/Carry this rule’s key but no longer match/);
		expect(different).toHaveTextContent('(2)');
		expect(lost).toHaveTextContent('(1)');
		expect(different.closest('details')).not.toHaveAttribute('open');
		expect(lost.closest('details')).not.toHaveAttribute('open');
	});

	it('use the same table, with the same headers', () => {
		setup({ preview: lists });

		const details = screen.getByText(/Check by hand/).closest('details')!;
		const headers = within(details)
			.getAllByRole('columnheader', { hidden: true })
			.map((h) => h.textContent?.trim());
		expect(headers).toEqual([
			'Entry',
			'Source transaction',
			'Booked',
			'Account',
			'Amount',
			'Currently',
			'Counterparty name'
		]);
	});

	it('hold the rows, with what the entry holds now and where it came from', () => {
		setup({ preview: lists });

		const details = screen.getByText(/Check by hand/).closest('details')!;
		expect(within(details).getAllByRole('row', { hidden: true }).at(-1)).toHaveTextContent('Rent');
		const lost = screen.getByText(/Carry this rule’s key/).closest('details')!;
		expect(within(lost).getAllByRole('row', { hidden: true }).at(-1)).toHaveTextContent(
			'rule deleted'
		);
	});

	it('ask for more of their own list', async () => {
		const { onmore } = setup({ preview: lists });
		const details = screen.getByText(/Check by hand/).closest('details')!;

		await fireEvent.click(within(details).getByRole('button', { name: 'Show more', hidden: true }));

		expect(onmore).toHaveBeenCalledWith('different_value');
	});

	it('say none when empty', () => {
		setup({ preview: preview({ matches: previewList([previewRow()], 1) }) });

		const details = screen.getByText(/Check by hand/).closest('details')!;
		expect(details).toHaveTextContent('(0)');
		expect(details).toHaveTextContent('None.');
	});
});

describe('RulePreview: its states', () => {
	it('explains what is needed while there is nothing to preview', () => {
		setup({ preview: null, status: 'idle', rows: noRows });

		expect(screen.getByText(/add a condition to see what it would do/)).toBeInTheDocument();
	});

	it('says so while the first preview is on its way', () => {
		setup({ preview: null, status: 'loading', current: false, rows: noRows });

		expect(screen.getByText(/Checking what would change/)).toBeInTheDocument();
		expect(screen.getByRole('region', { name: 'Preview' })).toHaveAttribute('aria-busy', 'true');
	});

	it('keeps the old preview, marked, while a new one is on its way', () => {
		setup({
			preview: preview({ matches: previewList([previewRow()], 5), would_confirm: 1 }),
			status: 'loading',
			current: false
		});

		expect(screen.getByText(/Updating for your last change/)).toBeInTheDocument();
		expect(screen.getByText(/Matches 5 entries/)).toBeInTheDocument();
	});

	it('gives the reason and a retry when the preview failed', async () => {
		const { onretry } = setup({
			preview: null,
			status: 'error',
			rows: noRows,
			failure: 'The server could not be reached.',
			retryable: true
		});

		expect(screen.getByText('The server could not be reached.')).toBeInTheDocument();
		await fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
		expect(onretry).toHaveBeenCalledOnce();
	});

	it('offers no retry for a rule the server refused', () => {
		setup({
			preview: null,
			status: 'error',
			rows: noRows,
			failure: 'The server did not accept this rule; see the highlighted field.'
		});

		expect(screen.queryByRole('button', { name: 'Try again' })).toBeNull();
	});
});
