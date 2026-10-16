"""A1: fetch recent Amazon orders via amazon-orders, signing in through a browser window.

The password / OTP / captcha are typed into Amazon's own page inside a Playwright-controlled
browser; this script only ever sees the resulting cookies. By default the cookie jar lives in a
throwaway temp dir and is deleted when the script ends (nothing credential-like stays on disk).

    .venv/bin/python a1_browser_login.py --domain amazon.de --count 10

Output (personal data, gitignored): out/orders-<domain>.json
"""
import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path

from amazonorders.conf import AmazonOrdersConfig
from amazonorders.contrib.browser.playwright import PlaywrightBrowserLogin
from amazonorders.orders import AmazonOrders
from amazonorders.session import AmazonSession

HERE = Path(__file__).parent


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", required=True, help="e.g. amazon.de, amazon.com")
    ap.add_argument("--count", type=int, default=10, help="max orders to keep (one history page)")
    ap.add_argument("--time-filter", default="months-3", help="last30 | months-3 | year-YYYY")
    ap.add_argument("--keep-session", action="store_true",
                    help="keep the cookie jar in .state/ (it IS a credential) to test session reuse")
    args = ap.parse_args()

    if args.keep_session:
        jar_dir = HERE / ".state"
        jar_dir.mkdir(exist_ok=True)
    else:
        jar_dir = Path(tempfile.mkdtemp(prefix="amazon-spike-"))
    jar = jar_dir / "cookies.json"

    try:
        config = AmazonOrdersConfig(data={"domain": args.domain, "cookie_jar_path": str(jar)})
        session = AmazonSession(config=config)

        if jar.exists():
            print(f"reusing persisted session at {jar}")
            session.login()  # reuses persisted cookies; falls through to a normal login if rejected
        if not session.is_authenticated:
            PlaywrightBrowserLogin(session).login()
        print("signed in")

        orders = AmazonOrders(session).get_order_history(
            time_filter=args.time_filter, full_details=True, keep_paging=False)[: args.count]
        print(f"fetched {len(orders)} orders")

        dump = [o.to_dict() if hasattr(o, "to_dict") else vars(o) for o in orders]
        out = HERE / "out"
        out.mkdir(exist_ok=True)
        path = out / f"orders-{args.domain}.json"
        path.write_text(json.dumps(dump, indent=2, default=str, ensure_ascii=False))
        print(f"wrote {path}")
        summarize(dump)
    finally:
        if not args.keep_session:
            shutil.rmtree(jar_dir, ignore_errors=True)
            print("cookie jar deleted")


def summarize(orders: list[dict]) -> None:
    """Which fields did we actually get? (A1 question: price/tax/shipping on .de?)"""
    fields = ["order_number", "order_date", "grand_total", "currency", "payment_method",
              "invoice_link", "items", "shipments"]
    print("\nfield coverage over orders:")
    for f in fields:
        have = sum(1 for o in orders if o.get(f) not in (None, "", []))
        print(f"  {f:16} {have}/{len(orders)}")
    item_fields = ["title", "quantity", "price", "tax", "shipping", "promotions"]
    items = [i for o in orders for i in (o.get("items") or [])]
    print(f"\nfield coverage over {len(items)} items:")
    for f in item_fields:
        have = sum(1 for i in items if i.get(f) not in (None, "", []))
        print(f"  {f:16} {have}/{len(items)}")


if __name__ == "__main__":
    main()
