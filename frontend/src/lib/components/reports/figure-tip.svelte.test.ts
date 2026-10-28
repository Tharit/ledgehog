import { render } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import FigureTip from './figure-tip.svelte';

describe('FigureTip', () => {
	it('draws a measure row as a stone tile, whatever its chart line looks like', () => {
		const { container } = render(FigureTip, {
			props: {
				tip: {
					title: 'Aug 2026',
					rows: [
						{ label: 'Income', value: '€1', icon: 'hand-coins', color: 'stone' },
						{ label: 'Expense', value: '€2', icon: 'receipt', color: 'stone' }
					]
				}
			}
		});
		const tiles = container.querySelectorAll('[data-slot="figure-tooltip"] span[style]');
		expect(tiles).toHaveLength(2);
		for (const tile of tiles) {
			expect(tile.getAttribute('style')).toContain('--dim-stone');
			expect(tile.querySelector('svg')).toBeInTheDocument();
		}
		expect(container.querySelector('.lucide-hand-coins')).toBeInTheDocument();
		expect(container.querySelector('.lucide-receipt')).toBeInTheDocument();
	});

	it('draws "Other" as circle-ellipsis', () => {
		const { container } = render(FigureTip, {
			props: {
				tip: { rows: [{ label: 'Other', value: '€3', icon: 'circle-ellipsis', color: 'stone' }] }
			}
		});
		expect(container.querySelector('.lucide-circle-ellipsis')).toBeInTheDocument();
	});

	it('draws a row with no subject without a tile', () => {
		const { container } = render(FigureTip, {
			props: { tip: { rows: [{ label: 'Total', value: '€4' }] } }
		});
		expect(container.querySelector('svg')).toBeNull();
		expect(container).toHaveTextContent('Total');
	});
});
