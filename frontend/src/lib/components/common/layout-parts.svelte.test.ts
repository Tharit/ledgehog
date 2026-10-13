import { fireEvent, render, screen } from '@testing-library/svelte';
import { createRawSnippet } from 'svelte';
import { describe, expect, it, vi } from 'vitest';
import EmptyState from './empty-state.svelte';
import Field from './field.svelte';
import NoticeLine from './notice-line.svelte';
import Notice from './notice.svelte';
import PageHeader from './page-header.svelte';

const text = (label: string) => createRawSnippet(() => ({ render: () => `<span>${label}</span>` }));
const control = createRawSnippet<
	[{ id: string; 'aria-describedby': string | undefined; 'aria-invalid': boolean }]
>((field) => ({
	render: () =>
		`<input id="${field().id}" aria-invalid="${field()['aria-invalid']}" ${
			field()['aria-describedby'] ? `aria-describedby="${field()['aria-describedby']}"` : ''
		} />`
}));

describe('Field', () => {
	it('labels its control', () => {
		render(Field, { props: { label: 'Name', children: control } });

		expect(screen.getByLabelText('Name')).toBeInTheDocument();
	});

	it('describes the control by its hint, and by its error when there is one', () => {
		render(Field, {
			props: { label: 'Note', hint: 'Optional.', error: 'Too long.', children: control }
		});

		const input = screen.getByLabelText('Note');
		const described = (input.getAttribute('aria-describedby') ?? '').split(' ');
		expect(described).toHaveLength(2);
		expect(document.getElementById(described[0])).toHaveTextContent('Optional.');
		expect(document.getElementById(described[1])).toHaveTextContent('Too long.');
		expect(input).toHaveAttribute('aria-invalid', 'true');
	});

	it('says an error as an alert in the destructive colour, under the field', () => {
		render(Field, { props: { label: 'Name', error: 'Taken.', children: control } });

		const alert = screen.getByRole('alert');
		expect(alert).toHaveTextContent('Taken.');
		expect(alert).toHaveClass('text-destructive');
	});

	it('has no alert and is valid without an error', () => {
		render(Field, { props: { label: 'Name', children: control } });

		expect(screen.queryByRole('alert')).toBeNull();
		expect(screen.getByLabelText('Name')).toHaveAttribute('aria-invalid', 'false');
	});

	it('is a labelled group for radio choices', () => {
		render(Field, {
			props: {
				label: 'Kind',
				group: true,
				children: createRawSnippet(() => ({
					render: () => '<input type="radio" aria-label="Income" />'
				}))
			}
		});

		expect(screen.getByRole('group', { name: 'Kind' })).toBeInTheDocument();
	});
});

describe('EmptyState', () => {
	it('says what is missing and the next step, with the add action', async () => {
		const onaction = vi.fn();
		render(EmptyState, {
			props: {
				title: 'No payees yet',
				actionLabel: 'Add payee',
				onaction,
				children: text('Add one when there is a merchant you want to follow.')
			}
		});

		expect(screen.getByRole('heading', { name: 'No payees yet' })).toBeInTheDocument();
		expect(
			screen.getByText('Add one when there is a merchant you want to follow.')
		).toBeInTheDocument();
		await fireEvent.click(screen.getByRole('button', { name: 'Add payee' }));
		expect(onaction).toHaveBeenCalledOnce();
		expect(screen.getByRole('button', { name: 'Add payee' })).toHaveClass('h-8');
	});

	it('has no button when the page has no add action', () => {
		render(EmptyState, { props: { title: 'Nothing here', children: text('Wait.') } });

		expect(screen.queryByRole('button')).toBeNull();
	});
});

describe('PageHeader', () => {
	it('has a title, a description and the primary action at the standard size', async () => {
		const onaction = vi.fn();
		render(PageHeader, {
			props: { title: 'Payees', description: 'A curated list.', actionLabel: 'Add payee', onaction }
		});

		expect(screen.getByRole('heading', { level: 2, name: 'Payees' })).toBeInTheDocument();
		expect(screen.getByText('A curated list.')).toBeInTheDocument();
		const add = screen.getByRole('button', { name: 'Add payee' });
		expect(add).toHaveClass('h-8');
		await fireEvent.click(add);
		expect(onaction).toHaveBeenCalledOnce();
	});

	it('is an h1 on a route of its own', () => {
		render(PageHeader, { props: { title: 'Ledger', level: 1 } });

		expect(screen.getByRole('heading', { level: 1, name: 'Ledger' })).toBeInTheDocument();
	});

	it('has no action when the page has no add, and can lead to a route', () => {
		const { unmount } = render(PageHeader, { props: { title: 'Dashboard' } });
		expect(screen.queryByRole('button')).toBeNull();
		unmount();

		render(PageHeader, {
			props: { title: 'Rules', actionLabel: 'Add rule', actionHref: '/settings/rules/new' }
		});
		expect(screen.getByRole('link', { name: 'Add rule' })).toHaveAttribute(
			'href',
			'/settings/rules/new'
		);
	});

	it('can disable the action', () => {
		render(PageHeader, {
			props: { title: 'Payees', actionLabel: 'Add payee', actionDisabled: true }
		});

		expect(screen.getByRole('button', { name: 'Add payee' })).toBeDisabled();
	});
});

describe('NoticeLine', () => {
	it('reserves its line when there is nothing to say', () => {
		render(NoticeLine, { props: { notice: null } });

		expect(document.querySelector('[data-slot="notice-line"]')).toHaveClass('min-h-5');
		expect(screen.queryByRole('status')).toBeNull();
		expect(screen.queryByRole('alert')).toBeNull();
	});

	it('says a success as a status and a failure as an alert', () => {
		const { unmount } = render(NoticeLine, {
			props: { notice: { text: 'Deleted Food.', error: false } }
		});
		expect(screen.getByRole('status')).toHaveTextContent('Deleted Food.');
		unmount();
		render(NoticeLine, { props: { notice: { text: 'Could not move.', error: true } } });
		expect(screen.getByRole('alert')).toHaveTextContent('Could not move.');
	});

	it('carries an optional action on the same line', async () => {
		const onclick = vi.fn();
		const action = createRawSnippet(() => ({
			render: () => '<button type="button">Try again</button>'
		}));
		render(NoticeLine, {
			props: { notice: { text: 'Could not load more.', error: true }, action }
		});

		await fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
		expect(screen.getByRole('alert')).toContainElement(
			screen.getByRole('button', { name: 'Try again' })
		);
		expect(onclick).not.toHaveBeenCalled();
	});
});

describe('Notice action slot', () => {
	it('is optional', () => {
		render(Notice, { props: { children: text('Quiet.') } });

		expect(screen.queryByRole('button')).toBeNull();
	});
});
