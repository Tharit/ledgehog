import { render } from '@testing-library/svelte';
import { createRawSnippet } from 'svelte';
import { describe, expect, it } from 'vitest';
import Card from './card.svelte';

const body = createRawSnippet(() => ({ render: () => '<span>Inside</span>' }));

describe('Card', () => {
	it('is a padded card by default', () => {
		const { container } = render(Card, { props: { children: body } });
		const card = container.firstElementChild!;

		expect(card.tagName).toBe('DIV');
		expect(card).toHaveClass('rounded-xl', 'border', 'bg-card', 'shadow-card', 'p-5');
		expect(card).toHaveTextContent('Inside');
	});

	it('is flush without padding, and rounds its outer rows instead of clipping', () => {
		const { container } = render(Card, { props: { variant: 'flush', children: body } });
		const card = container.firstElementChild!;

		expect(card).toHaveClass('shadow-card');
		expect(card).not.toHaveClass('p-5');
		expect(card).not.toHaveClass('overflow-hidden');
	});

	it('takes its tag, merges its class and passes other attributes on', () => {
		const { container } = render(Card, {
			props: {
				element: 'section',
				class: 'flex gap-3 p-4',
				'aria-label': 'Totals',
				'data-slot': 'totals',
				children: body
			}
		});
		const card = container.firstElementChild!;

		expect(card.tagName).toBe('SECTION');
		expect(card).toHaveClass('flex', 'gap-3', 'p-4', 'rounded-xl');
		expect(card).not.toHaveClass('p-5');
		expect(card).toHaveAttribute('aria-label', 'Totals');
		expect(card).toHaveAttribute('data-slot', 'totals');
	});
});
