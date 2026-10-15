import { CalendarDate, parseDate, type DateValue } from '@internationalized/date';
import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import { Calendar } from './index.js';

const day = (iso: string) =>
	document.querySelector(`[data-bits-day][data-value="${iso}"]`) as HTMLElement;

describe('Calendar (single day)', () => {
	it('opens on the month of the value and marks the value selected', () => {
		render(Calendar, { props: { value: parseDate('2026-10-09'), locale: 'en' } });

		expect(screen.getByRole('heading')).toHaveTextContent('October 2026');
		expect(day('2026-10-09')).toHaveAttribute('data-selected');
		expect(day('2026-10-10')).not.toHaveAttribute('data-selected');
	});

	it('reports the day clicked, and keeps it when it is clicked again', async () => {
		const onValueChange = vi.fn<(value: DateValue | undefined) => void>();
		render(Calendar, {
			props: { value: parseDate('2026-10-09'), locale: 'en', onValueChange }
		});

		await fireEvent.click(day('2026-10-14'));
		expect(onValueChange.mock.calls.at(-1)?.[0]?.toString()).toBe('2026-10-14');
		await fireEvent.click(day('2026-10-09'));

		expect(onValueChange.mock.calls.every(([v]) => v !== undefined)).toBe(true);
	});

	it('starts the week as the locale says', () => {
		render(Calendar, { props: { value: new CalendarDate(2026, 10, 9), locale: 'de' } });

		expect(screen.getAllByRole('columnheader')[0]).toHaveTextContent('Mo');
	});

	it('moves to the next month with the nav button', async () => {
		render(Calendar, { props: { value: parseDate('2026-10-09'), locale: 'en' } });

		await fireEvent.click(screen.getByRole('button', { name: /next/i }));

		expect(screen.getByRole('heading')).toHaveTextContent('November 2026');
	});
});
