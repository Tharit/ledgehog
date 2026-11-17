import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import { parseParams } from '#lib/reports/params.js';
import { tag } from '#lib/ledger/fixtures.js';
import { buildLookups } from '#lib/ledger/lookups.js';
import { reportLookups } from '#lib/reports/trend-fixtures.js';
import ReportControls from './report-controls.svelte';

const TODAY = '2026-10-20';
const lookups = reportLookups();

function setup(search: string, props: Record<string, unknown> = {}) {
	const onchange = vi.fn();
	render(ReportControls, {
		props: {
			report: 'over-time',
			params: parseParams(search, 'over-time', TODAY),
			lookups,
			today: TODAY,
			onchange,
			...props
		}
	});
	return onchange;
}

describe('ReportControls', () => {
	it('shows the controls the address says, as pressed buttons', () => {
		setup('step=quarter&mode=category&kind=income', { mode: true, kind: true, step: true });

		expect(screen.getByRole('button', { name: 'Quarter' })).toHaveAttribute('aria-pressed', 'true');
		expect(screen.getByRole('button', { name: 'Month' })).toHaveAttribute('aria-pressed', 'false');
		expect(screen.getByRole('button', { name: 'By category' })).toHaveAttribute(
			'aria-pressed',
			'true'
		);
		expect(screen.getByRole('button', { name: 'Income' })).toHaveAttribute('aria-pressed', 'true');
	});

	it('reports a change of a control upward, to be written into the address', async () => {
		const onchange = setup('', { step: true, kind: true });

		await fireEvent.click(screen.getByRole('button', { name: 'Year' }));
		await fireEvent.click(screen.getByRole('button', { name: 'Income' }));

		expect(onchange).toHaveBeenNthCalledWith(1, { step: 'year' });
		expect(onchange).toHaveBeenNthCalledWith(2, { kind: 'income' });
	});

	it('shows only what the report has: Balances has no account or tag filter', () => {
		setup('', { filters: false });

		expect(screen.queryByRole('button', { name: /All accounts/ })).toBeNull();
		expect(screen.queryByRole('button', { name: /Tags/ })).toBeNull();
		expect(screen.queryByRole('button', { name: 'Year' })).toBeNull();
	});

	it('offers the transfer kinds in the by-account mode alone', () => {
		setup('mode=account', { mode: true, kind: true });

		expect(screen.getByRole('button', { name: 'Transfers in' })).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Transfers out' })).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'By account' })).toHaveAttribute(
			'aria-pressed',
			'true'
		);
	});

	it('has only Expense and Income in the by-category mode', () => {
		setup('mode=category', { mode: true, kind: true });

		expect(screen.queryByRole('button', { name: 'Transfers in' })).toBeNull();
		expect(screen.queryByRole('button', { name: 'Transfers out' })).toBeNull();
	});

	it('falls back to Expense when the mode leaves the accounts with a transfer kind', async () => {
		const onchange = setup('mode=account&kind=transfer_out', { mode: true, kind: true });

		await fireEvent.click(screen.getByRole('button', { name: 'By category' }));

		expect(onchange).toHaveBeenCalledWith({ mode: 'category', kind: 'expense' });
	});

	it('leaves the kind alone when the mode changes with a kind of every mode', async () => {
		const onchange = setup('mode=account&kind=income', { mode: true, kind: true });

		await fireEvent.click(screen.getByRole('button', { name: 'By category' }));

		expect(onchange).toHaveBeenCalledWith({ mode: 'category' });
	});

	it('By account has the period and the tags, no account filter', () => {
		setup('', { accounts: false });

		expect(screen.queryByRole('button', { name: /All accounts/ })).toBeNull();
		expect(screen.getByRole('button', { name: /Tags/ })).toBeInTheDocument();
		expect(screen.queryByRole('button', { name: 'Expense' })).toBeNull();
	});

	it('writes the period in the date chip and offers the new presets', async () => {
		setup('from=2026-01-01&to=2026-06-30');

		const chip = screen.getByRole('button', { name: /Jan 1 – Jun 30/ });
		await fireEvent.click(chip);

		expect(await screen.findByRole('button', { name: 'Last 12 months' })).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Last year' })).toBeInTheDocument();
	});
});

describe('ReportControls: the mark of an account and a tag option', () => {
	const tileOf = (row: HTMLElement) => row.querySelector<HTMLElement>('span[style*="--tile-fg"]');
	const withTags = () =>
		buildLookups({
			accounts: [...lookups.accounts.values()],
			tags: [tag({ id: 30, name: 'Lisbon trip', color: 'lavender' })]
		});

	it('draws an account with its icon in its own colour', async () => {
		setup('');

		await fireEvent.click(screen.getByRole('button', { name: 'All accounts' }));
		const row = (await screen.findByRole('checkbox', { name: 'Giro' })).closest('label')!;

		expect(tileOf(row)?.querySelector('svg')).not.toBeNull();
		expect(tileOf(row)?.getAttribute('style')).toContain('--dim-forest');
	});

	it('draws a tag as a chip in its colour, not a tile', async () => {
		setup('', { lookups: withTags() });

		await fireEvent.click(screen.getByRole('button', { name: 'Tags' }));
		const row = (await screen.findByRole('checkbox', { name: 'Lisbon trip' })).closest('label')!;

		const chip = row.querySelector<HTMLElement>('[data-slot="tag-chip"]');
		expect(chip).not.toBeNull();
		expect(chip?.getAttribute('style')).toContain('--dim-lavender');
		expect(tileOf(row)).toBeNull();
	});

	it('steps the period to the span before or after, of the same length', async () => {
		const onchange = setup('from=2026-02-01&to=2026-02-28');

		await fireEvent.click(screen.getByRole('button', { name: 'Previous period' }));
		await fireEvent.click(screen.getByRole('button', { name: 'Next period' }));

		expect(onchange).toHaveBeenNthCalledWith(1, { from: '2026-01-01', to: '2026-01-31' });
		expect(onchange).toHaveBeenNthCalledWith(2, { from: '2026-03-01', to: '2026-03-31' });
	});

	it('turns the next arrow off once the period reaches today', () => {
		setup('from=2026-10-01&to=2026-10-31');

		expect(screen.getByRole('button', { name: 'Next period' })).toBeDisabled();
		expect(screen.getByRole('button', { name: 'Previous period' })).toBeEnabled();
	});
});
