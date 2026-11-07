import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, commitUnit, getUnit, previewUnit } from '#lib/api/index.js';
import { entry } from '#lib/ledger/fixtures.js';
import { committed, fieldOut, joinedScene, unit } from './fixtures.js';
import { PREVIEW_DELAY_MS, UnitDraftFlow, type FlowHost } from './unit-draft-flow.svelte.js';
import type { UnitDraftRequest, UnitPreview } from './types.js';

vi.mock('#lib/api/index.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/index.js')>()),
	previewUnit: vi.fn(),
	commitUnit: vi.fn(),
	createTag: vi.fn(),
	getUnit: vi.fn()
}));

const { loaded, joinedPreview, partner } = joinedScene();

function host() {
	return {
		locale: vi.fn(() => 'en'),
		unitChanged: vi.fn(),
		patch: vi.fn(),
		reloadLookups: vi.fn().mockResolvedValue(undefined),
		addTag: vi.fn(),
		previewed: vi.fn(),
		committed: vi.fn()
	} as unknown as FlowHost;
}

const settle = async () => {
	for (let i = 0; i < 5; i++) await Promise.resolve();
};

/** the preview as the server answers it: the joined partner, the user's fixed values over its rows */
function answer(request: UnitDraftRequest): UnitPreview {
	const out = joinedPreview();
	for (const edit of request.entries ?? []) {
		const row = out.rows.find((r) => r.id === edit.id);
		if (row && edit.category?.mode === 'fixed') {
			row.fields.category = fieldOut(edit.category.value ?? null, { pass: 'user' });
		}
	}
	return out;
}

async function setup() {
	const flow = new UnitDraftFlow(host());
	flow.begin(loaded);
	await settle();
	return flow;
}

/** let the debounced preview go out and answer */
async function previewed() {
	vi.advanceTimersByTime(PREVIEW_DELAY_MS);
	await settle();
}

const lastRequest = () => vi.mocked(previewUnit).mock.calls.at(-1)![0] as UnitDraftRequest;

beforeEach(() => {
	vi.useFakeTimers();
	vi.resetAllMocks();
	vi.mocked(previewUnit).mockImplementation(async (request) => answer(request));
	vi.mocked(getUnit).mockResolvedValue(loaded);
	vi.mocked(commitUnit).mockResolvedValue(committed(loaded));
});
afterEach(() => vi.useRealTimers());

describe('what a preview tells the draft', () => {
	it('knows every entry of the unit the preview holds, without making them part of its own', async () => {
		const flow = await setup();
		expect(flow.draft!.knownEntry(2)).toBe(partner);
		expect(flow.draft!.isMember(2)).toBe(false);
		expect(flow.isDirty).toBe(false);
	});
});

describe('editing a partner that a proposal joined', () => {
	it('pins the pair as a pick first, and sends the edit with it', async () => {
		const flow = await setup();
		flow.setText(2, 'note', 'for the trip');
		expect(flow.draft!.pairingEdit(1)).toMatchObject({ mode: 'pick', partnerEntryId: 2 });
		expect(flow.isDirty).toBe(true);
		await previewed();
		expect(lastRequest().entries).toEqual([
			{ id: 1, pairing: { mode: 'pick', partner_entry_id: 2 } },
			{ id: 2, note: 'for the trip' }
		]);
	});

	it('is clean again once the edit is taken back', async () => {
		const flow = await setup();
		flow.setText(2, 'note', 'x');
		flow.setText(2, 'note', '');
		expect(flow.draft!.pairingEdit(1)).toBeUndefined();
		expect(flow.isDirty).toBe(false);
	});

	it('pins for a tag, a split and a removal as well', async () => {
		const flow = await setup();
		flow.toggleTag(2, 9);
		expect(flow.draft!.pairingEdit(1)).toBeDefined();
		flow.discard();
		await settle();
		const id = flow.addSplit(2);
		expect(id).toBe(-1);
		expect(flow.draft!.pairingEdit(1)).toBeDefined();
		flow.discard();
		await settle();
		flow.removeSplit(3);
		expect(flow.draft!.removed).toEqual([3]);
		expect(flow.draft!.pairingEdit(1)).toBeDefined();
	});

	it('changes nothing for an entry the preview does not join, and pins nothing for a refused change', async () => {
		const flow = await setup();
		const before = flow.draft;
		flow.setText(99, 'note', 'x');
		flow.setType(2, 'flow'); // the type of a partner is the pair’s
		expect(flow.draft).toBe(before);
		expect(flow.addSplit(99)).toBeNull();
	});

	it('does not pin for a leg the user has paired elsewhere itself', async () => {
		const flow = await setup();
		flow.pickPartner(1, 4);
		const before = flow.draft;
		flow.setText(2, 'note', 'x');
		expect(flow.draft).toBe(before);
	});

	it('takes the whole draft back with Reset, the pin included', async () => {
		const flow = await setup();
		flow.setText(2, 'note', 'x');
		flow.discard();
		await settle();
		expect(flow.draft!.pairingEdit(1)).toBeUndefined();
		expect(lastRequest().entries).toEqual([]);
	});

	it('weighs a field edit of a partner against what the partner stores', async () => {
		const flow = await setup();
		flow.setField(2, 'category', 10);
		await previewed();
		expect(flow.isDirty).toBe(true); // the preview ends in another category than the stored one
		vi.mocked(previewUnit).mockImplementation(async () => joinedPreview());
		flow.discard();
		await settle();
		flow.setField(2, 'category', 10);
		await previewed();
		expect(flow.isDirty).toBe(false); // the preview says nothing changes
	});
});

describe('typing the amount of a split on a picked partner', () => {
	it('is taken: the source of the split is known, and the commit is not held back', async () => {
		const flow = await setup();
		flow.pickPartner(1, 2);
		await settle();
		const id = flow.addSplit(2)!;
		flow.setAmountText(id, '1.00');
		expect(flow.amountErrors).toEqual({});
		flow.applyAmountText(id);
		expect(flow.draft!.edit(id).amount).toBe(100);
		await settle();
		await previewed();
		expect(flow.commitReason).toBeNull();
	});

	it('says what is wrong with an amount that is none, on the partner’s split too', async () => {
		const flow = await setup();
		flow.pickPartner(1, 2);
		await settle();
		const id = flow.addSplit(2)!;
		flow.setAmountText(id, 'abc');
		expect(flow.amountErrors[id]).toBeTruthy();
		expect(flow.commitReason).toBe('An amount is not valid.');
	});

	it('splits off the difference of a pair on the larger leg, a partner’s included', async () => {
		const flow = await setup();
		flow.setText(2, 'note', 'x'); // pinned: the partner is part of the draft
		await previewed();
		const unequal = {
			code: 'pair_unequal',
			entry_id: 1,
			field: null,
			detail: { partner: 2, difference: 100 },
			suggested_split: { source_entry_id: 2, amount: { amount: 100, currency: 'EUR' } }
		};
		flow.splitOffDifference(unequal as never);
		expect(flow.draft!.splits).toEqual([expect.objectContaining({ sourceEntryId: 2 })]);
		expect(flow.draft!.edit(flow.draft!.splits[0].id).amount).toBe(100);
	});
});

describe('what leaves the unit', () => {
	it('says which entries lost their changes, and clears the line with the next change', async () => {
		const flow = await setup();
		flow.setText(2, 'note', 'x');
		await previewed();
		flow.pickPartner(1, 4);
		expect(flow.notice).toEqual({
			kind: 'info',
			text: 'Your changes to The partner were dropped: it is no longer part of this unit.'
		});
		expect(flow.draft!.edit(2)).toEqual({ fields: {} });
		flow.setText(1, 'note', 'y');
		expect(flow.notice).toBeNull();
	});

	it('stays after the fee split a pick brings, and goes with the next edit of the user', async () => {
		const flow = await setup();
		flow.setText(2, 'note', 'x');
		await previewed();
		vi.mocked(previewUnit).mockImplementation(async (request) => {
			const out = answer(request);
			if (
				request.entries?.some((e) => e.pairing?.mode === 'pick' && e.pairing.partner_entry_id === 4)
			) {
				out.problems = [
					{
						code: 'pair_unequal',
						entry_id: 1,
						field: null,
						detail: { partner: 4, difference: 65 },
						suggested_split: { source_entry_id: 1, amount: { amount: -6500, currency: 'EUR' } }
					} as never
				];
			}
			return out;
		});
		flow.pickPartner(1, 4);
		const dropped = {
			kind: 'info',
			text: 'Your changes to The partner were dropped: it is no longer part of this unit.'
		};
		expect(flow.notice).toEqual(dropped);
		await previewed(); // the preview arrives: the fee split is applied
		expect(flow.draft!.splits.length).toBe(1);
		expect(flow.notice).toEqual(dropped);
		await previewed(); // and the preview after the split
		expect(flow.notice).toEqual(dropped);
		flow.setText(1, 'note', 'y');
		expect(flow.notice).toBeNull();
	});

	it('stays after an exact pick as well', async () => {
		const flow = await setup();
		flow.setText(2, 'note', 'x');
		await previewed();
		flow.pickPartner(1, 4);
		await previewed();
		await previewed();
		expect(flow.notice?.text).toContain('were dropped');
	});

	it('names several entries', async () => {
		const flow = await setup();
		flow.setText(2, 'note', 'x');
		flow.toggleTag(3, 9);
		await previewed();
		flow.clearPairing(1);
		expect(flow.notice?.text).toBe(
			'Your changes to The partner, The sibling were dropped: they are no longer part of this unit.'
		);
	});

	it('is silent when nothing was drafted on the partner', async () => {
		const flow = await setup();
		flow.pickPartner(1, 2);
		flow.pickPartner(1, 4);
		expect(flow.notice).toBeNull();
	});
});

describe('the commit', () => {
	it('carries the versions of the whole unit the preview held, the partner’s included', async () => {
		const flow = await setup();
		flow.setText(2, 'note', 'x');
		await previewed();
		await flow.commit();
		const request = vi.mocked(commitUnit).mock.calls[0][0] as UnitDraftRequest;
		expect(request.versions).toEqual({ 1: 3, 2: 7, 3: 8 });
		expect(request.entries).toEqual([
			{ id: 1, pairing: { mode: 'pick', partner_entry_id: 2 } },
			{ id: 2, note: 'x' }
		]);
	});

	it('tells a refused change of a partner’s pair in words', async () => {
		const flow = await setup();
		flow.setText(2, 'note', 'x');
		await previewed();
		vi.mocked(commitUnit).mockRejectedValue(
			new ApiError(422, 'invalid_draft', 'x', { code: 'pair_fixed' })
		);
		await flow.commit();
		expect(flow.notice).toMatchObject({ kind: 'error' });
		expect(flow.notice?.text).toContain('the pair’s');
		expect(flow.draft!.edit(2).note).toBe('x'); // nothing is thrown away
	});

	it('keeps what is drafted on the partner when the unit moved under it, and reads the partner again', async () => {
		const flow = await setup();
		flow.setText(2, 'note', 'x');
		await previewed();
		vi.mocked(commitUnit).mockRejectedValue(new ApiError(409, 'unit_moved', 'x', null));
		const again = unit({
			anchor_entry_id: 1,
			entries: [entry({ ...loaded.entries[0], version: 4 })]
		});
		vi.mocked(getUnit).mockResolvedValue(again);
		const changed = entry({ ...partner, version: 8, description: 'Changed elsewhere' });
		vi.mocked(previewUnit).mockImplementation(async (request) => {
			const out = answer(request);
			out.entries = [out.entries[0], changed, out.entries[2]];
			out.versions = { ...out.versions, 2: 8 };
			return out;
		});
		await flow.commit();
		await settle();
		expect(flow.notice).toMatchObject({ kind: 'conflict' });
		expect(flow.draft!.edit(2).note).toBe('x');
		expect(flow.draft!.pairingEdit(1)).toMatchObject({ mode: 'pick', partnerEntryId: 2 });
		expect(lastRequest().entries).toEqual([
			{ id: 1, pairing: { mode: 'pick', partner_entry_id: 2 } },
			{ id: 2, note: 'x' }
		]);
		// the next preview’s entries replace what is known of the partner
		expect(flow.draft!.knownEntry(2)?.description).toBe('Changed elsewhere');
	});
});
