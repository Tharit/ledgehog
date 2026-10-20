// The shapes of the two time-based reports (architecture §4.1), from the generated API types. The
// shared ones (`Line`, `ByCategory`…) are in `types.ts`.

type Schemas = import('../types/api.js').components['schemas'];

export type Savings = Schemas['SavingsOut'];
export type Period = Schemas['PeriodOut'];
export type CategorySeries = Schemas['CategorySeriesOut'];
export type OverTime = Schemas['OverTimeOut'];
export type Balances = Schemas['BalancesOut'];
export type AccountBalances = Schemas['AccountBalancesOut'];
export type PointNetWorth = Schemas['PointNetWorthOut'];

export type Step = 'month' | 'quarter' | 'year';
export type Kind = 'expense' | 'income';
