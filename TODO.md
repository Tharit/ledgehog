# TODO

Things noticed and deliberately not acted on yet.

## Spec divergence

Places where the implementation does not match `spec/`. Each needs a decision: change the code, or change the spec.

### Closed accounts in account pickers

`spec/spec.md` §3.3 (Closing): "pickers list it after the open accounts rather than hiding it."
The review panel's counter-account picker and the rule form's target picker follow this (`frontend/src/lib/rules/targets.ts`). These do not rank closed accounts after open ones; they list all accounts by sort order, then name:

- Ledger filter bar: `frontend/src/lib/components/ledger/filter-bar.svelte:64`
- Report controls: `frontend/src/lib/components/reports/report-controls.svelte:46`
- Entry form (unsynced accounts only): `frontend/src/lib/entry-form/defaults.ts:6`

Not a divergence, for reference: the importer pickers hide closed accounts (`frontend/src/lib/components/importers/discovery-page.svelte:44`, `frontend/src/lib/components/importers/instance-editor-page.svelte:114`). The spec asks for that: account discovery no longer offers a closed account (§3.3), and "Link account" lists open accounts (`spec/ux/views/importers.md`).

### Category ranking in pickers

`spec/spec.md` §3.5: "Pickers rank categories by recent use, so dormant ones sink without being hidden."
`targetOptions` in `frontend/src/lib/rules/targets.ts` sorts categories by their path, alphabetically. Not checked: whether another category picker ranks by recent use.

## Open questions

- **Marking a closed account in a picker row.** Closed accounts now sit after the open ones in the counter-account and rule target pickers, but the row itself looks like an open account's. The only existing convention is the "Closed" group heading on the accounts list. A muted "Closed" label on the row would be new copy.
- **Auto-pairing after a user's own-currency choice on a synced account (D261).** A leg with an instructed amount whose user-chosen counter-account is in the leg's own currency and synced waits for its partner, but the matcher's candidate filter (`is_candidate` in `app/core/matching/candidates.py`) keeps to the instructed currency, so the two are never paired automatically; the user picks the partner by hand. `spec/spec.md` §5.7 says both that the matcher keeps to the default and that a decided counter-account "is paired without review once its partner arrives". Unsynced counter-accounts are not affected: the commit creates the counter-leg.
- **Uncoloured accounts in a stacked chart.** Over time › By account stacks accounts in their own colour, and an account without one is `stone` (`spec/ux/design.md` §3), so with uncoloured accounts every segment and legend swatch is the same brown and the chart cannot be read. Proposed (not yet approved) addition to `design.md` §8: "In a chart that stacks accounts, an account without a colour takes the next colour of the categorical order (§3) not taken by a coloured account in the chart; "Other" stays `stone`." Only stacked charts change; icon tiles, the sankey and Balances keep `stone`. Code: `accountStack` in `frontend/src/lib/reports/charts.ts`.
- **"−0" at the base of a stacked chart's axis.** The expense stack charts in Over time (By category and By account) label the zero tick "-0", because `category-stack-chart.svelte` formats the tick as the kind's sign times a magnitude. Zero should read "0".
