// The reporting shapes (architecture §4.1, spec §8), from the generated API types. Every figure is
// a `Line`: a total in the base currency (null when entries exist and none could be valued), the
// entries it covers, and what could not be valued, per currency.

type Schemas = import('../types/api.js').components['schemas'];

export type Line = Schemas['LineOut'];
export type Overview = Schemas['OverviewOut'];
export type NetWorth = Schemas['NetWorthOut'];
export type SavingsSpan = Schemas['SavingsSpanOut'];
export type MonthSpend = Schemas['MonthSpendOut'];
export type ThisMonthSpend = Schemas['ThisMonthSpendOut'];
export type ByCategory = Schemas['ByCategoryOut'];
