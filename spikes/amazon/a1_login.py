"""A1: headless login with credentials relayed like a web UI would; fetch recent orders.

Models the real backend: AmazonSession.login() blocks in a worker thread; whenever Amazon asks
something (OTP device choice, OTP code, captcha) the RelayIO turns it into a pending "question"
event and blocks until an answer arrives. Here the main thread plays the web UI via the terminal;
in the app it would be an SSE/WebSocket event out + a POST /answer in.

Nothing is persisted: credentials come from getpass (never env/disk) and the cookie jar lives in
a temp dir that is deleted at the end. JS challenges are handled by headless Playwright
(PlaywrightAcicForm / PlaywrightJSAuthForm); an AWS WAF *puzzle* is NOT solved (needs a paid
solver or a human) and surfaces as an error - that is one of the things this spike measures.

    .venv/bin/python a1_login.py --domain amazon.de --count 10
"""
import argparse
import getpass
import json
import queue
import re
import shutil
import tempfile
import threading
from pathlib import Path

from amazonorders import util
from amazonorders.conf import AmazonOrdersConfig
from amazonorders.orders import AmazonOrders
from amazonorders.session import AmazonSession, IODefault

HERE = Path(__file__).parent
ANSWER_TIMEOUT = 300


class RelayIO(IODefault):
    """Turns the library's blocking echo()/prompt() calls into events + a blocking answer queue."""

    def __init__(self) -> None:
        self.events: queue.Queue = queue.Queue()
        self.answers: queue.Queue = queue.Queue()

    def echo(self, msg: str, **kwargs) -> None:
        if msg:
            self.events.put({"kind": "info", "msg": msg})

    def prompt(self, msg: str, type=None, **kwargs):
        self.events.put({"kind": "question", "msg": msg,
                         "choices": kwargs.get("choices"), "img_url": kwargs.get("img_url")})
        return self.answers.get(timeout=ANSWER_TIMEOUT)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", required=True)
    ap.add_argument("--count", type=int, default=10,
                    help="max orders to keep; history pages (~10 orders) are fetched until reached")
    ap.add_argument("--time-filter", default="months-3")
    args = ap.parse_args()

    username = input("Amazon e-mail: ")
    password = getpass.getpass("Amazon password: ")

    jar_dir = Path(tempfile.mkdtemp(prefix="amazon-spike-"))
    session = None
    try:
        config = AmazonOrdersConfig(data={
            "domain": args.domain,
            "cookie_jar_path": str(jar_dir / "cookies.json"),
            "language_package": "amazon_de_labels" if args.domain == "amazon.de" else None,
            "auth_forms_classes": [
                "amazonorders.contrib.browser.playwright.PlaywrightAcicForm",
                "amazonorders.contrib.browser.playwright.PlaywrightJSAuthForm",
            ],
        })
        relay = RelayIO()
        session = AmazonSession(username=username, password=password, io=relay, config=config)
        del password

        result: dict = {}

        def worker() -> None:
            try:
                session.login()
            except Exception as e:  # surfaced to the "UI" below
                result["error"] = e

        t = threading.Thread(target=worker, daemon=True)
        t.start()

        while t.is_alive() or not relay.events.empty():
            try:
                ev = relay.events.get(timeout=0.5)
            except queue.Empty:
                continue
            if ev["kind"] == "info":
                print(f"[amazon] {ev['msg']}")
                continue
            if ev["img_url"]:  # captcha: the UI would render this image
                img = session.session.get(ev["img_url"]).content
                p = HERE / "out"
                p.mkdir(exist_ok=True)
                (p / "captcha.png").write_bytes(img)
                print(f"[captcha image saved to {p / 'captcha.png'}]")
            print(f"[question] {ev['msg']}" + (f" choices={ev['choices']}" if ev["choices"] else ""))
            relay.answers.put(input("--> "))

        if "error" in result:
            print(f"LOGIN FAILED: {type(result['error']).__name__}: {result['error']}")
            return
        print("signed in (headless)")

        # limit: stop paging once enough orders are collected (whole pages of ~10), so details
        # (one extra request per order) are only fetched for what we keep
        page = AmazonOrders(session).get_order_history_page(
            time_filter=args.time_filter, full_details=True, limit=args.count)
        orders = page.items[: args.count]
        print(f"more orders available beyond --count: {page.has_more or len(page.items) > args.count}")
        dump = [o.to_dict() for o in orders]
        out = HERE / "out"
        out.mkdir(exist_ok=True)
        (out / f"orders-{args.domain}.json").write_text(
            json.dumps(dump, indent=2, default=str, ensure_ascii=False))
        print(f"fetched {len(orders)} orders -> out/orders-{args.domain}.json")
        summarize(dump)
        dump_labels(orders, config)
    finally:
        if session is not None and session.is_authenticated:
            try:
                session.logout()  # ends the session on Amazon's side too, not just locally
                print("signed out")
            except Exception as e:
                print(f"sign-out failed ({e}); sign out of all devices in your Amazon account")
        shutil.rmtree(jar_dir, ignore_errors=True)
        print("cookie jar deleted")


def summarize(orders: list[dict]) -> None:
    """Which fields did we actually get?"""
    fields = ["order_number", "order_placed_date", "grand_total", "subtotal", "total_before_tax",
              "estimated_tax", "shipping_total", "promotion_applied", "payment_method",
              "order_details_link", "items", "shipments"]
    print("\nfield coverage over orders:")
    for f in fields:
        print(f"  {f:20} {sum(1 for o in orders if o.get(f) not in (None, '', []))}/{len(orders)}")
    items = [i for o in orders for i in (o.get("items") or [])]
    print(f"\nfield coverage over {len(items)} items:")
    for f in ["title", "asin", "quantity", "price", "seller", "link"]:
        print(f"  {f:20} {sum(1 for i in items if i.get(f) not in (None, '', []))}/{len(items)}")


def dump_labels(orders, config) -> None:
    """Print the wording of the order-summary rows (labels only, digits masked, no amounts),
    plus what the quantity element contains - to see why tax/shipping/quantity parse as None."""
    sel = config.selectors
    labels: dict[str, int] = {}
    quantities: dict[str, int] = {}
    for o in orders:
        for tag in util.select(o.parsed, sel.FIELD_ORDER_SUBTOTALS_TAG_ITERATOR_SELECTOR):
            inner = util.select_one(tag, sel.FIELD_ORDER_SUBTOTALS_INNER_TAG_SELECTOR)
            text = tag.get_text(" ", strip=True)
            if inner:
                text = text.replace(inner.get_text(" ", strip=True), "")
            label = re.sub(r"\d+", "#", " ".join(text.split()))
            labels[label] = labels.get(label, 0) + 1
        for item in o.items:
            for tag in util.select(item.parsed, sel.FIELD_ITEM_QUANTITY_SELECTOR):
                q = re.sub(r"\d+", "#", " ".join(tag.get_text(" ", strip=True).split()))
                quantities[q] = quantities.get(q, 0) + 1
    print("\nsummary-row labels (count over orders):")
    for label, n in sorted(labels.items(), key=lambda kv: -kv[1]):
        print(f"  {n}x  {label!r}")
    print("\nquantity element texts (digits masked):", quantities or "no quantity element found")


if __name__ == "__main__":
    main()
