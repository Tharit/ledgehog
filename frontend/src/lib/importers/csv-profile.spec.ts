import { describe, expect, it } from 'vitest';
import { draftFromSettings, emptyDraft, fieldOfSetting, settingsFromDraft } from './csv-profile.js';

// the shape of the shipped "giro with a preamble" preset (app/plugins/importers/csv/presets)
const GIRO = {
	encoding: null,
	delimiter: null,
	quote: '"',
	header_marker: ['Buchung', 'Valuta', 'Betrag'],
	booked_on: 'Buchung',
	value_on: 'Valuta',
	date_format: 'dd.MM.yyyy',
	amount: { column: 'Betrag', credit: null, debit: null },
	decimal_sep: ',',
	thousands_sep: '.',
	invert_amounts: false,
	invert_balance: false,
	counterparty_name: 'Sender / Empfänger',
	counterparty_ref: 'IBAN',
	counterparty_bic: 'BIC',
	end_to_end_id: null,
	mandate_ref: null,
	booking_text: null,
	purpose: ['Buchungstext', 'Verwendungszweck'],
	instructed: null,
	currency: 'Währung',
	placeholders: ['n/a'],
	filters: [{ column: 'Valuta', equals: 'vorgemerkt', matches: null }],
	balance: {
		mode: 'labelled',
		column: null,
		label: 'Saldo',
		right: 0,
		below: 1,
		date: { format: 'dd.MM.yyyy', label: null, right: 2, below: 1, pattern: null }
	},
	export_date: {
		format: 'dd.MM.yyyy, HH:mm:ss',
		label: 'Exportdatum',
		right: 0,
		below: 1,
		pattern: null
	},
	coverage_end: null,
	statement_payment: null
};

describe('the CSV profile form', () => {
	it('writes a preset back as the same settings', () => {
		expect(settingsFromDraft(draftFromSettings(GIRO))).toEqual(GIRO);
	});

	it('reads a counterparty column with a pattern and writes it back unchanged', () => {
		const settings = {
			...GIRO,
			counterparty_name: { column: 'Verwendungszweck', pattern: '^([^,]+),' }
		};
		const draft = draftFromSettings(settings);

		expect(draft.counterpartyName).toBe('Verwendungszweck');
		expect(draft.counterpartyPattern).toBe('^([^,]+),');
		expect(settingsFromDraft(draft)).toEqual(settings);
	});

	it('writes a counterparty column without a pattern as the plain column', () => {
		const draft = { ...emptyDraft(), counterpartyName: '4', counterpartyPattern: '  ' };

		expect(settingsFromDraft(draft).counterparty_name).toBe(4);
	});

	it('reads a card with a statement payment, two amount columns and a position', () => {
		const settings = {
			...GIRO,
			amount: { column: null, credit: 'Haben', debit: 4 },
			statement_payment: {
				counter_account_ref: 'x',
				purpose: 'Card {statement_date}',
				date_offset_days: 4
			}
		};
		const draft = draftFromSettings(settings);

		expect(draft.amountMode).toBe('split');
		expect(draft.debit).toBe('4');
		expect(draft.paymentOn).toBe(true);
		expect(settingsFromDraft(draft)).toEqual(settings);
	});

	it('writes a number typed in a column as a position and anything else as a name', () => {
		const draft = { ...emptyDraft(), bookedOn: '2', amountColumn: 'Betrag#2' };
		const out = settingsFromDraft(draft);

		expect(out.booked_on).toBe(2);
		expect(out.amount).toEqual({ column: 'Betrag#2', credit: null, debit: null });
	});

	it('leaves a refused number as typed, for the server to name', () => {
		const draft = {
			...emptyDraft(),
			balanceMode: 'labelled' as const,
			balanceLabel: 'Saldo',
			balanceRight: 'two'
		};
		expect(settingsFromDraft(draft).balance).toMatchObject({ right: 'two' });
	});

	it('sends no balance, instructed amount or payment that is switched off', () => {
		const out = settingsFromDraft(emptyDraft());

		expect(out.balance).toBeNull();
		expect(out.instructed).toBeNull();
		expect(out.statement_payment).toBeNull();
		expect(out.export_date).toBeNull();
	});

	it('puts a refusal under the field of its setting, or of its parent', () => {
		expect(fieldOfSetting('amount.column')).toBe('amount');
		expect(fieldOfSetting('balance.date.format')).toBe('balance.date');
		expect(fieldOfSetting('filters.matches')).toBe('filters');
		expect(fieldOfSetting('header_marker')).toBe('header_marker');
		expect(fieldOfSetting('export_date.pattern')).toBe('export_date');
		expect(fieldOfSetting('counterparty_name.pattern')).toBe('counterparty_pattern');
		expect(fieldOfSetting('counterparty_name.column')).toBe('counterparty_name');
	});
});
