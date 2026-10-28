import { render } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import { categoryStack } from '#lib/reports/charts.js';
import { overTimeCategories, reportLookups } from '#lib/reports/trend-fixtures.js';
import CategoryStackChart from './category-stack-chart.svelte';

const { categories } = reportLookups();

describe('CategoryStackChart', () => {
	it('draws each legend entry as its category’s lead tile, "Other" as circle-ellipsis', () => {
		const { series, rows } = categoryStack(overTimeCategories(), categories);
		const { container } = render(CategoryStackChart, {
			props: { series, rows, currency: 'EUR' }
		});
		const legend = container.querySelector('[data-slot="chart-legend"]')!;
		const items = [...legend.querySelectorAll('li')];
		expect(items).toHaveLength(series.length);
		for (const item of items) expect(item.querySelector('span[style] svg')).toBeInTheDocument();
		expect(items.at(-1)!.querySelector('.lucide-circle-ellipsis')).toBeInTheDocument();
		expect(items[0].querySelector('span[style]')!.getAttribute('style')).toContain('--dim-slate');
		expect(legend.querySelector('.rounded-\\[2px\\]')).toBeNull();
	});
});
