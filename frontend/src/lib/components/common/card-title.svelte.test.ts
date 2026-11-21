import { render, screen } from '@testing-library/svelte';
import { createRawSnippet } from 'svelte';
import { describe, expect, it } from 'vitest';
import Clock from '@lucide/svelte/icons/clock';
import CardTitle from './card-title.svelte';
import BandRow from './band-row.svelte';
import SubgroupRow from './subgroup-row.svelte';

const text = (t: string) => createRawSnippet(() => ({ render: () => `<button>${t}</button>` }));

describe('CardTitle', () => {
	it('is a tinted heading row: glyph, title and count, actions at the right', () => {
		const { container } = render(CardTitle, {
			props: { id: 't', title: 'Waiting', count: '3', icon: Clock, actions: text('Act') }
		});
		const row = container.firstElementChild!;

		expect(row).toHaveClass('bg-muted');
		const heading = screen.getByRole('heading', { name: 'Waiting (3)' });
		expect(heading).toHaveAttribute('id', 't');
		expect(heading).toHaveClass('text-base', 'font-semibold');
		expect(heading.querySelector('svg')).toHaveAttribute('width', '16');
		expect(row.lastElementChild).toHaveTextContent('Act');
	});

	it('has no glyph, count or actions unless given', () => {
		const { container } = render(CardTitle, { props: { title: 'Closed' } });

		expect(container.querySelector('svg')).toBeNull();
		expect(container.querySelector('[data-slot="title-count"]')).toBeNull();
		expect(container.firstElementChild!.children).toHaveLength(1);
	});
});

describe('SubgroupRow', () => {
	it('is one full-width tinted row with a heading-sized label and an action at the right', () => {
		const { container } = render(SubgroupRow, { props: { label: 'USD', action: text('Add') } });
		const row = container.firstElementChild!;

		expect(row).toHaveAttribute('role', 'row');
		expect(row).toHaveClass('bg-muted');
		expect(row.querySelectorAll('[role="gridcell"]')).toHaveLength(1);
		expect(screen.getByText('USD')).toHaveClass('text-base', 'font-semibold', 'text-foreground');
		expect(screen.getByRole('button', { name: 'Add' })).toBeInTheDocument();
	});

	it('sticks beneath what is above it only when given a top', () => {
		const { container } = render(SubgroupRow, { props: { label: 'November 2026', top: '2rem' } });
		const row = container.firstElementChild as HTMLElement;

		expect(row).toHaveClass('sticky');
		expect(row.style.top).toBe('2rem');
	});
});

describe('BandRow', () => {
	it("is a lighter row with a muted label in the labels' size", () => {
		const { container } = render(BandRow, { props: { label: 'Tue, Nov 17' } });
		const row = container.firstElementChild!;

		expect(row).toHaveAttribute('role', 'row');
		expect(row).not.toHaveClass('sticky');
		expect(screen.getByText('Tue, Nov 17')).toHaveClass(
			'text-xs',
			'font-medium',
			'text-muted-foreground'
		);
	});

	it('sticks at the top it is given', () => {
		const { container } = render(BandRow, { props: { label: 'Tue, Nov 17', top: '4.25rem' } });
		const row = container.firstElementChild as HTMLElement;

		expect(row).toHaveClass('sticky');
		expect(row.style.top).toBe('4.25rem');
	});

	it('carries an action at the right and a line beneath, like a subgroup row', () => {
		render(BandRow, {
			props: {
				label: 'A transfer needs an account in GBP',
				action: text('Add account'),
				children: createRawSnippet(() => ({ render: () => '<p>Notice</p>' })),
				'data-group': 'GBP'
			}
		});

		const row = document.querySelector('[data-group="GBP"]')!;
		expect(row).toHaveAttribute('role', 'row');
		expect(row.querySelector('[data-slot="band-label"]')).toHaveTextContent(
			'A transfer needs an account in GBP'
		);
		expect(screen.getByRole('button', { name: 'Add account' })).toBeInTheDocument();
		expect(screen.getByText('Notice')).toBeInTheDocument();
	});
});
