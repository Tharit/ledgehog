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
