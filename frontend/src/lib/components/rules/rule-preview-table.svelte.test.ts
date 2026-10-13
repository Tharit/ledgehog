import { fireEvent, render, screen } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { account } from '#lib/ledger/fixtures.js';
import { buildLookups } from '#lib/ledger/lookups.js';
import { previewRow } from '#lib/rules/fixtures.js';
import { unitPanel } from '#lib/units/panel-instance.js';
import { activeUnitSource } from '#lib/units/sources.js';
import RulePreviewTable from './rule-preview-table.svelte';

vi.mock('#lib/units/panel-instance.js', () => ({ unitPanel: { open: vi.fn() } }));

const rows = [
	previewRow({ entry_id: 11, description: 'First' }),
	previewRow({
		entry_id: 12,
		description: 'Second',
		current_key: { pass: 'history', basis: { agree: 1, of: 1, since: '2026-03-01' } }
	}),
	previewRow({ entry_id: 13, description: 'Third' })
];

function table() {
	return render(RulePreviewTable, {
		props: {
			rows,
			columns: ['counterparty_name'],
			sets: 'category',
			lookups: buildLookups({ accounts: [account()] }),
			ruleName: () => undefined,
			label: 'Matches'
		}
	});
}

beforeEach(() => vi.mocked(unitPanel.open).mockClear());

describe('RulePreviewTable: rows open the review panel', () => {
	it('opens on a click, by entry id', async () => {
		table();

		await fireEvent.click(document.querySelector('[data-entry-id="12"]')!);

		expect(vi.mocked(unitPanel.open).mock.calls[0][0]).toBe(12);
	});

	it('opens on Enter when the row has focus, and rows are in the tab order', async () => {
		table();
		const row = document.querySelector('[data-entry-id="13"]') as HTMLElement;
		expect(row).toHaveAttribute('tabindex', '0');

		await fireEvent.keyDown(row, { key: 'Enter' });

		expect(vi.mocked(unitPanel.open).mock.calls[0][0]).toBe(13);
	});

	it('makes the table the source the panel steps through', async () => {
		table();
		await fireEvent.click(document.querySelector('[data-entry-id="12"]')!);

		const source = activeUnitSource();

		expect(source?.neighbour(12, 1)).toBe(13);
		expect(source?.neighbour(12, -1)).toBe(11);
		expect(source?.neighbour(13, 1)).toBeNull();
		expect(source?.neighbour(99, 1)).toBeNull();
	});

	it('writes the basis in the shared vocabulary, a proposal in italic', () => {
		table();

		const basis = screen.getByText('history: 1 of 1 since Mar 2026');

		expect(basis).toHaveClass('italic');
	});
});
