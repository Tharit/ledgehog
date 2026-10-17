import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import type { ImportRun } from '#lib/accounts/runs.js';
import AccountRuns from './account-runs.svelte';

function run(over: Partial<ImportRun> = {}): ImportRun {
	return {
		id: 1,
		importer: 'csv',
		instance_id: 2,
		account_id: 1,
		kind: 'transactions',
		status: 'ok',
		started_at: '2026-10-11T08:00:00Z',
		finished_at: '2026-10-11T08:00:05Z',
		started_by: 1,
		error_text: null,
		covered_from: null,
		covered_through: '2026-10-10',
		stats: { inserted: 12, skipped_by_identity: 3, inserted_as_duplicates: [] },
		reverted_at: null,
		reverted_by: null,
		revertible: false,
		...over
	};
}

function runs(props = {}) {
	const handlers = { onrevert: vi.fn(), onshowall: vi.fn(), onretry: vi.fn() };
	render(AccountRuns, {
		props: {
			runs: [run({ id: 6, revertible: true }), run({ id: 5 })],
			status: 'ready',
			instanceLabel: () => 'Giro file',
			currency: 'EUR',
			...handlers,
			...props
		}
	});
	return handlers;
}

const li = (id: number) => document.querySelector(`[data-run-id="${id}"]`) as HTMLElement;

describe('AccountRuns', () => {
	it('shows instance, status, coverage and the one line of the summary', () => {
		runs();
		const row = within(li(6));
		expect(row.getByText('Giro file')).toBeInTheDocument();
		expect(row.getByText('Succeeded')).toBeInTheDocument();
		expect(row.getByText(/covered through Oct 10, 2026/)).toBeInTheDocument();
		expect(row.getByText('12 inserted · 0 as duplicates · 3 skipped')).toBeInTheDocument();
	});

	it('offers Revert… on the revertible run only, and says later runs go first on an earlier one', async () => {
		const h = runs();
		expect(within(li(5)).queryByRole('button', { name: 'Revert…' })).not.toBeInTheDocument();
		expect(within(li(5)).getByText('Later runs are reverted first.')).toBeInTheDocument();
		await fireEvent.click(within(li(6)).getByRole('button', { name: 'Revert…' }));
		expect(h.onrevert).toHaveBeenCalledWith(expect.objectContaining({ id: 6 }));
	});

	it('marks a reverted run and shows the error of a failed one', () => {
		runs({
			runs: [
				run({ id: 3, status: 'reverted' }),
				run({ id: 2, status: 'failed', error_text: 'ParseFailed: header not found', stats: {} })
			]
		});
		expect(within(li(3)).getByText('Reverted')).toBeInTheDocument();
		expect(within(li(2)).getByText('ParseFailed: header not found')).toBeInTheDocument();
	});

	it('opens the run summary in place', async () => {
		runs();
		await fireEvent.click(within(li(6)).getByRole('button', { expanded: false }));
		expect(within(li(6)).getByText('Skipped by identity')).toBeInTheDocument();
	});

	it('shows the latest five with Show all for the rest', async () => {
		const many = Array.from({ length: 7 }, (_, i) => run({ id: 10 - i }));
		const h = runs({ runs: many });
		expect(document.querySelectorAll('[data-run-id]')).toHaveLength(5);
		await fireEvent.click(screen.getByRole('button', { name: 'Show all' }));
		expect(h.onshowall).toHaveBeenCalled();
	});

	it('says when no import has run', () => {
		runs({ runs: [] });
		expect(screen.getByText('No import has run for this account.')).toBeInTheDocument();
	});

	it('offers Try again when the runs could not be loaded', async () => {
		const h = runs({ runs: [], status: 'error' });
		await fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
		expect(h.onretry).toHaveBeenCalled();
	});
});
