import { fireEvent, render, screen } from '@testing-library/svelte';
import { createRawSnippet } from 'svelte';
import { describe, expect, it, vi } from 'vitest';
import ErrorState from './error-state.svelte';
import Notice from './notice.svelte';

const text = createRawSnippet(() => ({
	render: () => '<span>Derived values may be stale.</span>'
}));

describe('Notice', () => {
	it('is a quiet status line by default', () => {
		render(Notice, { props: { children: text } });

		expect(screen.getByRole('status')).toHaveTextContent('Derived values may be stale.');
	});

	it('can be an alert', () => {
		render(Notice, { props: { role: 'alert', children: text } });

		expect(screen.getByRole('alert')).toBeInTheDocument();
	});
});

describe('ErrorState', () => {
	it('shows the title and the message', () => {
		render(ErrorState, { props: { title: 'No luck', message: 'The server is down.' } });

		expect(screen.getByRole('alert')).toHaveTextContent('No luck');
		expect(screen.getByRole('alert')).toHaveTextContent('The server is down.');
	});

	it('offers a retry only when it can retry', async () => {
		const onretry = vi.fn();
		const { unmount } = render(ErrorState, { props: { message: 'Down.', onretry } });

		await fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
		expect(onretry).toHaveBeenCalledOnce();

		unmount();
		render(ErrorState, { props: { message: 'Down.' } });
		expect(screen.queryByRole('button')).not.toBeInTheDocument();
	});
});
