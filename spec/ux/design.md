# Household ledger — visual design

Status: **draft, written before the first screen, from two reference images.**
The visual language every view uses: colour, type, spacing, icons, the mascot,
and how the states `ux/patterns.md` defines look. This document depends on
`patterns.md` and supplies the concrete look for its conventions; it adds no
domain concepts and no conventions of its own about behaviour.

The tokens below are the source of truth. The reference images
(`design_system.png`, `design_system_mockup.png`, §10) set the tone; where a
value here and a pixel there disagree, this document wins.

---

## 1. Principles

Ledgehog is a household ledger with a warm, friendly, understated identity.

- **Warm, not sterile.** Cream and beige surfaces rather than white or cool
  grey; forest green anchors the identity, with muted earthy accents.
- **Playful, not childish.** The mascot appears where there is room for it,
  never in the data.
- **Calm where you look, dense where you work.** Overviews breathe; the
  ledger list, the review queue and the unit panel are compact (§5), because
  they are read row by row and driven by keyboard.
- **Colour supports, never carries.** No meaning is in colour alone: the sign
  is always written (`patterns.md` §2), a badge always has a glyph and a
  tooltip, a category always its name.

The overall rule: it should feel like a thoughtfully kept personal finance
notebook, not enterprise accounting software or a banking dashboard.

## 2. Theme colours

Light theme only in v1. Token names are semantic so that a dark theme can be
added later by redefining values, never by renaming. Each token maps onto the
CSS variable shadcn-svelte uses, so the theme is one stylesheet.

| Token | shadcn variable | Hex | Use |
|---|---|---|---|
| background | `--background` | `#F7F0E6` | app background |
| sidebar | `--sidebar` | `#F3E9DA` | navigation sidebar |
| surface | `--card`, `--popover` | `#FFFAF3` | cards, panels, dialogs, menus |
| surface-muted | `--muted`, `--secondary` | `#F5EDE2` | inputs, secondary buttons, table header |
| border | `--border` | `#E9DED0` | dividers and card outlines — decorative |
| input | `--input` | `#948572` | input and checkbox outlines (≥ 3:1) |
| text | `--foreground` | `#172923` | text, headings, figures |
| text-muted | `--muted-foreground` | `#6B6359` | labels, metadata, proposals (§7) |
| primary | `--primary` | `#24483D` | primary buttons, links, brand |
| primary-foreground | `--primary-foreground` | `#FFFAF3` | text on primary |
| primary-hover | — | `#356554` | hover on primary |
| accent | `--accent`, `--sidebar-accent` | `#DDE3D3` | selected navigation, list cursor row |
| sage | — | `#91A88D` | translucent area fills, decoration |
| ring | `--ring` | `#356554` | focus ring |
| amount-positive | — | `#3B7A57` | amounts above zero |
| amount-negative | `--destructive` | `#B04A33` | amounts below zero; destructive confirmations |

- **`amount-positive` and `amount-negative` follow the sign, never the
  category's kind.** A refund in an expense category is positive and green;
  income and expense are told apart by the category and the report line
  (`spec.md` §3.5), not by colour.
- **There is no warning colour.** Account facts, run summaries and stale-state
  notices are notices (`patterns.md` §4.4, §8), shown in `text` and
  `text-muted` with an icon. Red is for amounts and destructive confirmations
  only.
- Never pure white (`#FFFFFF`) or a cool grey as a surface.

Text tokens meet WCAG AA (4.5:1) on `background`, `sidebar` and `surface`;
`amount-positive` and `amount-negative` on `background` and `surface`.

## 3. Category colours

A dedicated set, separate from the theme: the colours a user picks for
categories and tags (`spec.md` §3.5, §3.7), and the categorical palette of
every chart, so a category's bar matches its icon. A user picks a name from
this set, never a free colour, so contrast holds whatever is chosen.

| Name | Foreground | Tint |
|---|---|---|
| `forest` | `#2F5D4E` | `#E2E4DC` |
| `sage` | `#5B7A58` | `#E8E8DD` |
| `olive` | `#6F6F2A` | `#EBE7D7` |
| `teal` | `#2E6E6E` | `#E2E6E0` |
| `slate` | `#4D6984` | `#E6E6E3` |
| `lavender` | `#6A6194` | `#EAE5E6` |
| `plum` | `#81506E` | `#EDE2E0` |
| `ochre` | `#8F6420` | `#EFE5D5` |
| `brown` | `#76503A` | `#ECE2D9` |
| `stone` | `#736B61` | `#EBE6DF` — the default |

- **An icon is drawn in its foreground on its tint**: a rounded square,
  radius 6px, 24px in compact rows and 32px in comfortable ones.
- **Resolution:** a category without a colour takes its parent's, up to the
  top level; with none there, or a name not in this set, `stone`. The same for
  icons (§6), defaulting to `shapes`. Colouring the top-level categories is
  therefore enough to colour the tree.
- **No reds.** A red category would read as a negative amount.
- Foregrounds are at least 4.5:1 on `surface` and 3.5:1 on their own tint;
  tints are the foreground at 14 % over `surface`.

## 4. Typography

Inter, variable, bundled with the app (architecture §6.7), with
`system-ui, sans-serif` as fallback.

| Role | Size / weight |
|---|---|
| Page heading | 28px / 600 |
| Section heading | 16px / 600 |
| Body | 14px / 400 |
| Compact rows (§5) | 13px / 400 |
| Labels, metadata | 12px / 500 |
| Overview figures | 28px / 700 |

Every amount uses tabular numerals (`font-variant-numeric: tabular-nums`) and
is right-aligned (`patterns.md` §2). No decorative fonts; uppercase only for
short eyebrow labels, if at all.

## 5. Layout, spacing and density

An 8px grid, with 4px steps inside compact elements.

| Element | Value |
|---|---|
| Sidebar width | 232px |
| Main content padding | 32px |
| Card padding | 20px |
| Gap between cards | 16px |
| Card radius | 12px |
| Button, input, nav item radius | 8px |
| Borders | 1px `border` |
| Shadow | `0 1px 2px rgb(60 40 20 / 0.06)` on cards only |

**Two densities, named so no view invents a third:**

- **Comfortable** — overview, account and report cards, settings. Rows 48px,
  14px text, category icon 32px, a second line allowed for metadata.
- **Compact** — the ledger list, the review queue, the unit panel and any
  table of entries. Rows 32px, one line, 13px text, category icon 24px,
  horizontal dividers only, no card padding around the table.

## 6. Icons

Lucide (`@lucide/svelte`, architecture §2), stroke 1.75px, 18px by default and
16px in compact rows, drawn in `text-muted` unless a category colour applies.
No filled, glossy or 3D icons.

**Category icons** come from a curated set — the only names the category
editor offers:

```
shopping-cart  shopping-basket  utensils  coffee  wine  pizza
house  lamp  zap  flame  droplet  wifi  smartphone  tv
car  fuel  bus  train-front  bike  plane  circle-parking
heart-pulse  pill  stethoscope  dumbbell  shirt  scissors  baby
graduation-cap  book-open  gamepad-2  music  film  ticket
gift  party-popper  paw-print  tree-palm  tent
briefcase  banknote  piggy-bank  landmark  receipt  credit-card
hand-coins  wallet  trending-up  percent  shield  building-2
wrench  hammer  leaf  sparkles  repeat  shapes  circle-ellipsis
```

**Fixed icons**, not configurable, drawn in `stone`:

| What | Icon |
|---|---|
| a transfer ("→ Cash") | `arrow-left-right` |
| an opening entry | `flag` |
| a valuation entry | `gauge` |
| a reconciliation entry | `scale` |

An unclassified entry shows no category icon: its category slot is the absent
value "Unclassified" (§7).

**Review badges** (`patterns.md` §4.2), 14px, `text-muted`, always with their
tooltip:

| Token | Icon |
|---|---|
| `unconfirmed` | `circle-dashed` |
| `unclassified` | `circle-question-mark` |
| `document_suggested` | `file-text` |
| `waiting` | `clock` |
| `unmatched_transfer` | `unlink` |

## 7. States

The look of the states `patterns.md` defines, the same in every view; the
section numbers in this table are `patterns.md`'s.

| State | Look |
|---|---|
| list cursor (`patterns.md` §5) | row background `accent`, 2px `primary` bar on the left edge |
| keyboard focus inside a panel | 2px `ring` outline, 2px offset |
| hover | row background `surface-muted`; never stronger than the cursor |
| resolved by your action (§7) | row text `text-muted`, `check` icon in the badge slot |
| changed as a consequence (§7) | 2px `ochre` bar on the left edge, with the tooltip "changed by your last action" |
| proposal (§4.3) | `text-muted`, italic |
| decided value | `text`, regular |
| absent value (§9) — "Unclassified", "→ ?", "not anchored", unvalued | `text-muted` with a dotted underline, the explanation in a tooltip |
| disabled commit (§6) | `primary` at 40 %, its reason as tooltip |
| notice (account facts, stale state) | one line, `text-muted`, `info` icon; never a banner or a dialog |

## 8. Charts

- Lines are 2px `primary`; areas beneath them `sage` at 20 %. Gridlines 1px
  `border`, horizontal only; axis labels 12px `text-muted`.
- Series by category use the category's resolved colour (§3); everything else
  in the categorical order of §3, with "Other" always `stone`.
- Bars for comparing categories; a donut only where the whole matters more
  than the ranking. Amounts on charts follow `patterns.md` §2, signs included.

## 9. Mascot and brand

A friendly brown hedgehog with a cream face and a dark-green ledger book,
flat and vector-like, recognisable at small sizes.

- **Sidebar:** the small head beside the "Ledgehog" wordmark.
- **Empty states:** a larger illustration with the sentence that explains the
  next step (`patterns.md` §9) — the review queue with nothing to review, an
  account with no data yet.
- **Favicon:** cream silhouette on `primary`.
- **Never** in a dense view, and never with motivational copy.

The reference images are generated raster art. The favicon, the sidebar mark
and each empty-state illustration are to be redrawn as SVG before they ship.

## 10. Reference images

- `design_system.png` — mascot, wordmark, app icons, favicons, monochrome
  variants.
- `design_system_mockup.png` — the canonical reference for tone: surfaces,
  type, spacing, card style, chart style.

The mockup's **layout and content are illustrative only**; the spec decides
what each screen shows. In particular, these appear in the mockup and are not
part of the design: budgets, goals and a savings rate (`spec.md` §1.2); charts
on the dashboard (`plan.md`); bank logos and payee logos; a greeting, a user
avatar and the motivational quote; spending shown unsigned. The navigation
follows the routes of architecture §6.2 — Ledger, not "Transactions", and the
review queue, which the mockup lacks.

## 11. Open for the first month

- the category colour set and the curated icon list;
- the two densities' exact row heights;
- the consequence marker of §7 and whether resolved rows fade further.
