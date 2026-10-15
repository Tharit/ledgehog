// What the panel says of a transfer leg's partner (spec §5.7, patterns §4.3, §6): its state in
// plain words, the offers in the order the server gave them, one short hint per offer and the
// partner the preview shows (a pair, or a proposal). Pure: it words what the server said and
// sorts nothing (the server's order is the offers' order).
import { formatDate, formatMoney } from '#lib/format/index.js';
import type { Lookups } from '#lib/ledger/lookups.js';
import type { Money } from '#lib/types/domain.js';
import type { PairingEdit } from './draft.js';
import type { UnitOffer, UnitTransfer } from './types.js';

export type OfferGroupKey = 'open' | 'paired_elsewhere' | 'new';

export type OfferGroup = { key: OfferGroupKey; label: string; offers: UnitOffer[] };

const GROUP_LABEL: Readonly<Record<OfferGroupKey, string>> = {
	open: 'Open',
	paired_elsewhere: 'Paired elsewhere',
	new: 'New'
};

/**
 * The offers a leg can be given now, grouped as the server ordered them: open offers, then legs
 * paired elsewhere, then the counter-leg a commit would create ("New"). Within a group nothing is
 * sorted.
 */
export function offerGroups(offers: readonly UnitOffer[]): OfferGroup[] {
	const keyOf = (offer: UnitOffer): OfferGroupKey | null =>
		offer.kind === 'open_leg' || offer.kind === 'untyped_entry'
			? 'open'
			: offer.kind === 'paired_elsewhere'
				? 'paired_elsewhere'
				: offer.kind === 'counter_leg'
					? 'new'
					: null;
	const groups: OfferGroup[] = [];
	for (const key of ['open', 'paired_elsewhere', 'new'] as const) {
		const members = offers.filter((offer) => keyOf(offer) === key);
		if (members.length > 0) groups.push({ key, label: GROUP_LABEL[key], offers: members });
	}
	return groups;
}

/** The offers that are shown. */
export function shownOffers(offers: readonly UnitOffer[]): UnitOffer[] {
	return offerGroups(offers).flatMap((g) => g.offers);
}

type Words = { lookups: Lookups; locale: string };

const accountName = ({ lookups }: Words, id: number) =>
	lookups.accounts.get(id)?.name ?? `Account ${id}`;

/** "Savings · 12 Oct 2026 · 50.00 EUR": a leg in a few words. */
export function legWords(
	leg: { account_id: number; booked_on: string; amount: Money | null },
	words: Words
): string {
	const parts = [accountName(words, leg.account_id), formatDate(leg.booked_on, words.locale)];
	if (leg.amount) {
		parts.push(
			formatMoney(leg.amount.amount, leg.amount.currency, {
				locale: words.locale,
				showCurrency: true,
				showPlus: false
			})
		);
	}
	return parts.join(' · ');
}

/** The short hints of an offer: what picking it will do (the real consequences follow the pick). */
export function offerHints(
	offer: UnitOffer,
	transfer: Pick<UnitTransfer, 'partner'>,
	words: Words
): string[] {
	const hints: string[] = [];
	const { effect } = offer;
	if (offer.kind === 'counter_leg') {
		const leg = offer.counter_leg;
		const amount = leg?.amount ?? offer.amount;
		if (leg?.needs_received_amount) hints.push('You enter the amount received');
		else if (amount) {
			const text = formatMoney(Math.abs(amount.amount), amount.currency, {
				locale: words.locale,
				showCurrency: true,
				showPlus: false
			});
			hints.push(
				`Receives ${text} on ${formatDate(leg?.booked_on ?? offer.booked_on, words.locale)}`
			);
		}
	}
	if (effect.types_as_transfer) hints.push('will be typed as a transfer');
	if (effect.fee) {
		const { difference } = effect.fee;
		const text = formatMoney(Math.abs(difference.amount), difference.currency, {
			locale: words.locale,
			showPlus: false
		});
		hints.push(`differs by ${text}: the difference becomes a separate flow`);
	}
	if (effect.breaks_pair_with.length > 0) {
		// the legs a pick would unpair, named where the offer or the leg's own partner says what they are
		const known = new Map<number, string>();
		if (transfer.partner) known.set(transfer.partner.entry_id, legWords(transfer.partner, words));
		if (offer.paired_with)
			known.set(offer.paired_with.entry_id, legWords(offer.paired_with, words));
		const names = effect.breaks_pair_with.map((id) => known.get(id) ?? 'its current partner');
		hints.push(`breaks the pair with ${[...new Set(names)].join(', ')}`);
	}
	return hints;
}

/** The offer the server proposes for the leg, when it is one of the offers shown. */
export function proposedOffer(transfer: UnitTransfer): UnitOffer | null {
	const id = transfer.proposed_pick?.entry_id;
	if (id !== undefined) {
		return transfer.offers.find((o) => o.entry_id === id) ?? null;
	}
	return transfer.offers.find((o) => o.proposed && o.entry_id !== null) ?? null;
}

/** The counter-leg offer of a leg, when it has one. */
export function counterLegOffer(transfer: UnitTransfer): UnitOffer | null {
	return transfer.offers.find((o) => o.kind === 'counter_leg') ?? null;
}

/**
 * The other side a commit creates for a leg (spec §5.7): picked in the draft, or proposed by the
 * server and effective in the preview. Null when the leg's partner is something else. The synthetic
 * row the preview shows (a negative id) is the partner then; before it exists (an amount still to
 * enter) the offer says what would be created.
 */
export type PendingCounterLeg = {
	accountId: number;
	bookedOn: string;
	/** null: not known yet (a cross-currency leg whose amount received is still to enter) */
	amount: Money | null;
	/** the server proposed it: shown as a proposal, accepted on commit */
	proposal: boolean;
	/** the user enters the amount received (a cross-currency leg) */
	needsReceivedAmount: boolean;
	/** what the draft holds as the amount received (unsigned minor units) */
	receivedAmount: number | null;
};

export function pendingCounterLeg(
	transfer: UnitTransfer,
	pairing: PairingEdit | null | undefined
): PendingCounterLeg | null {
	const picked = pairing?.mode === 'counter_leg' ? pairing : null;
	const proposed = !picked && pairing?.mode !== 'pick' && transfer.proposed_counter_leg;
	if (!picked && !proposed) return null;
	const offer = counterLegOffer(transfer);
	const synthetic = transfer.partner && transfer.partner.entry_id < 0 ? transfer.partner : null;
	const accountId = synthetic?.account_id ?? offer?.account_id;
	if (accountId === undefined) return null;
	const bookedOn = synthetic?.booked_on ?? offer?.counter_leg?.booked_on ?? offer?.booked_on;
	if (bookedOn === undefined) return null;
	const receivedAmount = picked?.receivedAmount ?? null;
	return {
		accountId,
		bookedOn,
		amount: synthetic?.amount ?? offer?.counter_leg?.amount ?? offer?.amount ?? null,
		proposal: proposed,
		needsReceivedAmount:
			(offer?.counter_leg?.needs_received_amount ?? false) || receivedAmount !== null,
		receivedAmount
	};
}

/** The partner a leg shows: a pair's partner, else the proposal the preview applies. */
export type ShownPartner = {
	account_id: number;
	booked_on: string;
	amount: Money | null;
	description: string | null;
	/** the server proposed it: shown as a proposal, no pair is made until the commit */
	proposal: boolean;
	exact: boolean;
};

export function shownPartner(transfer: UnitTransfer): ShownPartner | null {
	const proposed = transfer.proposed_pick?.entry_id ?? null;
	if (transfer.partner) {
		const offer = proposed === transfer.partner.entry_id ? proposedOffer(transfer) : null;
		return {
			...transfer.partner,
			proposal: proposed === transfer.partner.entry_id,
			exact: offer?.exact ?? false
		};
	}
	const offer = proposedOffer(transfer);
	if (offer && proposed !== null) {
		return {
			account_id: offer.account_id,
			booked_on: offer.booked_on,
			amount: offer.amount,
			description: offer.description,
			proposal: true,
			exact: offer.exact
		};
	}
	return null;
}

/** The evidence line of a proposed partner. */
export function proposalEvidence(partner: ShownPartner): string {
	return partner.exact ? 'proposed: exact match' : 'proposed: closest candidate';
}

/**
 * The state of an unpaired leg in plain words, or null when there is nothing to add (a pair, a
 * proposal). `counterAccountId` is the leg's counter-account as the draft leaves it.
 */
export function stateSentence(
	transfer: UnitTransfer,
	counterAccountId: number | null,
	words: Words
): string | null {
	switch (transfer.state) {
		case 'paired':
			return null;
		case 'needs_account':
			return `Needs an account in ${transfer.needs_account?.currency ?? 'another currency'}`;
		case 'waiting': {
			const waiting = transfer.waiting_for;
			const name = waiting ? accountName(words, waiting.account_id) : 'the other account';
			const reach =
				waiting?.synced_through != null
					? `synced through ${formatDate(waiting.synced_through, words.locale)}`
					: 'not synced yet';
			return `Waiting for ${name}. Its import has not reached the matching window yet (${reach}).`;
		}
		case 'unmatched': {
			if (counterAccountId === null) return 'Choose where the money went.';
			const counter = words.lookups.accounts.get(counterAccountId);
			// an unsynced account has no import to wait for: the other side is made by hand
			if (!counter || !counter.synced) {
				return counter ? `No partner. Create the other side on ${counter.name}.` : null;
			}
			return `The partner is missing from ${counter.name}’s import. Import what is missing, or convert this to a flow if it is not a transfer.`;
		}
	}
}
