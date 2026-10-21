import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import Segmented from './segmented.svelte';

const OPTIONS = [
	{ value: 'a', label: 'Alpha' },
	{ value: 'b', label: 'Beta' }
];

describe('Segmented', () => {
	it('is one 32px bordered box; the chosen segment is filled primary', () => {
		render(Segmented, {
			props: { label: 'Pick', options: OPTIONS, value: 'a', onchange: vi.fn() }
		});
		const group = screen.getByRole('group', { name: 'Pick' });
		expect(group).toHaveClass('h-8', 'border', 'divide-x');
		const alpha = screen.getByRole('button', { name: 'Alpha' });
		expect(alpha).toHaveAttribute('aria-pressed', 'true');
		expect(alpha).toHaveClass('bg-primary', 'text-primary-foreground');
		const beta = screen.getByRole('button', { name: 'Beta' });
		expect(beta).toHaveAttribute('aria-pressed', 'false');
		expect(beta).not.toHaveClass('bg-primary');
	});

	it('reports the segment pressed', async () => {
		const onchange = vi.fn();
		render(Segmented, { props: { label: 'Pick', options: OPTIONS, value: 'a', onchange } });
		await fireEvent.click(screen.getByRole('button', { name: 'Beta' }));
		expect(onchange).toHaveBeenCalledWith('b');
	});

	it('as radios, is a radiogroup of radios', () => {
		render(Segmented, {
			props: { label: 'Pick', role: 'radio', options: OPTIONS, value: 'b', onchange: vi.fn() }
		});
		expect(screen.getByRole('radiogroup', { name: 'Pick' })).toBeInTheDocument();
		expect(screen.getByRole('radio', { name: 'Beta' })).toBeChecked();
		expect(screen.getByRole('radio', { name: 'Alpha' })).not.toBeChecked();
	});

	it('disables a segment', () => {
		render(Segmented, {
			props: {
				label: 'Pick',
				options: [OPTIONS[0], { ...OPTIONS[1], disabled: true, reason: 'Not now' }],
				value: 'a',
				onchange: vi.fn()
			}
		});
		expect(screen.getByRole('button', { name: 'Beta' })).toBeDisabled();
	});
});
