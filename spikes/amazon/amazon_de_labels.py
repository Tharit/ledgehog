"""amazon-orders language package for amazon.de (served in UK English: en_GB).

The library's default labels are US wording; the order-summary rows on amazon.de read
'Postage & Packing:', 'Total before VAT:', 'Estimated VAT:'. Matching is by lowercase substring.
"""
from amazonorders.selectors import Selectors as DefaultSelectors


class Selectors(DefaultSelectors):
    FIELD_ORDER_SHIPPING_TOTAL_LABELS = ["shipping", "postage"]
    FIELD_ORDER_TOTAL_BEFORE_TAX_LABELS = ["before tax", "before vat"]
    FIELD_ORDER_ESTIMATED_TAX_LABELS = ["estimated tax", "tax collected", "estimated vat"]
