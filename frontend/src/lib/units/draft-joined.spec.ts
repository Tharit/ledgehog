import { describe, expect, it } from 'vitest';
import { entry } from '#lib/ledger/fixtures.js';
import { Draft } from './draft.js';
import { joinedScene, unit } from './fixtures.js';

const { leg, partner, sibling, other, loaded } = joinedScene();
const HOW = { proposal: true, exact: true };

/** the unit as loaded, and every entry of the joined preview known */
const known = () => Draft.of(loaded).know([leg, partner, sibling, other]);
/** the pair of a proposal pinned, so the partner's side can be edited */
const pinned = () => known().pinPick(1, 2, HOW);

describe('the entries a draft can say anything about (E)', () => {
	it('is the unit as loaded: what is known of a preview is not part of it', () => {
		const draft = known();
		expect([...draft.members]).toEqual([1]);
		expect(draft.isLoaded(1)).toBe(true);
		expect(draft.isLoaded(2)).toBe(false);
		expect(draft.isJoined(2)).toBe(true);
		expect(draft.isJoined(1)).toBe(false);
		expect(draft.knownEntry(2)).toBe(partner);
	});

	it('adds every entry of the sources a pick pairs with, and nothing of another source', () => {
		const draft = known().pickPartner(1, 2);
		expect([...draft.members].sort()).toEqual([1, 2, 3]);
		expect(draft.isMember(4)).toBe(false);
		expect(known().pickPartner(1, 4).isMember(3)).toBe(false);
	});

	it('counts a split row whose source is in E, and no other', () => {
		const draft = pinned().addSplit(2);
		expect(draft.isMember(-1)).toBe(true);
		expect(draft.isMember(-9)).toBe(false);
	});

	it('learns only of ids it does not know yet, so what is known is stable', () => {
		const draft = known();
		const later = entry({ ...partner, description: 'Changed since' });
		expect(draft.know([later])).toBe(draft);
		expect(draft.know([later]).knownEntry(2)?.description).toBe('Incoming');
		expect(draft.know([later], true).knownEntry(2)?.description).toBe('Changed since');
		// the loaded entries are never replaced by a preview
		expect(draft.know([entry({ ...leg, description: 'x' })], true).knownEntry(1)).toBe(leg);
	});
});

describe('what the draft refuses outside E', () => {
	it('takes no edit of an entry the preview only shows', () => {
		const draft = known();
		expect(draft.setField(2, 'category', 10)).toBe(draft);
		expect(draft.setDescription(2, 'x')).toBe(draft);
		expect(draft.setNote(2, 'x')).toBe(draft);
		expect(draft.toggleTag(2, 9)).toBe(draft);
		expect(draft.addSplit(2)).toBe(draft);
		expect(draft.removeSplit(3)).toBe(draft);
		expect(draft.setSplitAmount(3, 50)).toBe(draft);
		expect(draft.toRequest().entries).toEqual([]);
	});

	it('takes them once a pick made the entry a member', () => {
		const draft = known().pickPartner(1, 2);
		expect(draft.setNote(2, 'x').edit(2).note).toBe('x');
		expect(draft.toggleTag(3, 9).tagEdit(3)).toEqual({ add: [9], remove: [] });
		expect(draft.removeSplit(3).removed).toEqual([3]);
		expect(draft.addSplit(2).splits).toHaveLength(1);
	});

	it('re-pairs a leg of the unit as loaded only', () => {
		const picked = known().pickPartner(1, 2);
		expect(picked.pickPartner(2, 4)).toBe(picked);
		expect(picked.pickCounterLeg(2)).toBe(picked);
		expect(picked.reresolvePairing(2)).toBe(picked);
		expect(picked.clearPairing(2)).toBe(picked);
		expect(picked.pickPartner(1, 4).pairingEdit(1)).toEqual({ mode: 'pick', partnerEntryId: 4 });
	});

	it('leaves the type and the counter-account of a partner to the pair', () => {
		const draft = pinned();
		expect(draft.setField(2, 'type', 'flow')).toBe(draft);
		expect(draft.setField(2, 'counter_account', 3)).toBe(draft);
		expect(draft.resetField(2, 'type')).toBe(draft);
		expect(draft.convertToFlow(2)).toBe(draft);
		expect(draft.convertToTransfer(2, 3)).toBe(draft);
		// its category and payee stay open
		expect(draft.setField(2, 'category', 10).fieldEdit(2, 'category')).toMatchObject({
			mode: 'fixed'
		});
	});
});

describe('pinning the pick of a proposal', () => {
	it('pairs the leg with the partner as a pick, flagged as pinned, and makes the partner a member', () => {
		const draft = pinned();
		expect(draft.pairingEdit(1)).toEqual({ mode: 'pick', partnerEntryId: 2, pinned: HOW });
		expect(draft.isMember(2)).toBe(true);
		expect(draft.isMember(3)).toBe(true);
	});

	it('is the pick of the proposal in the request, and no choice of the user’s', () => {
		const draft = pinned().setNote(2, 'x');
		expect(draft.toRequest().entries).toEqual([
			{ id: 1, pairing: { mode: 'pick', partner_entry_id: 2 } },
			{ id: 2, note: 'x' }
		]);
		expect(pinned().isDirty).toBe(false);
		expect(pinned().hasOtherChanges).toBe(false);
		expect(pinned().hasPick).toBe(false);
		expect(known().pickPartner(1, 2).hasPick).toBe(true);
	});

	it('is only made while the leg has no pairing edit of its own, and is made once', () => {
		const own = known().pickPartner(1, 4);
		expect(own.pinPick(1, 2, HOW)).toBe(own);
		const counter = known().pickCounterLeg(1);
		expect(counter.pinPick(1, 2, HOW)).toBe(counter);
		const once = pinned();
		expect(once.pinPick(1, 2, HOW)).toBe(once);
		// a partner nobody told the draft about cannot be pinned, nor a leg of the partner's side
		expect(Draft.of(loaded).pinPick(1, 2, HOW).pairingEdit(1)).toBeUndefined();
		expect(known().pinPick(2, 1, HOW).pairingEdit(2)).toBeUndefined();
	});

	it('goes when nothing is drafted on the partner any more', () => {
		const edited = pinned().setNote(2, 'x').toggleTag(3, 9);
		expect(edited.pairingEdit(1)).toBeDefined();
		const half = edited.setNote(2, null);
		expect(half.pairingEdit(1)).toBeDefined(); // the tag change is still there
		const clean = half.toggleTag(3, 9);
		expect(clean.pairingEdit(1)).toBeUndefined();
		expect(clean.toRequest().entries).toEqual([]);
	});

	it('stays through edits of other entries', () => {
		const draft = pinned().setNote(2, 'x').setNote(1, 'mine');
		expect(draft.pairingEdit(1)).toMatchObject({ mode: 'pick', pinned: HOW });
		expect(draft.edit(1).note).toBe('mine');
	});
});

describe('what leaves the unit takes its drafts along', () => {
	const drafted = () => pinned().setNote(2, 'x').toggleTag(2, 9).addSplit(2).removeSplit(3);

	it('drops them when the leg is paired with another partner, and says which entries', () => {
		const next = drafted().pickPartner(1, 4);
		expect(next.dropped).toEqual([2, 3]);
		expect(next.toRequest()).toMatchObject({
			entries: [{ id: 1, pairing: { mode: 'pick', partner_entry_id: 4 } }],
			removed_entry_ids: []
		});
		expect(next.splits).toEqual([]);
		expect(next.isMember(2)).toBe(false);
		// the next change forgets what was dropped
		expect(next.setNote(1, 'y').dropped).toEqual([]);
	});

	it.each([
		['clearing the pairing', (d: Draft) => d.clearPairing(1)],
		['asking for a counter-leg', (d: Draft) => d.pickCounterLeg(1)],
		['re-resolving the pairing', (d: Draft) => d.reresolvePairing(1)],
		['re-resolving the unit', (d: Draft) => d.reresolve()],
		['changing the leg’s type', (d: Draft) => d.setField(1, 'type', 'flow')],
		['changing the leg’s counter-account', (d: Draft) => d.setField(1, 'counter_account', 3)],
		['converting the leg to a flow', (d: Draft) => d.convertToFlow(1)],
		['picking the partner again as a choice', (d: Draft) => d.pickPartner(1, 4)]
	])('drops them by %s', (_name, change) => {
		const next = change(drafted());
		expect(next.dropped).toEqual([2, 3]);
		expect(next.edit(2)).toEqual({ fields: {} });
		expect(next.removed).toEqual([]);
	});

	it('keeps them when the leg is picked to the very partner it was pinned to', () => {
		const next = drafted().pickPartner(1, 2);
		expect(next.dropped).toEqual([]);
		expect(next.edit(2).note).toBe('x');
		expect(next.pairingEdit(1)).toEqual({ mode: 'pick', partnerEntryId: 2 }); // now the user’s own pick
		expect(next.hasPick).toBe(true);
	});

	it('keeps what is drafted on a loaded entry that leaves: it is committed with it', () => {
		const partnered = unit({
			anchor_entry_id: 1,
			entries: [
				entry({ ...leg, counterpart_entry_id: 9 }),
				entry({
					id: 9,
					version: 5,
					unit_key: 1,
					type: 'transfer',
					account_id: 3,
					amount: { amount: 4900, currency: 'EUR' },
					source_transaction_id: 12,
					counterpart_entry_id: 1
				})
			]
		});
		const draft = Draft.of(partnered).know([partner, other]);
		const edited = draft.setNote(9, 'stays').toggleTag(9, 5).addSplit(9);
		const repicked = edited.pickPartner(1, 4);
		expect(repicked.dropped).toEqual([]);
		expect(repicked.edit(9).note).toBe('stays');
		expect(repicked.splits).toHaveLength(1);
		expect(repicked.isMember(9)).toBe(true);
	});

	it('keeps what is drafted on an entry of the unit as loaded when the pick is taken back', () => {
		const draft = known().pickPartner(1, 2).setNote(1, 'mine').setNote(2, 'x');
		const next = draft.clearPairing(1);
		expect(next.dropped).toEqual([2]);
		expect(next.edit(1).note).toBe('mine');
	});
});

describe('what the draft knows of a partner', () => {
	it('toggles tags relative to what the partner stores', () => {
		const draft = pinned();
		expect(draft.effectiveTagIds(2)).toEqual([7]);
		const off = draft.toggleTag(2, 7);
		expect(off.tagEdit(2)).toEqual({ add: [], remove: [7] });
		expect(off.effectiveTagIds(2)).toEqual([]);
		expect(off.toggleTag(2, 7).tagEdit(2)).toBeUndefined();
		expect(draft.toggleTag(2, 9).tagEdit(2)).toEqual({ add: [9], remove: [] });
	});

	it('takes an edit that equals what is stored for none', () => {
		const draft = pinned();
		expect(draft.setDescription(2, 'Incoming')).toBe(draft);
		expect(draft.setNote(2, '')).toBe(draft);
		expect(draft.setSplitAmount(3, 100)).toBe(draft);
		const stored = entry({ ...partner, category_id: 10, payee_id: 20 });
		const withCategory = Draft.of(loaded).know([leg, stored, sibling]).pinPick(1, 2, HOW);
		expect(withCategory.setField(2, 'category', 10)).toBe(withCategory);
		expect(withCategory.setField(2, 'category', 11).fieldEdit(2, 'category')).toBeDefined();
	});

	it('starts a split row from the tags of the ORIGINAL of the source, as the server does', () => {
		const draft = pinned().toggleTag(3, 9); // the sibling got a tag of its own
		const split = draft.addSplit(3); // splitting the sibling
		expect(split.splits[0]).toMatchObject({ sourceEntryId: 3, tags: [7] }); // the original (2) stores [7]
		expect(split.effectiveTagIds(-1)).toEqual([7]);
		// what the original shows now (its draft tags) is what the row starts with, the difference sent
		const tagged = pinned().toggleTag(2, 9).addSplit(2);
		expect(tagged.effectiveTagIds(-1)).toEqual([7, 9]);
		expect(tagged.tagEdit(-1)).toEqual({ add: [9], remove: [] });
	});

	it('carries a split of the partner’s source in the request, with the source entry', () => {
		const draft = pinned().addSplit(2).setSplitAmount(-1, 100);
		expect(draft.toRequest().entries).toEqual([
			{ id: 1, pairing: { mode: 'pick', partner_entry_id: 2 } },
			{ id: -1, source_entry_id: 2, amount: 100 }
		]);
	});
});

describe('rebase over the unit as it is now', () => {
	it('keeps what is drafted on the partner while it is still part of the unit', () => {
		const draft = pinned().setNote(2, 'x').addSplit(2).setSplitAmount(-1, 100);
		const again = unit({ anchor_entry_id: 1, entries: [entry({ ...leg, version: 4 })] });
		const next = draft.rebase(again);
		expect(next.versions).toEqual({ 1: 4 });
		expect(next.edit(2).note).toBe('x');
		expect(next.splits).toHaveLength(1);
		expect(next.edit(-1).amount).toBe(100);
		expect(next.pairingEdit(1)).toMatchObject({ mode: 'pick', pinned: HOW });
		expect(next.isMember(2)).toBe(true);
	});

	it('drops them when the leg that joined the partner is gone', () => {
		const draft = pinned().setNote(2, 'x');
		const moved = unit({
			anchor_entry_id: 9,
			entries: [entry({ id: 9, version: 1, unit_key: 9, source_transaction_id: 20 })]
		});
		const next = draft.rebase(moved);
		expect(next.edit(2)).toEqual({ fields: {} });
		expect(next.pairingEdit(1)).toBeUndefined();
		expect(next.anchorId).toBe(9);
	});

	it('measures what is drafted on a partner against what is stored now', () => {
		const draft = pinned().setNote(2, 'x').setDescription(2, 'Newer');
		const fresh = entry({ ...partner, note: 'x', description: 'Newer', version: 9 });
		const next = draft.rebase(loaded).know([fresh], true);
		expect(next.knownEntry(2)?.version).toBe(9);
		expect(next.edit(2)).toEqual({ fields: {} }); // both became what is stored
		expect(next.pairingEdit(1)).toBeUndefined(); // nothing left to pin for
	});
});
