// The CSV importer's settings as a form (plugins/importers/csv.md §1–§6; the server's schema is
// app/plugins/importers/csv/profile.py). The profile is plain data; the form holds it as text, so
// that what is typed is kept as typed and the server alone judges it. `draftFromSettings` reads a
// stored profile or a preset; `settingsFromDraft` writes what the server takes.

/** A date found in the file by label (`LocatedDate`): optional, so it carries `on`. */
export type LocatedDraft = {
	on: boolean;
	format: string;
	label: string;
	right: string;
	below: string;
	pattern: string;
};

export type FilterDraft = { column: string; kind: 'equals' | 'matches'; value: string };

export type CsvDraft = {
	// reading the file
	encoding: string;
	delimiter: string;
	quote: string;
	/** one column name per line */
	headerMarker: string;
	// columns
	bookedOn: string;
	dateFormat: string;
	valueOn: string;
	amountMode: 'signed' | 'split';
	amountColumn: string;
	credit: string;
	debit: string;
	decimalSep: string;
	thousandsSep: string;
	counterpartyName: string;
	counterpartyRef: string;
	counterpartyBic: string;
	endToEndId: string;
	mandateRef: string;
	bookingText: string;
	/** one column per line */
	purpose: string;
	instructedAmount: string;
	instructedCurrency: string;
	currency: string;
	// rows
	/** one placeholder per line */
	placeholders: string;
	filters: FilterDraft[];
	// balance and coverage
	balanceMode: 'none' | 'running_column' | 'labelled';
	balanceColumn: string;
	balanceLabel: string;
	balanceRight: string;
	balanceBelow: string;
	balanceDate: LocatedDraft;
	exportDate: LocatedDraft;
	coverageEnd: LocatedDraft;
	// statement payment
	paymentOn: boolean;
	paymentRef: string;
	paymentPurpose: string;
	paymentOffset: string;
	// inversion
	invertAmounts: boolean;
	invertBalance: boolean;
};

export function emptyLocated(): LocatedDraft {
	return { on: false, format: '', label: '', right: '0', below: '0', pattern: '' };
}

/** A new profile: the server's own defaults (quote, separators), everything else to be filled in. */
export function emptyDraft(): CsvDraft {
	return {
		encoding: '',
		delimiter: '',
		quote: '"',
		headerMarker: '',
		bookedOn: '',
		dateFormat: '',
		valueOn: '',
		amountMode: 'signed',
		amountColumn: '',
		credit: '',
		debit: '',
		decimalSep: ',',
		thousandsSep: '.',
		counterpartyName: '',
		counterpartyRef: '',
		counterpartyBic: '',
		endToEndId: '',
		mandateRef: '',
		bookingText: '',
		purpose: '',
		instructedAmount: '',
		instructedCurrency: '',
		currency: '',
		placeholders: '',
		filters: [],
		balanceMode: 'none',
		balanceColumn: '',
		balanceLabel: '',
		balanceRight: '0',
		balanceBelow: '0',
		balanceDate: emptyLocated(),
		exportDate: emptyLocated(),
		coverageEnd: emptyLocated(),
		paymentOn: false,
		paymentRef: '',
		paymentPurpose: '',
		paymentOffset: '1',
		invertAmounts: false,
		invertBalance: false
	};
}

// ---- reading ---------------------------------------------------------------------------------

type Json = Record<string, unknown>;

const obj = (v: unknown): Json | null =>
	v !== null && typeof v === 'object' && !Array.isArray(v) ? (v as Json) : null;
const text = (v: unknown, fallback = ''): string =>
	typeof v === 'string' ? v : typeof v === 'number' ? String(v) : fallback;
const lines = (v: unknown): string =>
	Array.isArray(v) ? v.map((item) => text(item)).join('\n') : '';

function located(v: unknown): LocatedDraft {
	const d = obj(v);
	if (!d) return emptyLocated();
	return {
		on: true,
		format: text(d.format),
		label: text(d.label),
		right: text(d.right, '0'),
		below: text(d.below, '0'),
		pattern: text(d.pattern)
	};
}

/** The form for stored settings or a preset; a part the profile lacks is left at its default. */
export function draftFromSettings(settings: Json): CsvDraft {
	const draft = emptyDraft();
	const amount = obj(settings.amount);
	const instructed = obj(settings.instructed);
	const balance = obj(settings.balance);
	const payment = obj(settings.statement_payment);
	const split = amount !== null && (amount.credit != null || amount.debit != null);
	return {
		...draft,
		encoding: text(settings.encoding),
		delimiter: text(settings.delimiter),
		quote: text(settings.quote, draft.quote),
		headerMarker: lines(settings.header_marker),
		bookedOn: text(settings.booked_on),
		dateFormat: text(settings.date_format),
		valueOn: text(settings.value_on),
		amountMode: split ? 'split' : 'signed',
		amountColumn: text(amount?.column),
		credit: text(amount?.credit),
		debit: text(amount?.debit),
		decimalSep: text(settings.decimal_sep, draft.decimalSep),
		thousandsSep: text(settings.thousands_sep, draft.thousandsSep),
		counterpartyName: text(settings.counterparty_name),
		counterpartyRef: text(settings.counterparty_ref),
		counterpartyBic: text(settings.counterparty_bic),
		endToEndId: text(settings.end_to_end_id),
		mandateRef: text(settings.mandate_ref),
		bookingText: text(settings.booking_text),
		purpose: lines(settings.purpose),
		instructedAmount: text(instructed?.amount),
		instructedCurrency: text(instructed?.currency),
		currency: text(settings.currency),
		placeholders: lines(settings.placeholders),
		filters: Array.isArray(settings.filters)
			? settings.filters.map((f) => {
					const d = obj(f) ?? {};
					const matches = typeof d.matches === 'string';
					return {
						column: text(d.column),
						kind: matches ? 'matches' : 'equals',
						value: text(matches ? d.matches : d.equals)
					} as FilterDraft;
				})
			: [],
		balanceMode:
			balance?.mode === 'running_column' || balance?.mode === 'labelled' ? balance.mode : 'none',
		balanceColumn: text(balance?.column),
		balanceLabel: text(balance?.label),
		balanceRight: text(balance?.right, '0'),
		balanceBelow: text(balance?.below, '0'),
		balanceDate: located(balance?.date),
		exportDate: located(settings.export_date),
		coverageEnd: located(settings.coverage_end),
		paymentOn: payment !== null,
		paymentRef: text(payment?.counter_account_ref),
		paymentPurpose: text(payment?.purpose),
		paymentOffset: text(payment?.date_offset_days, '1'),
		invertAmounts: settings.invert_amounts === true,
		invertBalance: settings.invert_balance === true
	};
}

// ---- writing ---------------------------------------------------------------------------------

/** A line-per-item field as a list: trimmed lines, blank ones dropped. */
function list(value: string): string[] {
	return value
		.split('\n')
		.map((line) => line.trim())
		.filter((line) => line !== '');
}

/** A column reference: a whole number is a position (counted from 1), anything else a name. */
function column(value: string): string | number | null {
	const t = value.trim();
	if (t === '') return null;
	return /^\d+$/.test(t) ? Number(t) : t;
}

/** A whole number as typed; text that is not one goes to the server as it is, which refuses it by name. */
function whole(value: string): number | string {
	const t = value.trim();
	return /^-?\d+$/.test(t) ? Number(t) : t;
}

const orNull = (value: string): string | null => (value.trim() === '' ? null : value.trim());

function locatedOut(d: LocatedDraft) {
	return d.on
		? {
				format: d.format.trim(),
				label: orNull(d.label),
				right: whole(d.right),
				below: whole(d.below),
				pattern: orNull(d.pattern)
			}
		: null;
}

/** The settings the server takes, from the form. Nothing is judged here: the server names what is wrong. */
export function settingsFromDraft(d: CsvDraft): Json {
	const signed = d.amountMode === 'signed';
	const hasInstructed = d.instructedAmount.trim() !== '' || d.instructedCurrency.trim() !== '';
	return {
		encoding: orNull(d.encoding),
		delimiter: d.delimiter === '' ? null : d.delimiter,
		quote: d.quote,
		header_marker: list(d.headerMarker),
		booked_on: column(d.bookedOn) ?? '',
		value_on: column(d.valueOn),
		date_format: d.dateFormat.trim(),
		amount: signed
			? { column: column(d.amountColumn), credit: null, debit: null }
			: { column: null, credit: column(d.credit), debit: column(d.debit) },
		decimal_sep: d.decimalSep,
		thousands_sep: d.thousandsSep,
		invert_amounts: d.invertAmounts,
		invert_balance: d.invertBalance,
		counterparty_name: column(d.counterpartyName),
		counterparty_ref: column(d.counterpartyRef),
		counterparty_bic: column(d.counterpartyBic),
		end_to_end_id: column(d.endToEndId),
		mandate_ref: column(d.mandateRef),
		booking_text: column(d.bookingText),
		purpose: list(d.purpose).map((c) => column(c) ?? c),
		instructed: hasInstructed
			? { amount: column(d.instructedAmount) ?? '', currency: column(d.instructedCurrency) ?? '' }
			: null,
		currency: column(d.currency),
		placeholders: list(d.placeholders),
		filters: d.filters.map((f) => ({
			column: column(f.column) ?? '',
			equals: f.kind === 'equals' ? f.value : null,
			matches: f.kind === 'matches' ? f.value : null
		})),
		balance:
			d.balanceMode === 'none'
				? null
				: d.balanceMode === 'running_column'
					? {
							mode: 'running_column',
							column: column(d.balanceColumn),
							label: null,
							right: 0,
							below: 0,
							date: null
						}
					: {
							mode: 'labelled',
							column: null,
							label: d.balanceLabel.trim(),
							right: whole(d.balanceRight),
							below: whole(d.balanceBelow),
							date: locatedOut(d.balanceDate)
						},
		export_date: locatedOut(d.exportDate),
		coverage_end: locatedOut(d.coverageEnd),
		statement_payment: d.paymentOn
			? {
					counter_account_ref: d.paymentRef.trim(),
					purpose: d.paymentPurpose,
					date_offset_days: whole(d.paymentOffset)
				}
			: null
	};
}

// ---- where the server's refusal stands --------------------------------------------------------

/**
 * The form field a refused setting belongs to. The server names a setting by its path in the profile
 * (`amount.column`, `balance.date.format`, `filters.matches`); the form shows the message under the
 * field of that setting, or the nearest one it has.
 */
export function fieldOfSetting(setting: string): string {
	const known = SETTING_FIELDS[setting];
	if (known) return known;
	// a deeper path (a located date's part, a filter's part) belongs to the field of its parent
	const parts = setting.split('.');
	while (parts.length > 1) {
		parts.pop();
		const parent = SETTING_FIELDS[parts.join('.')];
		if (parent) return parent;
	}
	return setting;
}

const SETTING_FIELDS: Record<string, string> = {
	'amount.column': 'amount',
	'amount.credit': 'amount',
	'amount.debit': 'amount',
	'instructed.amount': 'instructed',
	'instructed.currency': 'instructed',
	'filters.column': 'filters',
	'filters.equals': 'filters',
	'filters.matches': 'filters',
	'balance.mode': 'balance',
	'balance.column': 'balance',
	'balance.label': 'balance',
	'balance.right': 'balance',
	'balance.below': 'balance',
	'balance.date': 'balance.date',
	'export_date.format': 'export_date',
	'export_date.label': 'export_date',
	'export_date.right': 'export_date',
	'export_date.below': 'export_date',
	'export_date.pattern': 'export_date',
	'coverage_end.format': 'coverage_end',
	'coverage_end.label': 'coverage_end',
	'coverage_end.right': 'coverage_end',
	'coverage_end.below': 'coverage_end',
	'coverage_end.pattern': 'coverage_end',
	'statement_payment.counter_account_ref': 'statement_payment',
	'statement_payment.purpose': 'statement_payment',
	'statement_payment.date_offset_days': 'statement_payment'
};

/** Every field id the CSV form shows an error under; a refusal elsewhere stands above the buttons. */
export const CSV_FIELDS: readonly string[] = [
	'encoding',
	'delimiter',
	'quote',
	'header_marker',
	'booked_on',
	'value_on',
	'date_format',
	'amount',
	'decimal_sep',
	'thousands_sep',
	'counterparty_name',
	'counterparty_ref',
	'counterparty_bic',
	'end_to_end_id',
	'mandate_ref',
	'booking_text',
	'purpose',
	'instructed',
	'currency',
	'placeholders',
	'filters',
	'balance',
	'balance.date',
	'export_date',
	'coverage_end',
	'statement_payment',
	'invert_amounts',
	'invert_balance'
];
