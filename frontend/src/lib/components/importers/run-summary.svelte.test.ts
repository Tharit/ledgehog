import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import { run, upload } from '#lib/importers/fixtures.js';
import { dryRunAsRun } from '#lib/importers/run.js';
import RunSummary from './run-summary.svelte';

function summarise(over: Parameters<typeof run>[0] = {}, props: { dryRun?: boolean } = {}) {
	return render(RunSummary, { props: { run: run(over), currency: 'EUR', ...props } });
}

describe('RunSummary', () => {
	it('counts what the run did', () => {
		summarise({
			stats: {
				inserted: 12,
				skipped_by_identity: 3,
				inserted_as_duplicates: [],
				importer: { filtered: 2, synthetic_skipped: 1 },
				unexplained_difference: { before: null, after: null },
				since_zero: [],
				balance: { balance_on: '2026-03-29', balance: -84201 }
			}
		});
		expect(screen.getByText('12 rows')).toBeInTheDocument();
		expect(screen.getByText(/3 rows/)).toBeInTheDocument();
		expect(screen.getByText(/2 rows dropped as zero bookings/)).toBeInTheDocument();
		expect(screen.getByText(/the statement payment was not emitted/)).toBeInTheDocument();
		expect(screen.getByText(/−842\.01\s+EUR on/)).toBeInTheDocument();
		expect(screen.getByText(/Mar 3.*Mar 29/)).toBeInTheDocument();
	});

	it('links a duplicate to itself and to the row it duplicates, on the statement', () => {
		summarise({
			account_id: 7,
			stats: {
				inserted: 1,
				skipped_by_identity: 0,
				inserted_as_duplicates: [{ id: 91, duplicate_of: 40 }],
				importer: {},
				unexplained_difference: { before: null, after: null },
				since_zero: []
			}
		});
		expect(screen.getByRole('link', { name: 'Row #91' })).toHaveAttribute(
			'href',
			'/accounts/7?source=91'
		);
		expect(screen.getByRole('link', { name: '#40' })).toHaveAttribute(
			'href',
			'/accounts/7?source=40'
		);
	});

	it('leaves the new duplicate unlinked in a dry run, which rolled it back', () => {
		summarise(
			{
				stats: {
					inserted: 1,
					skipped_by_identity: 0,
					inserted_as_duplicates: [{ id: 91, duplicate_of: 40 }],
					importer: {},
					unexplained_difference: { before: null, after: null },
					since_zero: []
				}
			},
			{ dryRun: true }
		);
		expect(screen.queryByRole('link', { name: 'Row #91' })).toBeNull();
		expect(screen.getByRole('link', { name: '#40' })).toBeInTheDocument();
		expect(screen.getByText('Would insert')).toBeInTheDocument();
	});

	it('names the reported records behind a difference that is not zero', () => {
		summarise({
			stats: {
				inserted: 1,
				skipped_by_identity: 0,
				inserted_as_duplicates: [],
				importer: {},
				unexplained_difference: { before: 0, after: 1250 },
				since_zero: [4, 9]
			}
		});
		expect(screen.getByText(/After: \+12\.50\s+EUR/)).toBeInTheDocument();
		expect(screen.getByRole('link', { name: '2 reported records' })).toHaveAttribute(
			'href',
			'/accounts/7'
		);
	});

	it('shows a failed run as its error only, quietly, with no next step', () => {
		render(RunSummary, {
			props: {
				run: run({
					status: 'failed',
					error_text: 'ParseFailed: no header row found',
					retryable: false,
					instance_id: 4,
					account_id: 7,
					stats: {}
				}),
				currency: 'EUR'
			}
		});
		expect(screen.getByText('ParseFailed: no header row found')).toBeInTheDocument();
		expect(screen.queryByRole('dialog')).toBeNull();
		expect(screen.queryByText(/then upload again/)).toBeNull();
		expect(screen.queryByRole('link')).toBeNull();
	});

	it('reads a dry run in the same shape', () => {
		const asRun = dryRunAsRun(upload(), 7);
		render(RunSummary, { props: { run: asRun, currency: 'EUR', dryRun: true } });
		expect(screen.getByText('3 rows')).toBeInTheDocument();
	});
});
