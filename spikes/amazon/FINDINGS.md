# Amazon order import: spike findings

Question: how do we get order history out of Amazon to fill `documents` / `document_lines`?
Scope: data acquisition only. Interfaces, modelling and split logic belong to the importer / core.

**Verdict: feasible.** A headless login with credentials relayed from a UI works from a container-like
environment, needs no stored credentials, and a year of `amazon.de` orders reconciles to the cent in all but
one explained case (see "Amount model").

Evidence base: one account, `amazon.de`, 40 orders from 2025 (+ 6 recent), MFA/OTP enabled. Anything marked
*single sample* rests on one order.

## 1. Getting the data

There is no official API for a buyer's own history. PA-API, SP-API and the Business Order Reporting API are for
sellers, affiliates and business accounts. Amazon retired the "Order History Reports" CSV in March 2023.

| Route | Verdict |
|---|---|
| **`amazon-orders` (PyPI), scraping the consumer site** | **Chosen.** Pinned `==4.9.2`. |
| "Request Your Data" ZIP (Privacy Central) | Zero-auth fallback. Manual, 1-5 days, order-level only, not tested here. Worth supporting as an upload. |
| Browser extension in the user's own browser | Best security (no credentials/cookies reach the backend), but an extension to build and ship. Escalation option. |
| Remote browser streamed into the web app | Heavy. Escalation option if headless challenges become unmanageable. |

### Auth model that worked
- The library's `login --browser` opens a **visible local window**, so it cannot run in a headless container.
  Not used.
- Used instead: `AmazonSession(username, password, io=RelayIO)`. `login()` blocks in a worker thread. Amazon's
  questions (OTP device choice, OTP code, captcha) arrive through `io.prompt(...)`, which `RelayIO` turns into a
  pending-question event and blocks until an answer comes back. In the spike a terminal plays the UI; in the app
  it would be an event out plus an answer in. A captcha prompt carries `img_url` so the UI can show the image.
- JS bot checks (ACIC / JS challenges) are handled automatically by **headless Playwright**
  (`PlaywrightAcicForm`, `PlaywrightJSAuthForm`). This ran fine from a local machine. **Not tested from a
  container/datacenter IP**, which is the main residual risk.
- An AWS WAF *puzzle* is not solved (needs a paid solver or a human); it surfaces as an error. Not hit in these
  runs.
- Credentials are used once and held in memory only. The cookie jar goes to a temp dir and is deleted. The
  script calls `logout()` so the session also ends on Amazon's side. Never use `AMAZON_OTP_SECRET_KEY` (a
  permanent second-factor key); the user types the one-time code.
- Rate/behaviour: a 40-order pull with full details (one extra request per order) went through in a single
  session without a captcha. The library docs advise waiting hours after repeated captchas.

## 2. Security audit (amazon-orders 4.9.2 and 18 dependencies)
Nothing malicious or exfiltrating found.
- Installed package is **identical to the GitHub tag `4.9.2`** (33 `.py` files, diffed).
- Library code has no `eval`/`exec`/`pickle`/`base64`/sockets/`ctypes`. Only subprocess is `playwright install`
  (user-triggered). All HTTP goes through one `requests` session to the configured Amazon domain.
- Credentials only flow into Amazon's sign-in form fields; nothing logs passwords, OTPs or cookies. The
  captcha-solver extras (capsolver, 2captcha, anticaptcha) are optional and were not installed.
- No `.pth`/`sitecustomize` hooks; every installed file matches its `RECORD` hash; OSV lists no known
  vulnerabilities for any pinned version; none yanked.
- **Caveats:** `amazon-orders` 4.9.2 was 1 day old at install (7 releases in 12 days). Only that package is
  pinned, with no hashes, so transitive dependencies float: lock the set with hashes before relying on it.
  Only the credential/session/browser paths were read closely, and dependencies were not source-diffed. The
  library also reads `~/.config/amazonorders/config.yml` and `AMAZON_USERNAME`/`AMAZON_PASSWORD`, which override
  passed values.

## 3. What comes back (per order)
`order_number`, `order_placed_date` (string), `grand_total`, `subtotal`, `shipping_total`, `total_before_tax`,
`estimated_tax`, `promotion_applied`, `gift_card`, `refund_total`, `payment_method` (+ last 4), `recipient`,
`order_details_link`, `cancelled`, `items[]`, `shipments[]`. No currency field: derive it from the domain.
Item: `title`, `asin`, `price`, `quantity`, `seller`, `link`, `image_link`, `return_eligible_date`.
Shipment: `delivery_status` (None for 41 of 46 shipments), `shipment_id` / `tracking_link` (sometimes).

### amazon.de specifics
- The library forces `amazon.de` into UK English (`en_GB`). Summary rows are matched by lowercase substring
  against US wording, so three amounts came back empty until `amazon_de_labels.py` (a `language_package`
  override) added: `postage`, `before vat`, `estimated vat`, and a start-anchored `vat` for rows labelled just
  `VAT:`.
- Summary-row labels seen: `Item(s) Subtotal:`, `Postage & Packing:`, `Total before VAT:` / `Total Before VAT:`,
  `Estimated VAT:`, `VAT:`, `Promotion Applied:`, `Gift Card Amount:`, `Refund Total`, `Total:`, `Grand Total:`.
  Other domains need their own label check.

## 4. Amount model (all numbers in this section are for the amazon.de sample)
Facts, verified:
- **`grand_total` is what was paid by card**, i.e. after the gift card. It is the number to match against the
  account transaction.
- **Item `price` is the gross unit price**; line amount is `price * (quantity or 1)`. `quantity` is only present
  when it is more than 1 (4 of 50 items, all 2); missing means 1.
- `promotion_applied` and `gift_card` are negative in the raw data. Amazon applies the promotion *after* VAT, so
  it is a gross amount.
- `subtotal` is **net** of VAT (it sits exactly one VAT share below the gross item sum). 21 orders at 19%, 1 at 7%.
- Raw identity (39 of 40 orders): `grand_total = Σ(price*qty) + postage + promotion + gift_card`.

### Proposed sign convention (for the core; input, not a spec change)
Expenses negative, reductions and refunds positive, and every line **gross** (VAT inside the value):

| Line | Amount |
|---|---|
| each item | `-(price * (quantity or 1))` |
| postage | `-(gross postage)`, see below |
| promotion | `+|promotion_applied|` |
| gift card | `+|gift_card|` |
| refund (separate document) | `+refund_total` |

Σ lines = `-grand_total`, which is the (negative) account transaction. If it does not match, emit an explicit
"unexplained difference" line (or flag the document) so the document total always equals the transaction.

### Postage is listed net: gross it up from Amazon's own VAT, not a fixed rate (*single sample*)
In the only order with paid postage, `shipping_total` is net of VAT (`total_before_tax = subtotal + postage`)
and the item-only identity was off by exactly the VAT on postage. A fixed `* 1.19` is also wrong, by 2 cents.
Exact derivation, using the order's totals:

```
vat_on_items   = Σ(price*qty) - subtotal
vat_on_postage = estimated_tax - vat_on_items
gross_postage  = shipping_total + vat_on_postage
```

This reconciled to 0.00 and gave a round price. The order also had a promotion that exactly offset gross postage
(looks like a free-postage promotion). Cross-check available without VAT rows:
`gross_postage = grand_total - Σ(price*qty) - promotion - gift_card`.
Needs more orders with paid postage before being trusted.

## 5. Edge cases and open points
- **~10 of 40 orders show no VAT rows**; `grand_total == subtotal` there (gross). Items are gross anyway, so with
  gross lines VAT is simply not needed. If it is ever needed it cannot be assumed from a single rate (7% exists).
- **Refunds (3):** `refund_total == grand_total`, shipment status `Return complete`. `grand_total` stays the
  original charge; the refund is a separate later transaction. Matching them is a core question.
- **Gift card (9):** negative amount; `grand_total` is net of it.
- Odd, unexplained: one order with `total_before_tax == 0`; `delivery_status` mostly None.
- A quantity-2 order that looked 0.77 off was a gift-card order: it reconciles exactly once the gift card is
  counted (so quantity handling is consistent across all 4 quantity-2 orders).
- Not seen: cancelled orders, gift wrap, coupons, reward points, multibuy/subscription discounts, other VAT
  rates, orders older than 2025, other domains, container/datacenter IPs.
- Fragility: scraping. The library shipped 7 releases in 12 days. Expect periodic breakage.

## 6. Running the spike
```
cd spikes/amazon
.venv/bin/pip install -r requirements.txt        # amazon-orders[browser]==4.9.2
.venv/bin/python a1_login.py --domain amazon.de --time-filter year-2025 --count 40
```
Prompts for email and password (hidden); OTP / captcha questions appear in the terminal. Writes
`out/orders-<domain>.json` (personal data, gitignored), prints field coverage and summary-row labels, signs out,
and deletes the cookie jar. If no browser is installed: `.venv/bin/playwright install chromium`.
`--count` pages history (about 10 orders per page) until reached.

Files: `a1_login.py` (login with `RelayIO`, fetch, coverage), `amazon_de_labels.py` (label override),
`requirements.txt`. Scratch analysis scripts live in the gitignored `.state/`.

## 7. Recommended next steps
1. Importer contract: "give me an authenticated session" plus an event channel for questions. Keep cookies in
   memory only. Run the login in a worker thread, as `RelayIO` does.
2. Test once from the real container and network.
3. Lock dependencies with hashes; re-audit when bumping `amazon-orders`.
4. Collect orders with paid postage and non-19% VAT to harden the gross-up rule.
5. Offer the ZIP-upload route as a no-login fallback.
