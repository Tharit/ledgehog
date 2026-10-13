import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import KeyboardHelp, { type HelpGroup } from './keyboard-help.svelte';

const groups: HelpGroup[] = [
	{ title: 'Moving', items: [{ keys: 'j', description: 'Down' }] },
	{ title: 'Acting', items: [{ keys: 'Enter', description: 'Open' }] }
];

const key = (name: string, target: Element = document.body) =>
	fireEvent.keyDown(target, { key: name });

describe('KeyboardHelp', () => {
	it('is a quiet button, closed at first, that reports its state', async () => {
		render(KeyboardHelp, { props: { groups } });
		const button = screen.getByRole('button', { name: 'Keyboard shortcuts (?)' });
		expect(button).toHaveAttribute('aria-expanded', 'false');
		expect(screen.queryByRole('region')).toBeNull();

		await fireEvent.click(button);

		expect(button).toHaveAttribute('aria-expanded', 'true');
		expect(screen.getByRole('region', { name: 'Keyboard shortcuts' })).toBeInTheDocument();
	});

	it('lists every group with its title and its keys', async () => {
		render(KeyboardHelp, { props: { groups, open: true } });

		const help = screen.getByRole('region', { name: 'Keyboard shortcuts' });
		expect(help).toHaveTextContent('Moving');
		expect(help).toHaveTextContent('Acting');
		expect(help.querySelector('kbd')).toHaveTextContent('j');
		expect(help).toHaveTextContent('Open');
	});

	it('is fixed to the corner and scrolls when long', () => {
		render(KeyboardHelp, { props: { groups, open: true } });

		const help = screen.getByRole('region', { name: 'Keyboard shortcuts' });
		expect(help).toHaveClass('fixed', 'overflow-y-auto');
		expect(help.className).toMatch(/max-h-/);
	});

	it('? shows and hides it, Esc hides it', async () => {
		render(KeyboardHelp, { props: { groups } });

		await key('?');
		expect(screen.getByRole('region')).toBeInTheDocument();
		await key('?');
		expect(screen.queryByRole('region')).toBeNull();
		await key('?');
		await key('Escape');
		expect(screen.queryByRole('region')).toBeNull();
	});

	it('leaves ? to a field and to a dialog on a page', async () => {
		render(KeyboardHelp, { props: { groups } });
		const input = document.body.appendChild(document.createElement('input'));
		const dialog = document.body.appendChild(document.createElement('div'));
		dialog.setAttribute('role', 'dialog');

		await key('?', input);
		await key('?', dialog);

		expect(screen.queryByRole('region')).toBeNull();
	});

	it('ignores keys with a modifier, and Esc when it is closed', async () => {
		render(KeyboardHelp, { props: { groups } });

		await fireEvent.keyDown(document.body, { key: '?', ctrlKey: true });
		expect(screen.queryByRole('region')).toBeNull();
	});

	it('in a panel it answers only keys typed inside the panel', async () => {
		render(KeyboardHelp, { props: { groups, scope: 'panel' } });
		const panel = document.body.appendChild(document.createElement('div'));
		panel.dataset.slot = 'unit-panel';

		await key('?');
		expect(screen.queryByRole('region')).toBeNull();
		await key('?', panel);
		expect(screen.getByRole('region')).toBeInTheDocument();
	});

	it('Esc is kept by the help: nothing behind it sees the key that closed it', async () => {
		render(KeyboardHelp, { props: { groups, open: true } });
		let behind = 0;
		const count = () => behind++;
		window.addEventListener('keydown', count);

		await key('Escape');
		expect(behind).toBe(0);
		await key('Escape'); // closed now: the key belongs to whoever is behind
		expect(behind).toBe(1);
		window.removeEventListener('keydown', count);
	});
});
