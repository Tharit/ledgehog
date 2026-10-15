import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { formatDate, todayIso } from '#lib/format/index.js';
import DateField from './date-field.svelte';

const day = (iso: string) =>
	document.querySelector(`[data-bits-day][data-value="${iso}"]`) as HTMLElement | null;
const trigger = () => screen.getByRole('button', { name: 'Date' });

beforeEach(() => {
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

describe('DateField', () => {
	it('shows the date as the ledger writes dates, and today when given today', () => {
		const today = todayIso('UTC');
		render(DateField, { props: { value: today, label: 'Date' } });

		expect(trigger()).toHaveTextContent(formatDate(today));
	});

	it('opens a calendar on the value, chooses a day, sets the ISO value and closes', async () => {
		const onchange = vi.fn();
		render(DateField, { props: { value: '2026-10-09', label: 'Date', onchange } });

		await fireEvent.click(trigger());
		await waitFor(() => expect(day('2026-10-09')).toHaveAttribute('data-selected'));
		await fireEvent.click(day('2026-10-01') as HTMLElement);

		expect(onchange).toHaveBeenCalledWith('2026-10-01');
		expect(trigger()).toHaveTextContent(formatDate('2026-10-01'));
		await waitFor(() => expect(day('2026-10-01')).toBeNull());
	});

	it('closes on Escape without changing the date', async () => {
		const onchange = vi.fn();
		render(DateField, { props: { value: '2026-10-09', label: 'Date', onchange } });

		await fireEvent.click(trigger());
		await waitFor(() => expect(day('2026-10-09')).not.toBeNull());
		await fireEvent.keyDown(document.activeElement ?? document.body, { key: 'Escape' });

		await waitFor(() => expect(day('2026-10-09')).toBeNull());
		expect(onchange).not.toHaveBeenCalled();
		expect(trigger()).toHaveTextContent(formatDate('2026-10-09'));
	});

	it('cannot be opened when disabled', async () => {
		render(DateField, { props: { value: '2026-10-09', label: 'Date', disabled: true } });

		expect(trigger()).toBeDisabled();
	});
});
