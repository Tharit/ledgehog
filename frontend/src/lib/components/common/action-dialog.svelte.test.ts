import { fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { createRawSnippet } from 'svelte';
import { describe, expect, it, vi } from 'vitest';
import ActionDialog from './action-dialog.svelte';

const field = createRawSnippet(() => ({
	render: () => '<input aria-label="Name" />'
}));
const consequences = createRawSnippet(() => ({
	render: () => '<p>Nothing uses Food.</p>'
}));

function open(props: Record<string, unknown> = {}) {
	const onclose = vi.fn();
	const onsubmit = vi.fn();
	render(ActionDialog, {
		props: { open: true, onclose, onsubmit, title: 'Add category', children: field, ...props }
	});
	return { onclose, onsubmit };
}

describe('ActionDialog: form dialog', () => {
	it('has the title, its fields, and Cancel before the verb', async () => {
		open({ verb: 'Add' });

		const dialog = await screen.findByRole('dialog', { name: 'Add category' });
		const buttons = within(dialog)
			.getAllByRole('button')
			.map((b) => b.textContent?.trim());
		expect(buttons.indexOf('Cancel')).toBeLessThan(buttons.indexOf('Add'));
		expect(within(dialog).getByLabelText('Name')).toBeInTheDocument();
	});

	it('submits from the verb button, which is the submit button of the form holding the fields', async () => {
		const { onsubmit } = open({ verb: 'Add' });

		const dialog = await screen.findByRole('dialog');
		const input = within(dialog).getByLabelText('Name') as HTMLInputElement;
		const verb = within(dialog).getByRole('button', { name: 'Add' }) as HTMLButtonElement;
		expect(verb.type).toBe('submit');
		expect(verb.form).not.toBeNull();
		expect(input.form).toBe(verb.form);

		await fireEvent.click(verb);
		expect(onsubmit).toHaveBeenCalledOnce();
	});

	it('submits when the form is submitted (Enter in a field)', async () => {
		const { onsubmit } = open({ verb: 'Add' });

		const dialog = await screen.findByRole('dialog');
		const input = within(dialog).getByLabelText('Name') as HTMLInputElement;
		await fireEvent.submit(input.form!);

		expect(onsubmit).toHaveBeenCalledOnce();
	});

	it('does not submit while the verb is disabled', async () => {
		const { onsubmit } = open({ verb: 'Add', disabled: true });

		const dialog = await screen.findByRole('dialog');
		const input = within(dialog).getByLabelText('Name') as HTMLInputElement;
		await fireEvent.submit(input.form!);

		expect(onsubmit).not.toHaveBeenCalled();
		expect(within(dialog).getByRole('button', { name: 'Add' })).toBeDisabled();
	});

	it('starts with focus in the first field', async () => {
		open({ verb: 'Add' });

		const dialog = await screen.findByRole('dialog');
		await waitFor(() => expect(within(dialog).getByLabelText('Name')).toHaveFocus());
	});

	it('cancels with Cancel and with Esc', async () => {
		const { onclose } = open({ verb: 'Add' });

		const dialog = await screen.findByRole('dialog');
		await fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }));
		expect(onclose).toHaveBeenCalledTimes(1);

		await fireEvent.keyDown(within(dialog).getByLabelText('Name'), { key: 'Escape' });
		await waitFor(() => expect(onclose).toHaveBeenCalledTimes(2));
	});

	it('takes the standard buttons: Cancel outline, the verb primary, both 32px', async () => {
		open({ verb: 'Add' });

		const dialog = await screen.findByRole('dialog');
		const cancel = within(dialog).getByRole('button', { name: 'Cancel' });
		const verb = within(dialog).getByRole('button', { name: 'Add' });
		expect(cancel).toHaveClass('h-8', 'bg-background');
		expect(verb).toHaveClass('h-8', 'bg-primary');
	});
});

describe('ActionDialog: decision dialog', () => {
	it('is not a form: Enter in a field never confirms', async () => {
		const { onsubmit } = open({ mode: 'decision', verb: 'Merge', title: 'Merge Food into…' });

		const dialog = await screen.findByRole('dialog');
		expect(dialog.querySelector('form')).toBeNull();
		await fireEvent.keyDown(within(dialog).getByLabelText('Name'), { key: 'Enter' });
		expect(onsubmit).not.toHaveBeenCalled();
	});

	it('confirms with the verb button, which repeats the action', async () => {
		const { onsubmit } = open({
			mode: 'decision',
			verb: 'Tag 214 entries',
			title: 'Tag all',
			children: consequences
		});

		const dialog = await screen.findByRole('dialog');
		await fireEvent.click(within(dialog).getByRole('button', { name: 'Tag 214 entries' }));

		expect(onsubmit).toHaveBeenCalledOnce();
	});

	it('starts with focus on Cancel when it deletes, and the verb is destructive', async () => {
		open({
			mode: 'decision',
			verb: 'Delete',
			destructive: true,
			title: 'Delete Food?',
			children: consequences
		});

		const dialog = await screen.findByRole('dialog');
		await waitFor(() =>
			expect(within(dialog).getByRole('button', { name: 'Cancel' })).toHaveFocus()
		);
		expect(within(dialog).getByRole('button', { name: 'Delete' })).toHaveClass('text-destructive');
	});

	it('starts with focus on the verb when it is not destructive and has no field', async () => {
		open({ mode: 'decision', verb: 'Tag 3 entries', title: 'Tag all', children: consequences });

		const dialog = await screen.findByRole('dialog');
		await waitFor(() =>
			expect(within(dialog).getByRole('button', { name: 'Tag 3 entries' })).toHaveFocus()
		);
	});

	it('starts with focus in its find box when it has one', async () => {
		open({ mode: 'decision', verb: 'Merge', title: 'Merge Food into…' });

		const dialog = await screen.findByRole('dialog');
		await waitFor(() => expect(within(dialog).getByLabelText('Name')).toHaveFocus());
	});

	it('cancels with Esc', async () => {
		const { onclose } = open({
			mode: 'decision',
			verb: 'Delete',
			destructive: true,
			children: consequences
		});

		const dialog = await screen.findByRole('dialog');
		await fireEvent.keyDown(within(dialog).getByRole('button', { name: 'Cancel' }), {
			key: 'Escape'
		});

		await waitFor(() => expect(onclose).toHaveBeenCalledOnce());
	});
});

describe('ActionDialog: pick dialog', () => {
	it('has Cancel only', async () => {
		open({ mode: 'pick', title: 'Move Food under…' });

		const dialog = await screen.findByRole('dialog');
		const names = within(dialog)
			.getAllByRole('button')
			.map((b) => b.textContent?.trim());
		expect(names).toContain('Cancel');
		expect(names).not.toContain('Add');
		expect(names.filter((n) => n && n !== 'Close' && n !== 'Cancel')).toEqual([]);
	});
});

describe('ActionDialog: busy', () => {
	it('disables both buttons, names the verb in progress and cannot be dismissed', async () => {
		const { onclose } = open({
			verb: 'Delete',
			busyVerb: 'Deleting…',
			busy: true,
			mode: 'decision',
			destructive: true
		});

		const dialog = await screen.findByRole('dialog');
		expect(within(dialog).getByRole('button', { name: 'Cancel' })).toBeDisabled();
		expect(within(dialog).getByRole('button', { name: 'Deleting…' })).toBeDisabled();

		await fireEvent.keyDown(within(dialog).getByLabelText('Name'), { key: 'Escape' });
		await fireEvent.click(within(dialog).getByRole('button', { name: 'Close' }));
		expect(onclose).not.toHaveBeenCalled();
	});
});

describe('ActionDialog: feedback', () => {
	it('says an error as an alert in the destructive colour', async () => {
		open({ verb: 'Add', feedback: { kind: 'error', text: 'The server could not do this.' } });

		const alert = await screen.findByRole('alert');
		expect(alert).toHaveTextContent('The server could not do this.');
		expect(alert).toHaveClass('text-destructive');
	});

	it('says a conflict as plain status text', async () => {
		open({
			verb: 'Merge',
			feedback: { kind: 'conflict', text: 'It now repoints 13 entries (was 12).' }
		});

		const status = await screen.findByRole('status');
		expect(status).toHaveTextContent('It now repoints 13 entries (was 12).');
		expect(status).not.toHaveClass('text-destructive');
		expect(screen.queryByRole('alert')).toBeNull();
	});

	it('says a report as an alert with its lines', async () => {
		open({
			verb: 'Revert',
			feedback: { kind: 'report', text: 'Partly done.', lines: ['3 entries reverted', '1 kept'] }
		});

		const alert = await screen.findByRole('alert');
		expect(alert).toHaveTextContent('Partly done.');
		expect(within(alert).getAllByRole('listitem')).toHaveLength(2);
	});

	it('offers the stale notice its action, such as Reload', async () => {
		const onclick = vi.fn();
		open({
			verb: 'Add',
			feedback: { kind: 'conflict', text: 'The lists moved.', action: { label: 'Reload', onclick } }
		});

		await fireEvent.click(await screen.findByRole('button', { name: 'Reload' }));

		expect(onclick).toHaveBeenCalledOnce();
	});

	it('has no feedback slot content when there is nothing to say', async () => {
		open({ verb: 'Add' });

		await screen.findByRole('dialog');
		expect(document.querySelector('[data-slot="dialog-feedback"]')).toBeNull();
	});
});
