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
| row-hover | — | `#F5F3E9` | hovered row: `accent` at 30 % over `surface` |
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
  `text-muted` with an icon. Red is for amounts, destructive confirmations and
  the validation message under a field.
- Never pure white (`#FFFFFF`) or a cool grey as a surface.

Text tokens meet WCAG AA (4.5:1) on `background`, `sidebar` and `surface`;
`amount-positive` and `amount-negative` on `background` and `surface`.

## 3. Dimension colours

A dedicated set, separate from the theme: the colours a user picks for
categories, accounts, payees and tags (`spec.md` §3.3, §3.5–§3.7), and the
categorical palette of every chart, so a category's bar matches its icon. A
user picks a name from this set, never a free colour, so contrast holds
whatever is chosen.

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
- **Resolution.** A name not in this set counts as none.
  - *Category:* without a colour it takes its parent's, up to the top level;
    with none there, `stone`. The same for icons (§6), defaulting to `shapes`.
    Colouring the top-level categories is therefore enough to colour the tree.
  - *Account:* without a colour, `stone`; without an icon, its kind's (§6).
  - *Payee:* without a colour, `stone`; without an icon, its initial in the
    icon's place, 600 weight.
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

**Surfaces.** A page's content sits on cards (`surface`, 1px `border`, 12px
radius, the card shadow); its structure sits on the background. On the
background: the page header with its title, description and actions; section
tabs; a filter bar or a report's controls; notices; the heading of a list or
a group; an action that follows a stack of cards. On a card: figures, forms,
charts, lists and tables. A card is one of two kinds:

- **padded** (20px) — a self-contained block: a figure, a form, a chart, a
  short summary list. Its title, if any, is inside, at the top.
- **flush** — a page's list or table: no padding, rows edge to edge divided by
  hairlines, a header row tinted `surface-muted` along its top; the ledger list's total row
  (`patterns.md` §4.1) takes the same tint along its bottom. Its heading,
  if any, sits above it on the background; a list in groups is one card per
  group.

Facts about the page's subject (an account's balance, a document's total) are
a row of figure cards under the header, as on the Overview. An empty or error
state is a padded card in place of the content. Surfaces inside a dialog or
the work panel are not cards.

**Two densities, named so no view invents a third:**

- **Comfortable** — overview, account and report cards, settings. Rows 48px,
  14px text, category icon 32px, a second line allowed for metadata.
- **Compact** — the ledger list, the review queue, the unit panel and any
  table of entries. Rows 32px, one line, 13px text, category icon 24px,
  horizontal dividers only, in a flush card.

**Controls.** One scale, so no view picks a height:

| Control | Height | Where |
|---|---|---|
| Button, input, select, filter chip | 32px | everywhere |
| Compact button | 24px | inside popovers and table rows only |
| Icon button | 32px; 24px in a row | row actions, close |

Variants by role: *primary* for the one action that finishes a surface;
*outline* for Cancel and for secondary actions; *ghost* for header and popover
helpers ("Clear"); *destructive* only for the button that carries out a
deletion. A form dialog and a decision dialog put their buttons at the right
of the footer, Cancel first, the primary last; a page editor puts them after
the form, left-aligned, with the destructive action at the far right.

**A choice among a few** (a report's kind, step or mode, an entry's type, a filter's direction) is a segmented control: one 32px box with a 1px `border`, split into segments by 1px dividers, the chosen segment tinted `accent` with medium-weight text, as an active filter chip. Controls side by side keep a 12px gap, so each box reads as one group. A set of swatches or icons (colours, looks) is not a segmented control.

**Row actions** (`patterns.md` §11.3) have `opacity: 0` and become `1` on row
hover, `:focus-within` and an open menu of the row; under `(hover: none)` they
are always `1`. No transition. The `⋯` is Lucide `ellipsis`.

**The work panel** (`patterns.md` §11.1) is a large overlay over the list. Its
geometry, whether it slides in from the right or is centred and its exact
size, is open until it has been used on real units. Consequence marks (`patterns.md` §7) are a
quiet marker on the row that fades once the cursor has visited it.

## 6. Icons

Lucide (`@lucide/svelte`, architecture §2), stroke 1.75px. No filled, glossy
or 3D icons. Size and colour come from the slot an icon sits in, below.

Each dimension has its own curated set, the only names its editor offers:
suitable icons, not the whole library.

**Category icons:**

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

**Account icons**, with the default for each kind:

| Kind | Default |
|---|---|
| checking | `landmark` |
| savings | `piggy-bank` |
| card | `credit-card` |
| cash | `wallet` |
| digital_wallet | `wallet-cards` |
| depot | `chart-line` |
| loan | `hand-coins` |
| asset | `gem` |
| clearance | `scale` |

```
landmark  building-2  piggy-bank  vault  credit-card  wallet  wallet-cards  scale
banknote  coins  hand-coins  chart-line  trending-up  gem
house  car  briefcase  baby  gift  plane  shield
```

**Payee icons** — kinds of counterparty, not brands:

```
store  shopping-cart  shopping-basket  utensils  coffee  fuel  train-front
plane  pill  heart-pulse  shirt  smartphone  wifi  zap  house  building-2
landmark  shield  film  music  gamepad-2  book-open  package  truck  gift
paw-print  scissors  wrench  dumbbell  graduation-cap  user  users
```

**Where they show.** Every icon sits in one of three slots, and the slot
decides how it is drawn, never the thing it stands for.

- **Lead** — one tile at the start of a row, a legend entry, a tooltip row, a
  filter option or a picker's row: the dimension that row is read by. An
  entry's row is read by its category, or by its type where the entry is
  derived; an account's row by its account; a report's row by whatever it
  groups. The rounded square of §3, 24px in compact rows and 32px in
  comfortable ones, its glyph 16px and 18px. A segmented control's segments
  are words (§5), not tiles.
- **Marker** — after the content, a bare glyph, 14px, `text-muted`, always
  with a tooltip: what is *true of* that row. The review badges below, the
  split marker, the model mark.
- **Heading** — before the title of a card or a section, a bare glyph, 16px,
  `text-muted`: what kind of thing it holds.

**The lead tile takes four sources, and its colour says which:**

| The row is read by | Its icon | Its colour |
|---|---|---|
| a category, an account, a payee | the member's own | the member's own, on its tint |
| an account kind | the kind's default (above) | `stone` |
| an entry type | its fixed icon (below) | `stone` |
| a measure | its fixed icon (below) | `stone` |

A coloured tile is therefore a thing in the ledger, and a `stone` tile the
app's own vocabulary. A category may carry a glyph a measure also uses —
`percent`, `receipt` — and the two cannot be read for each other, because one
is coloured and the other is not; nothing forbids the overlap. A chart's
series colour does not change its tile: where a series is a measure, its tile
is `stone` though its line is not.

**A row has one lead tile and no more.** Every other member it names is its
name after an 8px dot in its colour — the ledger's account column, a
transfer's "→ Cash", a counter-account in the unit panel — and a payee is
named without a dot, never in a ledger row. A tag carries a colour only and is
a chip wherever it appears. **A page about one member** — an account, a payee —
shows that member's icon beside its title in the page header
(`patterns.md` §11.7).

**An empty lead slot** shows its absent value in words (§7) and takes no icon:
an unclassified entry's category slot reads "Unclassified".

**Fixed icons**, not configurable: `stone` in a lead slot, `text-muted` in a
marker or a heading slot. An entry type and the report line that sums it are
one concept and share one glyph.

| What | Icon |
|---|---|
| a transfer ("→ Cash"), the transfers (net) line | `arrow-left-right` |
| an opening entry, the openings line | `flag` |
| a valuation entry, the valuations line | `gauge` |
| a reconciliation entry, the reconciliations line | `scale` |
| a flow, in the type filter only | `coins` |
| net worth | `sigma` |
| income | `hand-coins` |
| expense, and a period's spend | `receipt` |
| savings | `piggy-bank` |
| the savings rate | `percent` |
| the unclassified line | `circle-question-mark` |
| the review queue | `inbox`, `check` at zero |

A balance takes no icon: its account is what its row is read by. An unvalued
amount takes none either — it is an absent value (§7), not a measure. Some of
these glyphs are also an account kind's default, or a name a category may
carry; they are told apart by their colour, as above.

**A figure card's title** takes its measure's icon in the heading slot: the
Overview's four do (`views/overview.md`). A card whose figure belongs to one
subject — an account's balance, a document's total — takes none, because the
page header above it already names that subject.

A flow in a row shows its category, never `coins`.

**Review badges** (`patterns.md` §4.2), 14px, `text-muted`, always with their
tooltip:

| Token | Icon |
|---|---|
| `unconfirmed` | `circle-dashed` |
| `unclassified` | `circle-question-mark` |
| `waiting` | `clock` |
| `unmatched_transfer` | `unlink` |

A review state is a marker wherever it appears, never a tile: the bare glyph
in a row, in the review-state filter's options, and in the heading slot of a
queue section — *Pending review* `circle-dashed`, *Needs an account* `unlink`,
*Waiting* `clock` (`views/review-queue.md`).

## 7. States

The look of the states `patterns.md` defines, the same in every view; the
section numbers in this table are `patterns.md`'s.

| State | Look |
|---|---|
| list cursor (`patterns.md` §5) | row background `accent`, 2px `primary` bar on the left edge |
| the cursor's unit (`patterns.md` §5) | the unit's other rows take `accent` at 60 % |
| keyboard focus inside a panel | 2px `ring` outline, 2px offset |
| hover | row background `row-hover` (`accent` at 30 % over `surface`); never stronger than the cursor or a unit member |
| clickable | the pointer cursor on every control that acts on a click; `not-allowed` on a disabled one |
| committed by you (§7) | row text `text-muted`; a confirmed unit also shows a `check` icon in the badge slot, an unconfirmed one keeps its review badge |
| changed as a consequence (§7) | 2px `ochre` bar on the left edge, with the tooltip "changed by your last action" |
| proposal (§4.3) | `text-muted`, italic |
| decided value | `text`, regular |
| absent value (§9) — "Unclassified", "→ ?", "not anchored", unvalued | `text-muted` with a dotted underline, the explanation in a tooltip |
| disabled commit (§6) | `primary` at 40 %, its reason as tooltip |
| notice (account facts, stale state) | one line, `text-muted`, `info` icon; never a banner or a dialog |
| placeholder | `text-muted`, regular weight, never italic (italic marks proposals) |
| field validation message | 12px, `destructive`, under the field |
| dialog feedback (`patterns.md` §11.5) | one slot above the footer; error in `destructive`, conflict and report in `text` |
| empty state | `surface` card, 1px `border`, left-aligned in a settings page, centred in a full view; title 16px/600, body `text-muted` |

## 8. Charts

- Lines are 2px `primary`; areas beneath them `sage` at 20 %. Gridlines 1px
  `border`, horizontal only; axis labels 12px `text-muted`.
- Series by category use the category's resolved colour (§3); everything else
  in the categorical order of §3, with "Other" always `stone`.
- Bars for comparing categories; a donut only where the whole matters more
  than the ranking. Amounts on charts follow `patterns.md` §2, signs included.
- In a signed time series income draws above the zero line and expense below
  it; an account's line takes the account's colour (§3).

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
  type, spacing, card style, chart style. `design_system_mockup.md` is the
  brief it is regenerated from.

The mockup's **layout and content are illustrative only**; the spec decides
what each screen shows. In particular, these appear in the mockup and are not
part of the design: budgets and goals; bank logos and payee logos; a greeting,
a user avatar and the motivational quote; spending shown unsigned. Logos are
never
fetched from anywhere; custom icons, when they come, are the user's own
uploads. The navigation
follows the routes of architecture §6.2 — Ledger, not "Transactions", and the
review queue, which the mockup lacks.

## 11. Open for the first month

- the colour set and the three curated icon lists;
- the two densities' exact row heights;
- the consequence marker of §7 and whether resolved rows fade further.
