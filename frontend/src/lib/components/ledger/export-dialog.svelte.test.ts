import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import ExportDialog from './export-dialog.svelte';

describe('ExportDialog', () => {
	it('explains the export and downloads only on Download', async () => {
		const onconfirm = vi.fn();
		const onclose = vi.fn();
		render(ExportDialog, { props: { open: true, onclose, onconfirm } });

		const dialog = await screen.findByRole('dialog', { name: 'Export CSV' });
		expect(dialog).toHaveTextContent("matches the ledger's current filters");
		expect(onconfirm).not.toHaveBeenCalled();

		await fireEvent.click(within(dialog).getByRole('button', { name: 'Download' }));
		expect(onconfirm).toHaveBeenCalledOnce();
	});

	it('Cancel closes without downloading', async () => {
		const onconfirm = vi.fn();
		const onclose = vi.fn();
		render(ExportDialog, { props: { open: true, onclose, onconfirm } });

		const dialog = await screen.findByRole('dialog');
		await fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }));
		expect(onclose).toHaveBeenCalled();
		expect(onconfirm).not.toHaveBeenCalled();
	});
});
