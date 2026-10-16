import { describe, expect, it } from 'vitest';
import { entry } from '#lib/ledger/fixtures.js';
import { Draft } from './draft.js';
import { documentSummary, previewRowOf, rowDocument, unit } from './fixtures.js';
import { documentField, documentHints, waitingText } from './unit-document.js';

const e = entry({
	id: 1,
	version: 3,
	unit_key: 1,
	source_transaction_id: 5,
	amount: { amount: -4731, currency: 'EUR' },
	booked_on: '2026-10-09'
});
const single = unit({ anchor_entry_id: 1, entries: [e] });
const draft = () => Draft.of(single);
const rowOf = (document: ReturnType<typeof rowDocument> | null) => previewRowOf(e, { document });

describe('documentField', () => {
	it('shows nothing where the preview and the draft say nothing', () => {
		expect(documentField(rowOf(null), draft(), 1)).toBeNull();
		expect(documentField(null, draft(), 1)).toBeNull();
	});

	it('shows a document matched by the matcher, with its key', () => {
		const linked = documentSummary();
		const field = documentField(
			rowOf(
				rowDocument({
					stored_document_id: 7,
					document: linked,
					key: { pass: 'matcher_decision', basis: {} }
				})
			),
			draft(),
			1
		)!;
		expect(field).toMatchObject({ state: 'linked', document: linked });
		expect(field.evidence).toEqual({ text: 'document matched', proposal: false });
	});

	it('marks a matched document of several lines as a proposal to check', () => {
		const field = documentField(
			rowOf(
				rowDocument({
					document: documentSummary(),
					key: { pass: 'matcher_proposal', basis: {} }
				})
			),
			draft(),
			1
		)!;
		expect(field.evidence).toEqual({
			text: 'document matched — check the split',
			proposal: true
		});
	});

	it('says "picked by you" for a stored user key with a document', () => {
		const field = documentField(
			rowOf(rowDocument({ document: documentSummary(), key: { pass: 'user', basis: {} } })),
			draft(),
			1
		)!;
		expect(field.evidence?.text).toBe('picked by you');
	});

	it('says "no document" for the stored decision of none', () => {
		const field = documentField(
			rowOf(rowDocument({ key: { pass: 'user', basis: {} } })),
			draft(),
			1
		)!;
		expect(field).toMatchObject({ state: 'none', document: null });
		expect(field.evidence?.text).toBe('no document');
	});

	it('shows the document the draft picks, as the preview says it would be linked', () => {
		const picked = documentSummary({ id: 9 });
		const field = documentField(
			rowOf(rowDocument({ document: picked, key: { pass: 'user', basis: {} } })),
			draft().pickDocument(1, 9, 2),
			1
		)!;
		expect(field).toMatchObject({ state: 'picked', document: picked, canReset: true });
		expect(field.evidence?.text).toBe('picked by you');
	});

	it('shows a pick the preview has not answered yet', () => {
		const field = documentField(null, draft().pickDocument(1, 9, 2), 1)!;
		expect(field).toMatchObject({ state: 'picked', document: null });
	});

	it('shows the decision of none as the draft’s own', () => {
		const field = documentField(
			rowOf(rowDocument({ suggestions: [documentSummary()], decision_required: true })),
			draft().noDocument(1),
			1
		)!;
		expect(field).toMatchObject({ state: 'none', decisionRequired: false, canReset: true });
		expect(field.evidence?.text).toBe('no document');
	});

	it('lists the suggestions, and a decision is required while none is made', () => {
		const suggestions = [documentSummary(), documentSummary({ id: 8 })];
		const field = documentField(
			rowOf(rowDocument({ suggestions, decision_required: true })),
			draft(),
			1
		)!;
		expect(field).toMatchObject({ state: 'open', decisionRequired: true, provider: 'amazon' });
		expect(field.suggestions.map((d) => d.id)).toEqual([7, 8]);
	});

	it('keeps requiring a decision when the draft only re-resolves', () => {
		const field = documentField(
			rowOf(rowDocument({ decision_required: true, suggestions: [documentSummary()] })),
			draft().reresolveDocument(1),
			1
		)!;
		expect(field.state).toBe('resolve_again');
		expect(field.decisionRequired).toBe(true);
	});

	it('carries the wait, and its provider for finding one by hand', () => {
		const field = documentField(
			rowOf(
				rowDocument({
					waiting: { provider: 'paypal', covered_through: '2026-10-01' },
					decision_required: true
				})
			),
			draft(),
			1
		)!;
		expect(field.waiting).toEqual({ provider: 'paypal', covered_through: '2026-10-01' });
		expect(field.provider).toBe('paypal');
	});

	it('falls back to the provider of the payee', () => {
		expect(documentField(rowOf(rowDocument()), draft(), 1, 'amazon')!.provider).toBe('amazon');
		expect(documentField(rowOf(rowDocument()), draft(), 1)!.provider).toBeNull();
	});

	it('offers the split along the lines of the document the transaction carries', () => {
		const linked = documentSummary();
		const split = {
			document_id: 7,
			available: true,
			proposed: false,
			replaces_stored_split: true
		};
		const field = documentField(rowOf(rowDocument({ document: linked, split })), draft(), 1)!;
		expect(field.split).toEqual({
			available: true,
			proposed: false,
			replacesStoredSplit: true,
			document: { id: 7, version: 2 }
		});
		// the split of a document the draft picks is made on the version the user saw
		const picked = documentField(
			rowOf(rowDocument({ document: linked, split })),
			draft().pickDocument(1, 7, 5),
			1
		)!;
		expect(picked.split?.document).toEqual({ id: 7, version: 5 });
	});

	it('knows a refused split', () => {
		const field = documentField(rowOf(rowDocument()), draft().declineSplit(1), 1)!;
		expect(field.declined).toBe(true);
	});
});

describe('documentHints', () => {
	const entryFacts = { amount: -4731, currency: 'EUR', bookedOn: '2026-10-09' };

	it('says exact amount and the day apart', () => {
		expect(documentHints(documentSummary(), entryFacts)).toEqual(['exact amount', '1 day before']);
		expect(documentHints(documentSummary({ occurred_on: '2026-10-09' }), entryFacts)).toEqual([
			'exact amount',
			'same day'
		]);
		expect(documentHints(documentSummary({ occurred_on: '2026-10-14' }), entryFacts)).toEqual([
			'exact amount',
			'5 days after'
		]);
	});

	it('says how far a different amount is', () => {
		const hints = documentHints(
			documentSummary({ total: { amount: -5000, currency: 'EUR' } }),
			entryFacts
		);
		expect(hints[0]).toMatch(/^2\.69.* more$/);
		expect(
			documentHints(documentSummary({ total: { amount: -4000, currency: 'EUR' } }), entryFacts)[0]
		).toMatch(/less$/);
	});

	it('leaves out what it cannot compare', () => {
		expect(
			documentHints(documentSummary({ total: { amount: -4731, currency: 'USD' } }), entryFacts)
		).toEqual(['1 day before']);
		expect(documentHints(documentSummary(), { ...entryFacts, bookedOn: null })).toEqual([
			'exact amount'
		]);
	});
});

describe('waitingText', () => {
	it('names the provider and how far its documents are covered', () => {
		expect(waitingText({ provider: 'amazon', covered_through: '2026-10-12' })).toMatch(
			/^Waiting for a document from amazon, covered through .*12.*2026$/
		);
		expect(waitingText({ provider: 'amazon', covered_through: null })).toBe(
			'Waiting for a document from amazon, not synced yet'
		);
	});
});
