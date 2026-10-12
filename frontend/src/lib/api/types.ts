// Hand-written for now: these are replaced by the types generated from OpenAPI
// (src/lib/types/api.d.ts, `npm run gen:api`) once the dump exists.

/** Calendar date, `YYYY-MM-DD`; never parsed to a Date (patterns §3). */
export type IsoDate = string;

/** Signed integer in the minor units of its currency, always with the currency (architecture §4.5). */
export type Money = { amount: number; currency: string };

export type SessionUser = { id: number; login: string; display_name: string };

export type AppConfig = {
	base_currency: string;
	timezone: string;
	locale: string;
	max_rate_age_days: number;
	matching_window_days: number;
	document_window_days: number;
};

export type Account = {
	id: number;
	name: string;
	kind: string;
	currency: string;
	external_ref: string | null;
	closed_on: IsoDate | null;
	sort_order: number;
	note: string | null;
	icon: string | null;
	color: string | null;
	synced: boolean;
	synced_through: IsoDate | null;
	last_data_on: IsoDate | null;
	unexplained_difference: Money | null;
	anchored: boolean;
	records_since_zero: number[] | null;
};

// Generated from OpenAPI (src/lib/types/api.d.ts): the entries list.
type Schemas = import('../types/api.js').components['schemas'];

export type Entry = Schemas['EntryOut'];
export type EntryPage = Schemas['EntryPageOut'];
export type EntryType = NonNullable<Entry['type']>;
export type ReviewFlag = Entry['review_flags'][number];
export type EntryTagIds = Schemas['EntryTagIdsOut'];
export type EntryTagsOut = Schemas['EntryTagsOut'];
export type SettleOut = Schemas['SettleOut'];
export type TagApplyBody = Schemas['TagApplyBody'];
export type TagApplyOut = Schemas['TagApplyOut'];
export type TagWriteOut = Schemas['TagWriteOut'];
export type CategoryCreateBody = Schemas['CategoryCreateBody'];
export type CategoryUpdateBody = Schemas['CategoryUpdateBody'];
export type CategoryWriteOut = Schemas['CategoryWriteOut'];
export type CategoryDeleteOut = Schemas['CategoryDeleteOut'];
export type CategoryMergeOut = Schemas['CategoryMergeOut'];
export type PayeeCreateBody = Schemas['PayeeCreateBody'];
export type PayeeUpdateBody = Schemas['PayeeUpdateBody'];
export type PayeeWriteOut = Schemas['PayeeWriteOut'];
export type PayeeDeleteOut = Schemas['PayeeDeleteOut'];
export type PayeeMergeOut = Schemas['PayeeMergeOut'];

// TEMPORARY, hand-written from app/api/routers/lookups.py until the generated types contain
// GET /api/ledger/categories|payees|tags; then replace these with `Schemas[...]`.
export type Category = {
	id: number;
	parent_id: number | null;
	name: string;
	kind: 'income' | 'expense' | string;
	sort_order: number;
	icon: string | null;
	color: string | null;
};

export type Payee = {
	id: number;
	name: string;
	icon: string | null;
	color: string | null;
	note: string | null;
	/** not shown in the UI yet (step 9); the lookup list carries it */
	document_provider?: string | null;
};

export type Tag = {
	id: number;
	name: string;
	color: string | null;
	starts_on: IsoDate | null;
	ends_on: IsoDate | null;
	entry_count: number;
};

/**
 * The ledger filter, in the API's own parameter names (so a URL is also an API query).
 * Within a dimension the values are OR, across dimensions AND. Amounts are magnitudes in minor
 * units of `currency` (which an amount bound requires).
 */
export type EntryFilter = {
	/** inclusive */
	from?: IsoDate;
	/** inclusive */
	to?: IsoDate;
	account_id: number[];
	category_id: number[];
	/** a category includes its descendants unless this is false */
	category_descendants: boolean;
	uncategorised: boolean;
	payee_id: number[];
	tag_id: number[];
	amount_min?: number;
	amount_max?: number;
	currency?: string;
	direction?: 'in' | 'out';
	q: string;
	type: string[];
	flag: string[];
};
