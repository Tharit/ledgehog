import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import { draftFromSettings, emptyDraft, settingsFromDraft } from '#lib/importers/csv-profile.js';
import CsvProfileForm from './csv-profile-form.svelte';

// the store holds the draft as state; so does the test, or the form would not redraw
function form(start = emptyDraft(), errors: Record<string, string> = {}) {
	const draft = $state(start);
	render(CsvProfileForm, { props: { draft, errors } });
	return draft;
}

describe('CsvProfileForm', () => {
	it('groups the fields as the profile does', () => {
		form();

		for (const group of [
			'Reading the file',
			'Columns',
			'Rows',
			'Balance and coverage',
			'Statement payment',
			'Signs'
		]) {
			expect(screen.getByRole('group', { name: group })).toBeInTheDocument();
		}
	});

	it('labels every field and gives none an example value as a placeholder', () => {
		form();

		const fields = document.querySelectorAll('input, textarea');
		expect(fields.length).toBeGreaterThan(10);
		for (const field of fields) {
			expect(field).not.toHaveAttribute('placeholder');
			expect(field.id).not.toBe('');
			expect(document.querySelector(`label[for="${field.id}"]`)).not.toBeNull();
		}
	});

	it('says in the helper text how a column is named', () => {
		form();

		expect(screen.getAllByText(/Name#2 for the second column of that name/).length).toBeGreaterThan(
			0
		);
	});

	it('edits the draft it is given', async () => {
		const draft = form();

		await fireEvent.input(screen.getByLabelText('Booking date column'), {
			target: { value: 'Buchung' }
		});
		await fireEvent.input(screen.getByLabelText('Header marker'), {
			target: { value: 'Buchung\nBetrag' }
		});

		expect(draft.bookedOn).toBe('Buchung');
		expect(settingsFromDraft(draft).header_marker).toEqual(['Buchung', 'Betrag']);
	});

	it('shows the credit and debit columns instead of the signed one when asked', () => {
		form(draftFromSettings({ amount: { column: null, credit: 'Haben', debit: 'Soll' } }));

		expect(screen.getByLabelText('Credit column')).toHaveValue('Haben');
		expect(screen.getByLabelText('Debit column')).toHaveValue('Soll');
		expect(screen.queryByLabelText('Amount column')).toBeNull();
	});

	it('adds and removes a row filter', async () => {
		const draft = form();

		await fireEvent.click(screen.getByRole('button', { name: 'Add filter' }));
		expect(draft.filters).toHaveLength(1);
		expect(screen.getByLabelText('Filter 1: column')).toBeInTheDocument();

		await fireEvent.click(screen.getByRole('button', { name: 'Remove filter 1' }));
		expect(draft.filters).toHaveLength(0);
	});

	it('shows the server’s refusal under the field it names', () => {
		form(emptyDraft(), { date_format: 'Unknown token', amount: 'Give one signed column' });

		expect(screen.getByText('Unknown token')).toBeInTheDocument();
		expect(screen.getByText('Give one signed column')).toBeInTheDocument();
		expect(screen.getByLabelText('Date format')).toHaveAttribute('aria-invalid', 'true');
	});
});
