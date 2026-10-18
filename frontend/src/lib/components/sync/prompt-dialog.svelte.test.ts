import { fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import type { OpenPrompt } from '#lib/sync/events.js';
import type { PromptBody } from '#lib/types/domain.js';
import PromptDialog from './prompt-dialog.svelte';

const tan = (over: Partial<Extract<PromptBody, { kind: 'tan' }>> = {}): PromptBody => ({
	kind: 'tan',
	medium: 'text',
	challenge: 'Enter the TAN shown on your phone',
	method: 'pushTAN',
	image_b64: null,
	image_mime: null,
	...over
});

const pin: PromptBody = { kind: 'secret', subject: 'pin' };

async function open(body: PromptBody, props: Record<string, unknown> = {}) {
	const prompt: OpenPrompt = {
		promptId: 'p1',
		instanceId: 1,
		runId: null,
		expiresAt: '2026-10-18T12:32:00Z',
		body
	};
	const handlers = { onanswer: vi.fn(), oncancel: vi.fn(), onstop: vi.fn() };
	render(PromptDialog, {
		props: {
			prompt,
			login: 'Giro login',
			moment: 'Signing in.',
			timeZone: 'Europe/Berlin',
			locale: 'de',
			canStop: true,
			...handlers,
			...props
		}
	});
	await screen.findByRole('dialog');
	return handlers;
}

describe('PromptDialog: a PIN or password', () => {
	it('asks for the PIN in a hidden field the browser does not remember', async () => {
		await open(pin);

		expect(screen.getByRole('dialog', { name: 'PIN for Giro login' })).toBeInTheDocument();
		expect(screen.getByText('Signing in.')).toBeInTheDocument();
		const field = screen.getByLabelText('PIN');
		expect(field).toHaveAttribute('type', 'password');
		expect(field).toHaveAttribute('autocomplete', 'off');
		expect(field).not.toHaveAttribute('placeholder');
		expect(screen.getByRole('button', { name: 'Sign in' })).toBeInTheDocument();
	});

	it('labels a password by its subject', async () => {
		await open({ kind: 'secret', subject: 'password' });

		expect(screen.getByRole('dialog', { name: 'Password for Giro login' })).toBeInTheDocument();
		expect(screen.getByLabelText('Password')).toBeInTheDocument();
	});

	it('sends what was typed with the verb', async () => {
		const { onanswer } = await open(pin);

		await fireEvent.input(screen.getByLabelText('PIN'), { target: { value: '1234' } });
		await fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));

		expect(onanswer).toHaveBeenCalledWith('1234');
	});

	it('says when it expires, in the household zone, and what cancelling does', async () => {
		await open(pin);

		expect(screen.getByText('Expires at 14:32')).toBeInTheDocument();
		expect(
			screen.getByText('Cancelling stops this login; its accounts keep failed runs to run again.')
		).toBeInTheDocument();
	});
});

describe('PromptDialog: a TAN', () => {
	it('shows the bank’s challenge and method as given, and one field "TAN"', async () => {
		await open(tan());

		expect(screen.getByRole('dialog', { name: 'TAN for Giro login' })).toBeInTheDocument();
		expect(screen.getByText('Enter the TAN shown on your phone')).toBeInTheDocument();
		expect(screen.getByText('TAN method: pushTAN')).toBeInTheDocument();
		expect(screen.getByLabelText('TAN')).toHaveAttribute('type', 'text');
		expect(screen.getByRole('button', { name: 'Send TAN' })).toBeInTheDocument();
	});

	it('shows a photoTAN image from its base64 and type, above the field', async () => {
		await open(tan({ medium: 'image', image_b64: 'QUJD', image_mime: 'image/png' }));

		const image = screen.getByRole('img', { name: 'photoTAN challenge' });
		expect(image).toHaveAttribute('src', 'data:image/png;base64,QUJD');
		expect(
			image.compareDocumentPosition(screen.getByLabelText('TAN')) & Node.DOCUMENT_POSITION_FOLLOWING
		).toBeTruthy();
	});

	it('has no field and no verb for a decoupled confirmation, only a waiting indicator', async () => {
		await open(tan({ medium: 'decoupled', challenge: 'Open the app' }));

		expect(screen.getByText('Open the app')).toBeInTheDocument();
		expect(screen.getByText(/Confirm in your banking app/)).toBeInTheDocument();
		const dialog = screen.getByRole('dialog');
		expect(within(dialog).getByRole('status')).toBeInTheDocument();
		expect(within(dialog).queryByRole('textbox')).toBeNull();
		expect(within(dialog).queryByLabelText('TAN')).toBeNull();
		expect(within(dialog).queryByRole('button', { name: 'Send TAN' })).toBeNull();
		expect(within(dialog).queryByRole('button', { name: 'Continue' })).toBeNull();
		expect(within(dialog).getByRole('button', { name: 'Cancel' })).toBeInTheDocument();
	});
});

describe('PromptDialog: a choice and a text', () => {
	it('lists the options with none chosen, under the label of the subject', async () => {
		await open({
			kind: 'choice',
			subject: 'tan_mechanism',
			options: [
				{ id: '902', label: 'pushTAN' },
				{ id: '910', label: 'photoTAN' }
			]
		});

		expect(screen.getByRole('dialog', { name: 'TAN method for Giro login' })).toBeInTheDocument();
		const trigger = screen.getByRole('button', { name: 'TAN method' });
		expect(trigger.textContent?.trim()).toBe('');
		expect(screen.getByRole('button', { name: 'Continue' })).toBeInTheDocument();
	});

	it('sends the id of the option chosen', async () => {
		const { onanswer } = await open({
			kind: 'choice',
			subject: 'tan_medium',
			options: [{ id: 'm1', label: 'My phone' }]
		});

		await fireEvent.click(screen.getByRole('button', { name: 'TAN medium' }));
		await fireEvent.click(await screen.findByRole('option', { name: 'My phone' }));
		await fireEvent.click(screen.getByRole('button', { name: 'Continue' }));

		expect(onanswer).toHaveBeenCalledWith('m1');
	});

	it('asks for a text with one field, labelled by the subject', async () => {
		await open({ kind: 'text', subject: 'tan_medium_name' });

		expect(screen.getByLabelText('Name of the TAN medium')).toHaveAttribute('type', 'text');
		expect(screen.getByRole('button', { name: 'Continue' })).toBeInTheDocument();
	});

	it('shows an unknown subject as given', async () => {
		await open({ kind: 'text', subject: 'security_question' });

		expect(screen.getByLabelText('security_question')).toBeInTheDocument();
	});
});

describe('PromptDialog: answering, cancelling and stopping', () => {
	it('cancels the prompt with Cancel and with Esc', async () => {
		const { oncancel } = await open(pin);

		await fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
		expect(oncancel).toHaveBeenCalledTimes(1);

		await fireEvent.keyDown(screen.getByLabelText('PIN'), { key: 'Escape' });
		await waitFor(() => expect(oncancel).toHaveBeenCalledTimes(2));
	});

	it('offers "Stop sync…" for a sync', async () => {
		const { onstop } = await open(pin);

		await fireEvent.click(screen.getByRole('button', { name: 'Stop sync…' }));
		expect(onstop).toHaveBeenCalledTimes(1);
	});

	it('has no "Stop sync…" where the task is not a sync', async () => {
		await open(pin, { canStop: false });

		expect(screen.queryByRole('button', { name: 'Stop sync…' })).toBeNull();
	});

	it('says "Sending…" while the answer is on its way, and cannot be dismissed', async () => {
		const { oncancel } = await open(pin, { sending: true });

		expect(screen.getByRole('button', { name: 'Sending…' })).toBeDisabled();
		expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled();
		await fireEvent.keyDown(screen.getByLabelText('PIN'), { key: 'Escape' });
		expect(oncancel).not.toHaveBeenCalled();
	});

	it('shows the server’s refusal under the field and keeps the dialog', async () => {
		await open(pin, { fieldError: 'The PIN is empty.' });

		expect(screen.getByLabelText('PIN')).toHaveAccessibleDescription('The PIN is empty.');
		expect(screen.getByRole('dialog')).toBeInTheDocument();
	});

	it('shows a failure to send above the buttons', async () => {
		await open(pin, { sendError: 'The server could not be reached.' });

		expect(screen.getByText('The server could not be reached.')).toBeInTheDocument();
	});
});
