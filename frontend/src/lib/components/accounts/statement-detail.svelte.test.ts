import { fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { provenance, sourceRow } from '#lib/accounts/fixtures.js';
import Harness from './statement-detail.harness.svelte';

const api = vi.hoisted(() => ({ getProvenance: vi.fn() }));
vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	...api
}));

const items = [
	sourceRow({ id: 4, counterparty_name: 'Netflix' }),
	sourceRow({ id: 3, counterparty_name: 'REWE' })
];

beforeEach(() => {
	history.replaceState(null, '', '/accounts/1');
	api.getProvenance.mockReset();
	api.getProvenance.mockImplementation(async (id: number) => provenance({ id }));
});
afterEach(() => history.replaceState(null, '', '/'));

describe('opening a statement row', () => {
	it('opens its detail by click, without a reload, and writes ?source=', async () => {
		render(Harness, { props: { items } });
		expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

		await fireEvent.click(screen.getByText('REWE'));

		const dialog = await screen.findByRole('dialog');
		expect(within(dialog).getByText('Source transaction')).toBeInTheDocument();
		await waitFor(() => expect(api.getProvenance).toHaveBeenCalledWith(3, expect.anything()));
		expect(location.search).toBe('?source=3');
	});

	it('opens it with Enter and with p on the row under the cursor', async () => {
		render(Harness, { props: { items } });
		await fireEvent.keyDown(document.body, { key: 'ArrowDown' });
		await fireEvent.keyDown(document.body, { key: 'Enter' });
		await screen.findByRole('dialog');
		expect(location.search).toBe('?source=4');
		history.replaceState(null, '', '/accounts/1');
	});

	it('opens with p', async () => {
		render(Harness, { props: { items } });
		await fireEvent.keyDown(document.body, { key: 'ArrowDown' });
		await fireEvent.keyDown(document.body, { key: 'p' });
		await screen.findByRole('dialog');
		expect(location.search).toBe('?source=4');
	});

	it('gives focus back to the list without scrolling it into view when it closes', async () => {
		const focus = vi.spyOn(HTMLElement.prototype, 'focus');
		render(Harness, { props: { items } });
		await fireEvent.click(screen.getByText('REWE'));
		const dialog = await screen.findByRole('dialog');
		focus.mockClear();

		await fireEvent.click(within(dialog).getAllByRole('button', { name: 'Close' })[0]);
		await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());

		const grid = screen.getByRole('grid', { name: 'Statement rows' });
		const onGrid = focus.mock.contexts.flatMap((el, i) =>
			el === grid ? [focus.mock.calls[i][0]] : []
		);
		expect(onGrid.length).toBeGreaterThan(0);
		// every focus the list received on close is one that does not scroll
		expect(onGrid.every((options) => options?.preventScroll === true)).toBe(true);
		focus.mockRestore();
	});

	it('closes with Cancel-style Close and clears ?source=', async () => {
		render(Harness, { props: { items } });
		await fireEvent.click(screen.getByText('REWE'));
		const dialog = await screen.findByRole('dialog');
		await fireEvent.click(within(dialog).getAllByRole('button', { name: 'Close' })[0]);
		await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
		await waitFor(() => expect(location.search).toBe(''));
	});
});
