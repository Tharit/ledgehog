import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import { catalogEntry, instance } from '#lib/importers/fixtures.js';
import { account } from '#lib/ledger/fixtures.js';
import { buildLookups } from '#lib/ledger/lookups.js';
import type { ImporterInstance } from '#lib/types/domain.js';
import ImporterList from './importer-list.svelte';

const lookups = buildLookups({ accounts: [account({ id: 7, name: 'Main giro' })] });

function list(instances: ImporterInstance[], over: Record<string, unknown> = {}) {
	const fn = {
		onedit: vi.fn(),
		onlink: vi.fn(),
		onrefresh: vi.fn(),
		ontoggle: vi.fn(),
		onreset: vi.fn(),
		ondelete: vi.fn(),
		onadd: vi.fn()
	};
	render(ImporterList, {
		props: {
			instances,
			catalog: [catalogEntry(), catalogEntry({ name: 'fints', kind: 'fetch' })],
			status: 'ready' as const,
			lookups,
			...fn,
			...over
		}
	});
	return fn;
}

async function openMenu(name: string) {
	await fireEvent.keyDown(screen.getByRole('button', { name: `More actions for ${name}` }), {
		key: 'Enter'
	});
	return screen.findByRole('menu');
}

describe('ImporterList', () => {
	it('shows the label as a link, the importer, its accounts and when it last ran', () => {
		list([
			instance({
				id: 1,
				label: 'Giro',
				accounts: [{ account_id: 7, external_ref: 'acct-7' }]
			}),
			instance({ id: 2, label: 'Old card', disabled: true })
		]);

		expect(screen.getByRole('link', { name: 'Giro' })).toHaveAttribute(
			'href',
			'/settings/importers/1'
		);
		expect(screen.getByRole('link', { name: 'Main giro' })).toHaveAttribute('href', '/accounts/7');
		expect(screen.getAllByText('never run')).toHaveLength(2);
		expect(screen.getByText('disabled')).toBeInTheDocument();
		expect(screen.getByText('no accounts linked')).toBeInTheDocument();
	});

	it('has the settings-row actions: Edit and Link account, then the menu', async () => {
		const fn = list([instance({ id: 1, label: 'Giro' })]);

		await fireEvent.click(screen.getByRole('button', { name: 'Edit Giro' }));
		await fireEvent.click(screen.getByRole('button', { name: 'Link an account to Giro' }));
		expect(fn.onedit).toHaveBeenCalledOnce();
		expect(fn.onlink).toHaveBeenCalledOnce();

		const menu = await openMenu('Giro');
		expect(
			within(menu)
				.getAllByRole('menuitem')
				.map((i) => i.textContent?.trim())
		).toEqual(['Disable', 'Delete…']);
	});

	it('swaps "Link account" for "Refresh accounts" on an instance of a fetch importer', async () => {
		const fn = list([
			instance({ id: 1, label: 'Giro' }),
			instance({ id: 3, label: 'Bank', importer: 'fints' })
		]);

		expect(screen.getByRole('button', { name: 'Link an account to Giro' })).toBeInTheDocument();
		expect(screen.queryByRole('button', { name: 'Link an account to Bank' })).toBeNull();
		await fireEvent.click(screen.getByRole('button', { name: 'Refresh the accounts of Bank' }));

		expect(fn.onrefresh).toHaveBeenCalledOnce();
		expect(fn.onrefresh.mock.calls[0][0]).toMatchObject({ id: 3 });
		expect(fn.onlink).not.toHaveBeenCalled();
	});

	it('offers Enable on a disabled instance and Reset… only for an importer that keeps state', async () => {
		list([instance({ id: 3, label: 'Bank', importer: 'fints', disabled: true })]);

		const menu = await openMenu('Bank');

		expect(
			within(menu)
				.getAllByRole('menuitem')
				.map((i) => i.textContent?.trim())
		).toEqual(['Enable', 'Reset…', 'Delete…']);
	});

	it('disables Delete… on an instance that has run, with the reason as its tooltip', async () => {
		const fn = list([instance({ id: 1, label: 'Giro', last_run_at: '2026-04-02T10:00:00Z' })]);

		const menu = await openMenu('Giro');
		const item = within(menu).getByRole('menuitem', { name: 'Delete…' });

		expect(item).toHaveAttribute('aria-disabled', 'true');
		expect(item).toHaveAttribute('title', 'has runs; disable it instead');
		await fireEvent.click(item);
		expect(fn.ondelete).not.toHaveBeenCalled();
	});

	it('says what is missing and offers Add importer when there is none', async () => {
		const fn = list([]);

		expect(screen.getByText('No importers yet')).toBeInTheDocument();
		await fireEvent.click(screen.getByRole('button', { name: 'Add importer' }));
		expect(fn.onadd).toHaveBeenCalledOnce();
	});

	it('shows the failure with Try again', async () => {
		const fn = { onretry: vi.fn() };
		list([], { status: 'error', failure: 'The server could not be reached.', ...fn });

		await fireEvent.click(screen.getByRole('button', { name: 'Try again' }));

		expect(fn.onretry).toHaveBeenCalledOnce();
	});
});
