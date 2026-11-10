from __future__ import annotations

from app.integrations.paypal.invoicing import invoice_id_from_create_body


def test_invoice_id_from_full_body() -> None:
    assert invoice_id_from_create_body({"id": "INV2-FULL", "status": "DRAFT"}) == "INV2-FULL"


def test_invoice_id_from_self_link_object() -> None:
    body = {
        "rel": "self",
        "href": "https://api.sandbox.paypal.com/v2/invoicing/invoices/INV2-NAMH-BKB3-DHHN-MXTH",
        "method": "GET",
    }
    assert invoice_id_from_create_body(body) == "INV2-NAMH-BKB3-DHHN-MXTH"


def test_invoice_id_from_links_array() -> None:
    body = {
        "links": [
            {
                "rel": "self",
                "href": "https://api-m.sandbox.paypal.com/v2/invoicing/invoices/INV2-LINK",
                "method": "GET",
            }
        ]
    }
    assert invoice_id_from_create_body(body) == "INV2-LINK"


def test_invoice_id_missing() -> None:
    assert invoice_id_from_create_body({"status": "DRAFT"}) is None
