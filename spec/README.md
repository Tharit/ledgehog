# Household ledger — documentation map

A self-hosted household ledger for two users: FinTS import, categorisation
with correction, shared accounts, net worth tracking. Start with `spec.md`.

## The documents

| Document | Answers | Stability |
|---|---|---|
| `spec.md` | What the system does. Domain model, invariants (stable `I<n>` ids), pipeline semantics. | Stable. Changing it usually means a migration. |
| `decisions.md` | Why it does it that way. Each decision with the alternatives rejected, as stable `D<n>` entries. | Grows; entries are never renumbered or deleted. |
| `schema.sql` | The data model as DDL, with the reasoning in comments. | Moves with `spec.md`. |
| `architecture.md` | How it is built. Stack, runtime composition, module boundaries, contracts. | Stable, but revised by implementation learnings. |
| `plan.md` | What gets built, in what order, what is out of v1. | Churns constantly; mostly deleted once v1 ships. |
| `plugins/<type>/<name>.md` | One per plugin. See below. | Varies by type. |
| `features/*.md` | One per subsystem large enough to distort `spec.md` if absorbed. Rare. | Written before implementing that subsystem. |
| `ux/patterns.md` | Conventions applying across every view: provenance widget, amount and date rendering, keyboard model, how flags and errors surface. | Written early, then stable. |
| `ux/design.md` | Design specification | Written early, iterated, then stable. |
| `ux/views/*.md` | Individual screens: ledger list, review queue and unit panel, documents, accounts and the account page, importers, the file upload and the refresh of an importer's accounts, sync, the Overview (`overview.md`) and the reports. | Written *during* implementation. Expected to churn. |

## Rules between documents

The table above lists the documents in dependency order: each depends on the
ones before it, and never on the ones after. `decisions.md` stands to one
side, explaining `spec.md` and `architecture.md` without either depending on
it.

**1. A decision belongs in `spec.md` if changing it would require a migration
or invalidate stored data.** Everything else belongs in `architecture.md`.
Both documents contain implementation detail; the test is consequence of
change, not level of abstraction.

**2. A document may not acquire concepts from one it depends on in passing.**
If `architecture.md` needs a domain concept `spec.md` lacks, that is a gap in
the spec — fix it there. If a view spec needs an API operation the
architecture does not define, the same applies. This is the rule that keeps
the documents from silently diverging.

**2a. A document cites only the documents it depends on.** `architecture.md`
cites `spec.md`; a view spec cites both. Never the reverse. A document that
would have to cite one that depends on it is describing something it does not
own — say what is required and leave the mechanism unspecified, rather than
naming where it lives. `spec.md` therefore writes an importer's obligations as
"the importer reports X", never naming a plugin spec. The `README` is the
exception, since it names every document by definition.

**3. Where a UI decision forces a backend contract, the contract belongs in
`architecture.md`.** Converting an entry to a transfer in the review panel is
a draft edit whose preview may pair it with an entry elsewhere, show a mirror
leg to be created on another account, or leave a former partner behind, and
whose commit writes all of it and returns everything it touched; preview and
commit are API operations, decided in the architecture, and the view spec
references them rather than inventing them.

**4. When implementation contradicts a document, change the document.** A spec
that is wrong in three places is worse than no spec, because it still reads
authoritatively.

**5. What lives in `spec.md`; why lives in `decisions.md`.** The spec states
behaviour and stays normative, so its rules remain easy to find. Every
alternative considered and rejected, and the full reasoning behind a choice,
is a `decisions.md` entry. The spec keeps at most a sentence of *why* where a
reader needs it to apply a rule correctly. `decisions.md` is never normative:
where an entry restates behaviour and disagrees with the spec, the spec wins
and the entry is corrected. Entries have stable identifiers (`D<n>`); a
reversed decision is kept, marked *superseded by D<m>*, and its replacement
added at the end, so the record of what was tried survives. Entries may
concern either `spec.md` or `architecture.md`.

References run one way only, consistent with rule 2a: each entry cites the
sections and invariant ids it explains (`spec §5.7`, `spec I22`), and no other
document cites `decisions.md`. Before changing a section or an invariant,
search `decisions.md` for it. Invariant ids, like entry ids, are never
renumbered, so those searches survive any restructuring of the spec.

## Plugin specs

Plugins are grouped by type, and the types need different documents rather
than a shared template:

| Path | Covers | Stability |
|---|---|---|
| `plugins/importers/<source>.md` | What the source delivers, how its fields map, whether it assigns a stable id, what it reports as a closing balance, its failure modes. | Written ahead from the format specification; changes only when the source does. |
| `plugins/classifiers/<name>.md` | What it matches on, how it weighs its evidence, what it puts in a derivation basis, its tuning parameters (history's lookback period, say). | Churns — tuned against real data. |
| `plugins/<future type>/…` | Per that type. | — |

An importer spec is largely transcription and is stable once written. A
classifier spec is a tuning document and will not be. Do not try to unify
them.

## When core functionality earns its own spec

The default is that it does not. `spec.md` and `architecture.md` are meant to
be complete for the core, and splitting features out of them fragments the
two documents everything else references.

The bar: **a subsystem earns its own file in `features/` when absorbing it
would distort `spec.md`'s structure.** Natural-language querying clears it —
it has its own resolution model, safety constraints and failure modes.
Document matching clears it too: its matcher, the document as a rule input and auto-split are
`features/documents.md`, while the documents, links and invariants it relies
on stay in `spec.md`. Adding OIDC does not; it is a paragraph in the
credential policy.

Even for a subsystem that clears the bar, any *domain concept* it introduces
still lands in `spec.md` (rule 2). The feature spec covers only its own
internals.

## Why UX is split in two

Patterns and views have different lifespans. Conventions — how money renders,
what a keyboard shortcut means, how provenance is shown — are worth deciding
once and early, because inconsistency is expensive to unwind and every view
would otherwise re-decide them. Individual screens are the opposite: the
review queue's interaction model will be wrong in ways that only a month of
real use reveals, so writing it in detail beforehand produces confident prose
about interactions nobody has felt yet. Sketch views thinly, implement, then
write them down.

Plugin and feature specs sit at the same layer as UX specs. Whether they
behave like patterns or like views depends on the type, which is why they are
tabulated separately above: an importer spec is a closed problem written
ahead of time, a classifier spec is tuned against data it has not seen yet.

## Reading order

New to the project: `README.md` → `spec.md` §1–§4 (what the thing is, with
the invariants in §2.1) → `schema.sql` → `spec.md` §5 onwards (the pipeline)
→ `architecture.md`. `decisions.md` when you want to know why something is the
way it is — and always before changing a section or invariant: search it for
the section number or invariant id.

Deciding what to work on: `plan.md`. It holds no design decisions — where a
plan item implies one, the decision lives in the spec or the architecture and
the plan references it.

Implementing a screen: `ux/patterns.md` → `ux/design.md` → the relevant
`ux/views/*.md` → `architecture.md` §4 for the contracts.

Adding a plugin: `spec.md` §5 → the relevant interface in `architecture.md`
§5 → an existing spec of the same type as a template.
