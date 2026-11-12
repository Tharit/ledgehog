# Mockup brief — instructions for the image generator

Status: **not normative.** A prompt for regenerating `design_system_mockup.png`
so that the reference image agrees with `design.md` and the spec. Where this
brief and `design.md` disagree, `design.md` wins and this brief is corrected.
Data, names and layout below are illustrative; colours, type, density and the
rules under "Must" are not.

---

## 1. The image

One landscape image, 3:2, about 1536 × 1024 px, on the app background
`#F7F0E6`. A flat, crisp UI screenshot style — not a photo of a laptop, no
perspective, no device frame, no drop shadows beyond very soft card shadows.

Layout of the sheet:

- **Top, about two thirds of the height:** one large screen — the
  **Overview** (§3), full width with its sidebar.
- **Bottom row:** three smaller screens of equal width, each with a narrow
  sidebar: **Ledger** (§4), **Review** (§5), **Reports** (§6).

All four screens share the same sidebar, palette and type, so the sheet reads
as one product.

## 2. What every screen shares

**Palette** (use these exact hex values):

- background `#F7F0E6`; sidebar `#F3E9DA`; cards and panels `#FFFAF3`;
  inputs and table headers `#F5EDE2`
- dividers `#E9DED0`, 1px, low contrast
- text `#172923`; secondary text `#6B6359`
- primary (buttons, links, brand) `#24483D`, with cream `#FFFAF3` text on it
- selected navigation item and the highlighted list row `#DDE3D3`
- amounts above zero `#3B7A57`; amounts below zero `#B04A33`
- category colours (icon foreground on a pale tint of itself): forest
  `#2F5D4E`, sage `#5B7A58`, olive `#6F6F2A`, teal `#2E6E6E`, slate `#4D6984`,
  lavender `#6A6194`, plum `#81506E`, ochre `#8F6420`, brown `#76503A`, stone
  `#736B61`
- no pure white, no cool grey, no bright blue, no orange, no red other than
  the amount colour

**Type:** Inter. Page titles 28px semibold, section titles 16px semibold, body
14px, compact table rows 13px, labels 12px. All amounts in tabular figures,
right-aligned, each with its sign: a true minus "−€54.23" and a plus
"+€3,250.00".

**Shape:** cards with 12px corners and a 1px border; buttons, inputs and nav
items 8px corners; generous space around section titles.

**Icons:** thin rounded line icons in the Lucide style, 1.75px stroke, never
filled or glossy. Category icons sit in a small rounded square of their
colour's pale tint, the icon drawn in the colour itself.

**Sidebar** (232px, `#F3E9DA`): at the top the small brown hedgehog head next
to the wordmark "Ledgehog" in dark green-black, bold. Navigation, each with a
line icon:

1. Overview (`house`)
2. Review (`inbox`) — with a small pill "14" in `#DDE3D3`
3. Ledger (`list`)
4. Accounts (`landmark`)
5. Reports (`chart-column`)
6. Sync (`refresh-cw`)

Settings (`settings`) sits alone at the bottom. The active item has the
`#DDE3D3` background. There is **no** Budgets, Goals, Categories or
Transactions item, no user avatar and no search box in a top bar.

## 3. Overview (the large screen)

A page title "Overview" and, under it in secondary text, "Sunday, 11 October
2026". No greeting, no motivational text.

**Four figure cards in a row** — figures only, **no sparklines and no
charts**:

1. **Net worth** — "€128,450.00"; beneath in secondary text
   "+ €500.00 in transfers still unpaired".
2. **Spent in October** — "−€1,240.00"; beneath "plus −€310.00 unclassified
   · −€42.00 reconciliations"; and a smaller line "September: −€2,615.00".
3. **Income in October** — "+€3,250.00"; beneath "September: +€3,250.00".
4. **To review** — "14" with the `inbox` icon; beneath a primary-coloured
   link "Open the review queue →".

**Data age card** (left, wider) titled "Data age", two short tables, *Synced*
and *By hand*, each sorted by data age, oldest first. Each row: account icon on
its tint, name, a secondary line with its data age, balance right-aligned with
sign:

| Icon (colour) | Name | Data age | Balance |
|---|---|---|---|
| `wallet` (ochre) | Cash | "entered by hand · 9 days ago" | +€184.20 |
| `chart-line` (teal) | Depot | "valued 23 Sep" | +€38,450.00 |
| `credit-card` (plum) | Visa | "synced yesterday" | −€640.12 |
| `piggy-bank` (sage) | Tagesgeld | "synced today" | +€25,000.00 |
| `landmark` (forest) | Giro | "synced today" | +€5,420.00 |

Under the Visa row, one quiet line in secondary text with a small `info` icon:
"unexplained difference −€12.40 since 30 Sep". No warning colour, no banner.

**Recent entries card** (right) titled "Latest entries", with a "Ledger →"
link: four compact rows, each with date, category icon on tint, description,
and signed amount — "REWE · Groceries −€54.23", "Salary · Salary +€3,250.00",
"Deutsche Bahn · Transport −€49.90", "→ Tagesgeld · Transfer −€500.00" (the
transfer with the `arrow-left-right` icon in stone and no category). One row
shows a small `circle-dashed` badge after its description.

**Mascot:** none on this screen.

## 4. Ledger (bottom left)

Title "Ledger". A filter bar of pill-shaped inputs: "1 Oct – 11 Oct",
"All accounts", "All categories", "Tags", and a text field "Filter…". A
primary button "+ Entry" at the right.

A **compact** table: 32px rows, one line each, thin horizontal dividers only.
Columns: Date · Account · Description · Payee · Category · Tags · Amount.

- The account column shows a small coloured dot then the name ("● Giro").
- The category column shows the icon on its tint then the name.
- One row is the highlighted cursor row: `#DDE3D3` background with a 2px
  dark-green bar on its left edge.
- One row shows "Unclassified" in secondary text with a dotted underline and
  no icon, and a small `circle-question-mark` badge.
- One row is a split, expanded: the parent "Amazon −€86.47" with two indented
  child rows "Books −€24.99" and "Household −€61.48".
- One row is a transfer: category column "→ Cash" with `arrow-left-right`.
- One row is a derived entry: "Valuation" with the `gauge` icon, no payee.
- One row carries a small tag chip "Lisbon trip" in a lavender tint.
- Amounts mixed: mostly negative, one refund "+€19.99" in an expense
  category (Shopping), one salary positive.

## 5. Review (bottom middle)

Two panes. **Left:** the queue, grouped with small section labels in
secondary text: "Recurring", "Waiting", "Needs an account". Compact rows with
badges (`circle-dashed`, `clock`, `unlink`). The cursor row is highlighted as
in the ledger. One group header reads "3 withdrawals need an account in USD"
with a small outlined button "Add account…".

**Right:** the unit panel for the cursor row — "REWE, −€47.31, Giro, 9 Oct".
Fields as labelled rows: Type "Flow", Payee "REWE", Category "Groceries" (with
icon). Beneath the category, in *italic secondary text*, the evidence
"history: 3 of 4 since Mar 2026". At the bottom a short preview line "→
confirmed" and a primary button "Confirm" with a small keyboard hint "⌘ ↵".
No percentages, no confidence bars, no traffic-light colours.

## 6. Reports (bottom right)

Title "Spend by category", a range picker "1 Sep – 30 Sep". A horizontal
**bar chart**, bars in the category colours (Housing forest, Groceries sage,
Transport slate, Restaurants ochre, Shopping plum, Health teal, Other stone),
each bar labelled with the category icon, name and a signed amount
("−€980.00"). Thin horizontal gridlines only.

Below the bars, separated by a divider, two further lines in secondary text,
also with amounts: "Unclassified −€310.00" and "Reconciliations −€42.00", so
the report shows how much of the total is explained. No donut, no pie, no
percentages.

## 7. Must

- Every amount has its sign; spending is never shown as a positive number.
- Green and red follow the sign only, never "income" and "expense".
- No warning or alert colour anywhere; notices are quiet secondary text.
- No charts or sparklines on the Overview.
- No budgets, goals, savings rate, avatars, greetings or quotes.
- No bank logos, brand logos or merchant logos; accounts and payees use line
  icons only.
- Dense screens (Ledger, Review) are clearly more compact than the Overview.
- The mascot appears only as the small sidebar head.

## 8. Avoid

Saturated or rainbow palettes, gradients, glassmorphism, 3D icons, emoji,
pure white surfaces, cool grey, stock-photo elements, a laptop or phone frame,
lorem ipsum, unreadable fake text — keep labels short and legible rather than
filling every cell.
