import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import { emptyDraft } from '#lib/importers/fints-profile.js';
import FintsForm from './fints-form.svelte';

function form(errors: Record<string, string> = {}) {
	const draft = $state(emptyDraft());
	render(FintsForm, { props: { draft, errors } });
	return draft;
}

describe('FintsForm', () => {
	it('shows the four labelled fields with their helper texts and no placeholders', () => {
		form();

		for (const label of ['Bank address', 'Bank code', 'Login name', 'Customer ID']) {
			expect(screen.getByLabelText(label)).toBeInTheDocument();
		}
		expect(document.querySelectorAll('input')).toHaveLength(4);
		for (const field of document.querySelectorAll('input')) {
			expect(field).not.toHaveAttribute('placeholder');
		}
		expect(screen.getByText(/It must start with https\./)).toBeInTheDocument();
		expect(screen.getByText('The eight-digit Bankleitzahl of your bank.')).toBeInTheDocument();
		expect(screen.getByText('The name you sign in to online banking with.')).toBeInTheDocument();
		expect(screen.getByText(/Leave empty otherwise\./)).toBeInTheDocument();
		const pin = 'The PIN is not stored. You will be asked for it whenever this login is used.';
		expect(screen.getByText(pin)).toBeInTheDocument();
		expect(screen.queryByRole('button')).toBeNull();
	});

	it('edits the draft it is given', async () => {
		const draft = form();

		await fireEvent.input(screen.getByLabelText('Bank code'), { target: { value: '12345678' } });

		expect(draft.bankCode).toBe('12345678');
	});

	it('shows a refusal under the field of its setting key', () => {
		form({ bank_code: 'Bank code is not valid' });

		expect(screen.getByText('Bank code is not valid')).toBeInTheDocument();
	});
});
