import { describe, expect, it } from 'vitest';
import { entry } from '#lib/ledger/fixtures.js';
import { Draft } from './draft.js';
import { knownRules } from './evidence.js';
import { fieldOut, joinedScene, preview, previewRowOf, transferOut, unit } from './fixtures.js';
import { groupsOf, partnerDirections } from './groups.js';
import { entryViews, type EntryView } from './view.js';

const rules = knownRules(() => undefined);
const HOW = { proposal: true, exact: true };
const { leg, partner, sibling, other, loaded, joinedPreview } = joinedScene();

function viewsOf(draft: Draft, shown = joinedPreview(), stale = false): EntryView[] {
	return entryViews({ unit: loaded, draft, preview: shown, rules, locale: 'en', stale });
}
const known = () => Draft.of(loaded).know([leg, partner, sibling, other]);
const byId = (views: EntryView[], id: number) => views.find((v) => v.id === id)!;

describe('the entries of the partner’s side, as known', () => {
	it('shows a joined partner as stored: its tags, its original, its account', () => {
		const views = viewsOf(known());
		expect(views.map((v) => v.id)).toEqual([1, 2, 3]);
		const p = byId(views, 2);
		expect(p.stored).toBe(partner);
		expect(p.joined).toBe(true);
		expect(p.original).toBe(true);
		expect(p.accountId).toBe(2);
		expect(p.tagIds).toEqual([7]);
		expect(byId(views, 3).original).toBe(false);
		expect(byId(views, 3).inSplit).toBe(true);
		expect(byId(views, 1).joined).toBe(false);
	});

	it('gives a split of a partner the account and the currency of its source, without a preview row of it', () => {
		const draft = known().pickPartner(1, 2).addSplit(2).setSplitAmount(-1, 100);
		// the preview has not answered for the split yet: it is the draft's alone
		const views = viewsOf(draft);
		const split = byId(views, -1);
		expect(split.accountId).toBe(2);
		expect(split.sourceId).toBe(6);
		expect(split.amount).toEqual({ amount: 100, currency: 'EUR' });
		expect(split.accountId).not.toBe(0);
	});

	it('keeps a pending split of a partner’s source in the partner’s group (no account 0)', () => {
		const draft = known().pickPartner(1, 2).addSplit(2);
		const views = viewsOf(draft);
		const groups = groupsOf(views, [...draft.knownEntries.values()]);
		const theirs = groups.find((g) => g.sourceId === 6)!;
		expect(theirs.views.map((v) => v.id)).toEqual([2, 3, -1]);
		expect(theirs.header.accountId).toBe(2);
		expect(theirs.strip).not.toBeNull();
		expect(groups.every((g) => g.header.accountId !== null)).toBe(true);
	});

	it('draws the group of a joined partner from what is known of it', () => {
		const draft = known().pinPick(1, 2, HOW);
		const groups = groupsOf(viewsOf(draft), [...draft.knownEntries.values()]);
		expect(groups.map((g) => g.sourceId)).toEqual([6, 5]);
		const theirs = groups[0];
		expect(theirs.header).toMatchObject({ accountId: 2, bookedOn: '2026-10-09' });
		expect(theirs.strip?.entryIds).toEqual([2, 3]);
		expect(theirs.splitEntryId).toBe(2);
		expect(partnerDirections(groups).get(1)).toBe('above');
	});

	it('offers the rule from a partner’s change of what a rule set (the stored key is its own)', () => {
		const draft = known().pinPick(1, 2, HOW).setField(2, 'payee', 99);
		const shown = joinedPreview();
		shown.rows[1].fields.payee = fieldOut(99, { pass: 'user' });
		expect(byId(viewsOf(draft, shown), 2).fields.payee.changedFromRule).toBe(true);
		expect(byId(viewsOf(known().pinPick(1, 2, HOW)), 2).fields.payee.changedFromRule).toBe(false);
	});

	it('shows the tags of a joined partner while the preview is stale, not an empty set', () => {
		const draft = known().pinPick(1, 2, HOW).toggleTag(2, 9);
		const views = viewsOf(draft, joinedPreview(), true);
		expect(byId(views, 2).tagIds).toEqual([7, 9]);
		expect(byId(viewsOf(known(), joinedPreview(), true), 2).tagIds).toEqual([7]);
	});
});

describe('a leg whose pair the client pinned', () => {
	it('is no pick of the user’s, and keeps the proposal’s words', () => {
		const views = viewsOf(known().pinPick(1, 2, HOW));
		const l = byId(views, 1);
		expect(l.pinned).toEqual(HOW);
		expect(l.picked).toBe(false);
		expect(l.pairEvidence).toEqual({ text: 'proposed: exact match', proposal: true });
		expect(byId(views, 2).pairEvidence).toEqual({ text: 'proposed: exact match', proposal: true });
	});

	it('words a pinned pair of settling’s as matched automatically', () => {
		const scene = joinedScene(false);
		const draft = Draft.of(scene.loaded)
			.know([scene.leg, scene.partner, scene.sibling])
			.pinPick(1, 2, { proposal: false, exact: false });
		const views = entryViews({
			unit: scene.loaded,
			draft,
			preview: scene.joinedPreview(),
			rules,
			locale: 'en'
		});
		expect(byId(views, 1).pairEvidence).toEqual({ text: 'matched automatically', proposal: false });
		expect(byId(views, 2).pairEvidence).toEqual({ text: 'matched automatically', proposal: false });
	});

	it('shows the proposal’s words on the partner before anything is pinned', () => {
		const views = viewsOf(known());
		expect(byId(views, 2).pairEvidence).toEqual({
			text: 'proposed: exact match',
			proposal: true
		});
		expect(byId(views, 2).pinned).toBeNull();
	});

	it('says picked by you of a partner the user picked', () => {
		const views = viewsOf(known().pickPartner(1, 2));
		expect(byId(views, 1).picked).toBe(true);
		expect(byId(views, 2).pairEvidence).toEqual({ text: 'picked by you', proposal: false });
	});
});

describe('a stale preview over a draft that re-paired the leg', () => {
	it('hides the entries the old partner brought, and the split rows of its source', () => {
		const shown = joinedPreview();
		// the old answer still lists a split row of the partner's source
		shown.rows.push(
			previewRowOf(
				entry({
					id: -1,
					type: 'flow',
					account_id: 2,
					source_transaction_id: 6,
					amount: { amount: 50, currency: 'EUR' }
				}),
				{ original: false, version: null }
			)
		);
		const repaired = known().pinPick(1, 2, HOW).setNote(2, 'x').addSplit(2).pickPartner(1, 4);
		expect(repaired.splits).toEqual([]);
		expect(viewsOf(repaired, shown, true).map((v) => v.id)).toEqual([1]);
		// once the preview is the draft's own, it is what it says
		expect(viewsOf(repaired, joinedPreview(), false).map((v) => v.id)).toEqual([1, 2, 3]);
	});

	it('keeps them while the leg’s pick or pin still pairs with that source', () => {
		const pinned = known().pinPick(1, 2, HOW).setNote(2, 'x');
		expect(viewsOf(pinned, joinedPreview(), true).map((v) => v.id)).toEqual([1, 2, 3]);
		const picked = known().pickPartner(1, 3);
		expect(viewsOf(picked, joinedPreview(), true).map((v) => v.id)).toEqual([1, 2, 3]);
	});

	it('shows no orphan split block for a split whose row left the unit', () => {
		const shown = joinedPreview();
		shown.rows.push(
			previewRowOf(entry({ id: -1, type: 'flow', account_id: 2, source_transaction_id: 6 }), {
				original: false,
				in_unit: false,
				version: null
			})
		);
		const draft = known().pinPick(1, 2, HOW).addSplit(2);
		expect(viewsOf(draft, shown).map((v) => v.id)).not.toContain(-1);
		// a split the preview has no row for at all is shown: it is the draft's alone
		expect(viewsOf(draft, joinedPreview()).map((v) => v.id)).toContain(-1);
	});
});

describe('the unit as loaded', () => {
	it('is not joined: both legs of a stored pair are the side the panel was opened on', () => {
		const mine = entry({
			id: 1,
			unit_key: 1,
			type: 'transfer',
			account_id: 1,
			source_transaction_id: 5,
			counterpart_entry_id: 2
		});
		const theirs = entry({
			id: 2,
			unit_key: 1,
			type: 'transfer',
			account_id: 2,
			source_transaction_id: 6,
			counterpart_entry_id: 1
		});
		const pair = unit({ anchor_entry_id: 1, entries: [mine, theirs] });
		const views = entryViews({
			unit: pair,
			draft: Draft.of(pair),
			preview: preview(pair, {
				rows: [
					previewRowOf(mine, { transfer: transferOut({ state: 'paired' }) }),
					previewRowOf(theirs, { transfer: transferOut({ state: 'paired' }) })
				]
			}),
			rules,
			locale: 'en'
		});
		expect(views.map((v) => v.joined)).toEqual([false, false]);
	});
});
