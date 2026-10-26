import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import { emptyDraft } from '#lib/importers/email-profile.js';
import EmailForm from './email-form.svelte';

function form(errors: Record<string, string> = {}) {
	const draft = $state(emptyDraft({ today: '2026-10-24' }));
	render(EmailForm, { props: { draft, errors } });
	return draft;
}

describe('EmailForm', () => {
	it('shows the labelled fields with helper texts, no placeholders, no password field', () => {
		form();

		for (const label of ['Mail server', 'Port', 'Login name', 'Folder', 'Senders']) {
			expect(screen.getByLabelText(label)).toBeInTheDocument();
		}
		expect(screen.getByRole('button', { name: 'Security' })).toHaveTextContent('TLS');
		expect(screen.getByRole('button', { name: 'Start date' })).toBeInTheDocument();
		for (const field of document.querySelectorAll('input, textarea')) {
			expect(field).not.toHaveAttribute('placeholder');
		}
		expect(screen.queryByLabelText(/password/i)).toBeNull();
		expect(screen.getByLabelText('Folder')).toHaveValue('INBOX');
		expect(screen.getByLabelText('Port')).toHaveValue('');
		expect(screen.getByText(/993 with TLS, 143 with STARTTLS/)).toBeInTheDocument();
		expect(screen.getByText(/The password is not stored/)).toBeInTheDocument();
		expect(screen.getByText(/sent whole to the configured model/)).toBeInTheDocument();
	});

	it('edits the draft, the senders as one text of lines', async () => {
		const draft = form();

		await fireEvent.input(screen.getByLabelText('Senders'), {
			target: { value: 'a@b.de\nc@d.de' }
		});
		await fireEvent.input(screen.getByLabelText('Mail server'), {
			target: { value: 'imap.x.org' }
		});

		expect(draft.senders).toBe('a@b.de\nc@d.de');
		expect(draft.host).toBe('imap.x.org');
	});

	it('shows a refusal under the field of its setting key', () => {
		form({ senders: 'Needs at least one address', port: 'Port is wrong' });

		expect(screen.getByText('Needs at least one address')).toBeInTheDocument();
		expect(screen.getByText('Port is wrong')).toBeInTheDocument();
	});
});
