import { fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { emptyDocumentFilter } from '#lib/documents/filter.js';
import type { DocumentFilter } from '#lib/types/domain.js';
import DocumentsFilterBar from './documents-filter-bar.svelte';

function bar(filter: Partial<DocumentFilter> = {}) {
	const onchange = vi.fn();
	const view = render(DocumentsFilterBar, {
		props: {
			filter: { ...emptyDocumentFilter(), ...filter },
			providers: ['amazon', 'paypal'],
			currencies: ['EUR'],
			today: '2026-10-11',
			baseCurrency: 'EUR',
			onchange
		}
	});
	return { onchange, ...view };
}

beforeEach(() => {
	vi.useFakeTimers();
	// jsdom has no ResizeObserver, which the popover's positioning looks for
	vi.stubGlobal(
		'ResizeObserver',
		class {
			observe() {}
			unobserve() {}
			disconnect() {}
		}
	);
});

afterEach(() => {
	vi.useRealTimers();
	vi.unstubAllGlobals();
});

describe('DocumentsFilterBar', () => {
	it('shows the dimension names while nothing is filtered', () => {
		bar();
		for (const name of [
			'All providers',
			'Any date',
			'Amount',
			'Any link state',
			'Any charge state'
		]) {
			expect(screen.getByRole('button', { name })).toBeInTheDocument();
		}
		expect(screen.queryByRole('button', { name: 'Clear' })).toBeNull();
	});

	it('shows what an active chip filters by', () => {
		bar({
			provider: ['amazon'],
			from: '2026-10-01',
			to: '2026-10-11',
			linked: false,
			fully_charged: false,
			amount_min: 5000,
			currency: 'EUR'
		});
		expect(screen.getByRole('button', { name: 'amazon' })).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Oct 1 – Oct 11' })).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Not linked' })).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Not fully charged' })).toBeInTheDocument();
		expect(screen.getByRole('button', { name: '≥ 50.00 EUR' })).toBeInTheDocument();
	});

	it('picks providers from the list it is given', async () => {
		const { onchange } = bar();
		await fireEvent.click(screen.getByRole('button', { name: 'All providers' }));
		await fireEvent.click(await screen.findByRole('checkbox', { name: 'paypal' }));
		expect(onchange).toHaveBeenCalledWith({ ...emptyDocumentFilter(), provider: ['paypal'] });
	});

	it('filters to documents that are not linked, and back to any', async () => {
		const { onchange, rerender } = bar();
		await fireEvent.click(screen.getByRole('button', { name: 'Any link state' }));
		await fireEvent.click(await screen.findByRole('radio', { name: 'Not linked' }));
		expect(onchange).toHaveBeenLastCalledWith({ ...emptyDocumentFilter(), linked: false });

		await rerender({ filter: { ...emptyDocumentFilter(), linked: false } });
		await fireEvent.click(screen.getByRole('button', { name: 'Not linked' }));
		await fireEvent.click(await screen.findByRole('radio', { name: 'Any' }));
		expect(onchange).toHaveBeenLastCalledWith(emptyDocumentFilter());
	});

	it('filters to documents that are not fully charged, and back to any', async () => {
		const { onchange, rerender } = bar();
		await fireEvent.click(screen.getByRole('button', { name: 'Any charge state' }));
		await fireEvent.click(await screen.findByRole('radio', { name: 'Not fully charged' }));
		expect(onchange).toHaveBeenLastCalledWith({ ...emptyDocumentFilter(), fully_charged: false });

		await rerender({ filter: { ...emptyDocumentFilter(), fully_charged: false } });
		await fireEvent.click(screen.getByRole('button', { name: 'Not fully charged' }));
		await fireEvent.click(await screen.findByRole('radio', { name: 'Any' }));
		expect(onchange).toHaveBeenLastCalledWith(emptyDocumentFilter());
	});

	it('offers an amount range without a direction', async () => {
		bar();
		await fireEvent.click(screen.getByRole('button', { name: 'Amount' }));
		await screen.findByLabelText('Minimum amount');
		expect(screen.queryByRole('radio', { name: 'Out' })).toBeNull();
	});

	it('sends the text after a pause and at once on Enter, trimmed', async () => {
		const { onchange } = bar();
		const box = screen.getByRole('textbox', { name: 'Filter documents by text' });

		await fireEvent.input(box, { target: { value: 'rewe' } });
		vi.advanceTimersByTime(249);
		expect(onchange).not.toHaveBeenCalled();
		vi.advanceTimersByTime(1);
		expect(onchange).toHaveBeenCalledWith({ ...emptyDocumentFilter(), q: 'rewe' });

		await fireEvent.input(box, { target: { value: ' order ' } });
		await fireEvent.keyDown(box, { key: 'Enter' });
		expect(onchange).toHaveBeenLastCalledWith({ ...emptyDocumentFilter(), q: 'order' });
	});

	it('clears everything with Clear', async () => {
		const { onchange } = bar({ provider: ['amazon'], q: 'x' });
		await fireEvent.click(screen.getByRole('button', { name: 'Clear' }));
		expect(onchange).toHaveBeenCalledWith(emptyDocumentFilter());
	});
});
