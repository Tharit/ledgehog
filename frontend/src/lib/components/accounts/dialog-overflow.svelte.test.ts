// Long content must not push a dialog past the viewport: the body scrolls, the header and the
// buttons stay in view, and a row's text shrinks instead of widening the dialog. jsdom has no layout,
// so this asserts the structure and classes that make it so.
import { render, screen, within } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import { provenance } from '#lib/accounts/fixtures.js';
import { RevertFlow } from '#lib/accounts/revert-flow.svelte.js';
import type { ImportRun } from '#lib/accounts/runs.js';
import { entry } from '#lib/ledger/fixtures.js';
import ConsequenceRow from './consequence-row.svelte';
import RevertRunDialog from './revert-run-dialog.svelte';
import RowDetailDialog from './row-detail-dialog.svelte';

function structure(dialog: HTMLElement) {
	const body = dialog.querySelector<HTMLElement>('[data-slot="dialog-body"]')!;
	const footer = dialog.querySelector<HTMLElement>('[data-slot="dialog-footer"]')!;
	return { body, footer };
}

describe('dialogs with long content', () => {
	it('an action dialog scrolls its body and keeps its footer outside the scroll area', async () => {
		const flow = new RevertFlow();
		flow.status = 'ready';
		flow.preview = {
			run_id: 5,
			removed_entry_ids: Array.from({ length: 400 }, (_, i) => i),
			partner_entry_ids: [],
			freed_document_ids: [],
			repointed_source_ids: [],
			cleared_duplicate_ids: [],
			derived_changes: [],
			versions: {},
			settle: null
		};
		render(RevertRunDialog, {
			props: {
				open: true,
				run: {
					id: 5,
					stats: { inserted: 400 },
					started_at: '2026-10-11T08:00:00Z'
				} as unknown as ImportRun,
				label: 'Giro file',
				flow,
				onclose: () => {},
				onreverted: () => {}
			}
		});
		const dialog = await screen.findByRole('dialog');
		const { body, footer } = structure(dialog);

		expect(dialog.className).toMatch(/max-h-\[calc\(100dvh-2rem\)\]/);
		expect(dialog.className).toMatch(/\bflex-col\b/);
		expect(body.className).toMatch(/overflow-y-auto/);
		expect(body.className).toMatch(/min-h-0/);
		expect(body.contains(footer)).toBe(false);
		expect(within(footer).getByRole('button', { name: 'Revert run' })).toBeInTheDocument();
		expect(within(footer).getByRole('button', { name: 'Cancel' })).toBeInTheDocument();
	});

	it('the row detail scrolls its body and keeps its footer outside it', async () => {
		render(RowDetailDialog, {
			props: {
				open: true,
				status: 'ready',
				provenance: provenance({ purpose: 'x'.repeat(2000) }),
				onclose: () => {}
			}
		});
		const dialog = await screen.findByRole('dialog');
		const { body, footer } = structure(dialog);

		expect(dialog.className).toMatch(/max-h-\[calc\(100dvh-2rem\)\]/);
		expect(body.className).toMatch(/overflow-y-auto/);
		expect(body.contains(footer)).toBe(false);
	});

	it('a consequence row keeps its date and amount and lets its text shrink, full text as tooltip', () => {
		const long = 'A very long description of an entry '.repeat(20);
		render(ConsequenceRow, {
			props: { entry: entry({ description: long }), note: 'confirmed' }
		});
		const row = screen.getByText(long.trim(), { exact: false });

		expect(row.className).toMatch(/min-w-0/);
		expect(row.className).toMatch(/truncate/);
		expect(row).toHaveAttribute('title', long);
		const li = row.closest('li')!;
		expect(li.className).toMatch(/min-w-0/);
		const fixed = [...li.children].filter((c) => c !== row);
		expect(fixed.every((c) => /shrink-0/.test(c.className))).toBe(true);
	});
});
