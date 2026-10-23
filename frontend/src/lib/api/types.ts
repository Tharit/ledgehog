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
	/** a document is dated within [booked_on - back, booked_on + ahead] of its transaction (spec §5.8) */
	document_window_back_days: number;
	document_window_ahead_days: number;
	/** whether "Log in with SSO" is offered, and whether it is the only way in */
	oidc_offered: boolean;
	oidc_enforced: boolean;
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
	/** the sum of the account's entries, in its currency */
	balance: Money;
	records_since_zero: number[] | null;
};

// Generated from OpenAPI (src/lib/types/api.d.ts): the entries list.
type Schemas = import('../types/api.js').components['schemas'];

export type Entry = Schemas['EntryOut'];
export type DocumentRow = Schemas['DocumentOut'];
export type DocumentProviders = Schemas['DocumentProvidersOut'];
export type DocumentPage = Schemas['DocumentPageOut'];
export type DocumentDetail = Schemas['DocumentDetailOut'];
export type DocumentLine = Schemas['DocumentLineOut'];
export type DocumentMatch = Schemas['DocumentMatchOut'];
export type DocumentCarrier = Schemas['CarrierOut'];
export type SourceTransaction = Schemas['SourceTransactionOut'];
export type EntryPage = Schemas['EntryPageOut'];
export type EntryType = NonNullable<Entry['type']>;
export type ReviewFlag = Entry['review_flags'][number];
export type EntryTagIds = Schemas['EntryTagIdsOut'];
export type EntryTagsOut = Schemas['EntryTagsOut'];
export type SettleOut = Schemas['SettleOut'];
export type AccountCreateBody = Schemas['CreateBody'];
export type AccountKind = AccountCreateBody['kind'];
export type AccountWriteOut = Schemas['AccountWriteOut'];
export type TagApplyBody = Schemas['TagApplyBody'];
export type TagApplyOut = Schemas['TagApplyOut'];
export type TagWriteOut = Schemas['TagWriteOut'];
export type TagUpdateBody = Schemas['TagUpdateBody'];
export type TagDeleteOut = Schemas['TagDeleteOut'];
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
export type SourceCreateBody = Schemas['SourceCreateBody'];
export type SourceUpdateBody = Schemas['SourceUpdateBody'];
export type SourceWriteOut = Schemas['SourceWriteOut'];
export type SourceEditOut = Schemas['SourceEditOut'];
export type SourceEditEffects = Schemas['EditEffectsOut'];
export type SourceDeleteOut = Schemas['SourceDeleteOut'];
export type SourceDeleteCounts = Schemas['DeleteCountsOut'];
export type SourceUnitRef = Schemas['UnitRefOut'];
export type AccountUpdateBody = Schemas['UpdateBody'];
export type StatementPage = Schemas['StatementOut'];
export type StatementItem = StatementPage['items'][number];
export type StatementSource = Schemas['StatementSourceOut'];
export type StatementRecord = Schemas['StatementRecordOut'];
export type Provenance = Schemas['ProvenanceOut'];
export type RunRef = Schemas['RunRefOut'];
export type DuplicateOf = Schemas['DuplicateOfOut'];
export type MarkDuplicateOut = Schemas['MarkDuplicateOut'];
export type DerivedChange = Schemas['DerivedChangeOut'];
export type RecordWriteOut = Schemas['RecordWriteOut'];
export type RecordDeleteOut = Schemas['RecordDeleteOut'];

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
	/** the provider of the documents that describe this payee's charges (spec §3.6) */
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

/**
 * The documents filter, in the API's own parameter names. Providers are OR, the rest AND. Amounts
 * are magnitudes in minor units of `currency` (which an amount bound requires); `linked: false`
 * is "not linked" (carried by no transaction); `fully_charged: false` is "not fully charged" (the
 * carriers' amounts fall short of the total, carried by none included).
 */
export type DocumentFilter = {
	provider: string[];
	/** inclusive */
	from?: IsoDate;
	/** inclusive */
	to?: IsoDate;
	amount_min?: number;
	amount_max?: number;
	currency?: string;
	q: string;
	linked?: boolean;
	fully_charged?: boolean;
};
