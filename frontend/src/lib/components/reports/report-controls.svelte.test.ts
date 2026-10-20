import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import { parseParams } from '#lib/reports/params.js';
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

	it('writes the period in the date chip and offers the new presets', async () => {
		setup('from=2026-01-01&to=2026-06-30');

		const chip = screen.getByRole('button', { name: /Jan 1 – Jun 30/ });
		await fireEvent.click(chip);

		expect(await screen.findByRole('button', { name: 'Last 12 months' })).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Last year' })).toBeInTheDocument();
	});
});
