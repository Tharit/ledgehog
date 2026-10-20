import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import { line } from '#lib/reports/fixtures.js';
import LineFigure from './line-figure.svelte';

const usd = { amount: { amount: 12000, currency: 'USD' }, count: 2 };

describe('LineFigure', () => {
	it('writes the total signed, with the base currency code', () => {
		render(LineFigure, { props: { line: line(-124000) } });

		expect(screen.getByText('−1,240.00 EUR')).toBeInTheDocument();
		expect(screen.queryByText(/unvalued/)).toBeNull();
	});

	it('writes a positive total with its plus unless it is told not to', () => {
		const { unmount } = render(LineFigure, { props: { line: line(50000) } });
		expect(screen.getByText('+500.00 EUR')).toBeInTheDocument();
		unmount();

		render(LineFigure, { props: { line: line(50000), showPlus: false } });
		expect(screen.getByText('500.00 EUR')).toBeInTheDocument();
	});

	it('writes zero as zero', () => {
		render(LineFigure, { props: { line: line(0) } });

		expect(screen.getByText('0.00 EUR')).toBeInTheDocument();
	});

	it('says "unvalued" when entries exist and none could be valued, never 0.00', () => {
		render(LineFigure, { props: { line: line(null, { count: 2, unvalued: [usd] }) } });

		const word = screen.getByText('unvalued');
		expect(word).toHaveAttribute('title', expect.stringContaining('120.00 USD (2 entries)'));
		expect(screen.queryByText(/0\.00/)).toBeNull();
	});

	it('shows the total and "+ n unvalued" with the currencies in its tooltip', () => {
		render(LineFigure, {
			props: { line: line(-10000, { count: 3, unvalued: [usd] }) }
		});

		expect(screen.getByText('−100.00 EUR')).toBeInTheDocument();
		expect(screen.getByText('+ 2 unvalued')).toHaveAttribute(
			'title',
			'No usable exchange rate for 120.00 USD (2 entries).'
		);
	});
});
