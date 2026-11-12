import { render, screen } from '@testing-library/svelte';
import { createRawSnippet } from 'svelte';
import { describe, expect, it } from 'vitest';
import Clock from '@lucide/svelte/icons/clock';
import CardTitle from './card-title.svelte';
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
	it('is one full-width row with a muted label and an action at the right', () => {
		const { container } = render(SubgroupRow, { props: { label: 'USD', action: text('Add') } });
		const row = container.firstElementChild!;

		expect(row).toHaveAttribute('role', 'row');
		expect(row).not.toHaveClass('bg-muted');
		expect(row.querySelectorAll('[role="gridcell"]')).toHaveLength(1);
		expect(screen.getByText('USD')).toHaveClass('text-xs', 'font-medium', 'text-muted-foreground');
		expect(screen.getByRole('button', { name: 'Add' })).toBeInTheDocument();
	});
});
