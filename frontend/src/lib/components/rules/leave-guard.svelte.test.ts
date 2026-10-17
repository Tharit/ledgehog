import { fireEvent, render, screen } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import LeaveGuard from './leave-guard.svelte';

type Navigation = {
	cancel: () => void;
	to: { url: URL } | null;
	willUnload: boolean;
};

const nav = vi.hoisted(() => ({
	callback: null as null | ((navigation: Navigation) => void),
	goto: vi.fn()
}));

vi.mock('$app/navigation', () => ({
	beforeNavigate: (callback: (navigation: Navigation) => void) => {
		nav.callback = callback;
	},
	goto: nav.goto
}));

function navigate(to: string | null = 'http://localhost/ledger', willUnload = false) {
	const cancel = vi.fn();
	nav.callback!({ cancel, to: to === null ? null : { url: new URL(to) }, willUnload });
	return cancel;
}

beforeEach(() => {
	nav.callback = null;
	nav.goto.mockReset();
	nav.goto.mockResolvedValue(undefined);
});

describe('LeaveGuard', () => {
	it('lets a clean page go', () => {
		render(LeaveGuard, { props: { dirty: false } });

		const cancel = navigate();

		expect(cancel).not.toHaveBeenCalled();
		expect(screen.queryByText('Discard changes?')).toBeNull();
	});

	it('stops a page with changes and asks "Discard changes?"', async () => {
		render(LeaveGuard, { props: { dirty: true } });

		const cancel = navigate();

		expect(cancel).toHaveBeenCalledOnce();
		expect(await screen.findByText('Discard changes?')).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Discard' })).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Cancel' })).toBeInTheDocument();
	});

	it('names what the draft is', async () => {
		render(LeaveGuard, { props: { dirty: true, subject: 'this importer' } });

		navigate();

		expect(
			await screen.findByText('The changes to this importer have not been saved.')
		).toBeInTheDocument();
	});

	it('stays when the user cancels', async () => {
		render(LeaveGuard, { props: { dirty: true } });
		navigate();
		await screen.findByText('Discard changes?');

		await fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));

		expect(nav.goto).not.toHaveBeenCalled();
		expect(screen.queryByText('Discard changes?')).toBeNull();
	});

	it('goes where it was going, without asking again, when the user discards', async () => {
		render(LeaveGuard, { props: { dirty: true } });
		navigate('http://localhost/ledger?x=1');
		await screen.findByText('Discard changes?');
		let again: ReturnType<typeof vi.fn> | null = null;
		nav.goto.mockImplementation(async () => {
			again = navigate('http://localhost/ledger?x=1');
		});

		await fireEvent.click(screen.getByRole('button', { name: 'Discard' }));

		expect(String(nav.goto.mock.calls[0][0])).toBe('http://localhost/ledger?x=1');
		expect(again).not.toBeNull();
		expect(again!).not.toHaveBeenCalled();
	});

	it('hands closing the tab or an outside link to the browser’s own question', () => {
		render(LeaveGuard, { props: { dirty: true } });

		const cancel = navigate(null, true);

		expect(cancel).toHaveBeenCalledOnce();
		expect(screen.queryByText('Discard changes?')).toBeNull();
	});
});
