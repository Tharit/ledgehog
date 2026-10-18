import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import type { SourceLine } from '#lib/accounts/sources.js';
import { account } from '#lib/ledger/fixtures.js';
import AccountSummary from './account-summary.svelte';

const file: SourceLine = {
	instanceId: 1,
	label: 'Giro export',
	importer: 'csv',
	kind: 'file',
	disabled: false
};
const fetcher: SourceLine = {
	instanceId: 2,
	label: 'Giro login',
	importer: 'testfetch',
	kind: 'fetch',
	disabled: false
};

function summary(sources: SourceLine[]) {
	const onfetch = vi.fn();
	render(AccountSummary, {
		props: {
			account: account({ id: 7 }),
			sources,
			today: '2026-10-18',
			onsetbalance: vi.fn(),
			onedit: vi.fn(),
			onclose: vi.fn(),
			onreopen: vi.fn(),
			ondelete: vi.fn(),
			onfetch
		}
	});
	return onfetch;
}

const line = (id: number) =>
	document.querySelector(`[data-source-instance="${id}"]`) as HTMLElement;

describe('AccountSummary: the sources', () => {
	it('offers "Upload file" on a file importer and "Fetch" on one that fetches', () => {
		summary([file, fetcher]);

		expect(within(line(1)).getByRole('link', { name: 'Upload file' })).toBeInTheDocument();
		expect(within(line(1)).queryByRole('button', { name: 'Fetch' })).toBeNull();
		expect(within(line(2)).getByRole('button', { name: 'Fetch' })).toBeInTheDocument();
		expect(within(line(2)).queryByRole('link', { name: 'Upload file' })).toBeNull();
	});

	it('asks for the fetch of the instance on its line', async () => {
		const onfetch = summary([fetcher]);

		await fireEvent.click(screen.getByRole('button', { name: 'Fetch' }));

		expect(onfetch).toHaveBeenCalledWith(2);
	});

	it('cannot fetch from a disabled instance', () => {
		summary([{ ...fetcher, disabled: true }]);

		expect(screen.getByRole('button', { name: 'Fetch' })).toBeDisabled();
	});
});
