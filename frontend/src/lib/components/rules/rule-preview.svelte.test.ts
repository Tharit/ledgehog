import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import { account, category } from '#lib/ledger/fixtures.js';
import { buildLookups } from '#lib/ledger/lookups.js';
import { preview, previewList, previewRow } from '#lib/rules/fixtures.js';
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
			'Matches 14 entries (9 unconfirmed, 5 confirmed)'
		);
		expect(screen.getByText(/Would confirm/)).toHaveTextContent(
			'Would confirm 6 units, 3 stay in review'
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
			'Matches 1 entry (1 unconfirmed, 0 confirmed)'
		);
		expect(screen.getByText(/Would confirm/)).toHaveTextContent(
			'Would confirm 1 unit, 0 stay in review'
		);
	});

	it('says when nothing matches', () => {
		setup({ preview: preview() });

		expect(screen.getByText('Matches no entries')).toBeInTheDocument();
		expect(screen.queryByText(/Would confirm/)).toBeNull();
	});

	it('says when there is nothing left to confirm', () => {
		setup({ preview: preview({ matches: previewList([previewRow({ confirmed: true })], 1) }) });

		expect(screen.getByText(/every match is confirmed already/)).toBeInTheDocument();
	});
});

describe('RulePreview: the matched entries', () => {
	it('are compact rows with date, account, text and amount', () => {
		setup({
			preview: preview({
				matches: previewList([previewRow({ entry_id: 7, description: 'Rent October' })], 1),
				would_confirm: 1
			})
		});

		const row = within(screen.getByRole('list', { name: 'Matched entries' })).getByRole('listitem');
		expect(row).toHaveTextContent('Oct 1, 2026');
		expect(row).toHaveTextContent('Giro');
		expect(row).toHaveTextContent('Rent October');
		expect(row).toHaveTextContent('−950.00');
		expect(row.className).toContain('h-8');
	});

	it('mark an unconfirmed one and not a confirmed one', () => {
		setup({
			preview: preview({
				matches: previewList(
					[
						previewRow({ entry_id: 1, confirmed: false }),
						previewRow({ entry_id: 2, confirmed: true })
					],
					2
				)
			})
		});

		expect(screen.getAllByRole('img', { name: /Unconfirmed/i })).toHaveLength(1);
	});

	it('name the rule that takes precedence', () => {
		setup({
			preview: preview({
				matches: previewList([previewRow({ shadowed_by_rule_id: 3 })], 1)
			})
		});

		expect(screen.getByText('Rule “Wallet withdrawals” takes precedence')).toBeInTheDocument();
	});

	it('fall back to the id of a rule that was not loaded', () => {
		setup({
			preview: preview({ matches: previewList([previewRow({ shadowed_by_rule_id: 99 })], 1) })
		});

		expect(screen.getByText('Rule “#99” takes precedence')).toBeInTheDocument();
	});

	it('link to the ledger on that day, in that account', () => {
		setup({
			preview: preview({
				matches: previewList([previewRow({ booked_on: '2026-10-09', account_id: 1 })], 1)
			})
		});

		expect(screen.getByRole('link', { name: 'Show in the ledger' })).toHaveAttribute(
			'href',
			'/ledger?from=2026-10-09&to=2026-10-09&account_id=1'
		);
	});

	it('say how many of the matches are shown, and ask for more', async () => {
		const { onmore } = setup({
			preview: preview({ matches: previewList([previewRow()], 120) })
		});

		expect(screen.getByText('Showing 1 of 120')).toBeInTheDocument();
		await fireEvent.click(screen.getByRole('button', { name: 'Show more' }));

		expect(onmore).toHaveBeenCalledWith('matches');
	});

	it('have no show-more once everything is shown', () => {
		setup({ preview: preview({ matches: previewList([previewRow()], 1) }) });

		expect(screen.queryByRole('button', { name: 'Show more' })).toBeNull();
	});
});

describe('RulePreview: the two lists to check by hand', () => {
	const lists = preview({
		matches: previewList([previewRow()], 1),
		different_value: previewList([previewRow({ entry_id: 8, current_value: 11 })], 2),
		lost_key: previewList(
			[previewRow({ entry_id: 9, current_value: 10, keyed_fields: ['category'] })],
			1
		)
	});

	it('are collapsed by default, each with its count', () => {
		setup({ preview: lists });

		const different = screen.getByText(/Check by hand: hold a different value/);
		const lost = screen.getByText(/Carry this rule’s key but no longer match/);
		expect(different).toHaveTextContent('(2)');
		expect(lost).toHaveTextContent('(1)');
		expect(different.closest('details')).not.toHaveAttribute('open');
		expect(lost.closest('details')).not.toHaveAttribute('open');
	});

	it('hold the rows, with what the entry holds now', () => {
		setup({ preview: lists });

		const details = screen.getByText(/Check by hand/).closest('details')!;
		expect(within(details).getByRole('listitem', { hidden: true })).toHaveTextContent('holds');
		expect(within(details).getByRole('listitem', { hidden: true })).toHaveTextContent('Rent');
		const lost = screen.getByText(/Carry this rule’s key/).closest('details')!;
		expect(within(lost).getByRole('listitem', { hidden: true })).toHaveTextContent(
			'key on category'
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

		expect(screen.getByText(/Checking what this rule would do/)).toBeInTheDocument();
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
