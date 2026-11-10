from datetime import UTC, datetime, timedelta

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID

from app.core.errors import WebhookVerificationError
from app.integrations.paypal.status import capture_block_reason, next_invoice_status
from app.integrations.paypal.webhooks import assert_paypal_cert_url, signed_message, verify_transmission_signature


def test_out_of_order_invoice_event_does_not_rewind_paid():
    status, applied = next_invoice_status("paid", "SENT")
    assert status == "paid"
    assert applied is False


def test_paid_event_advances_sent_invoice():
    status, applied = next_invoice_status("sent", "PAID")
    assert status == "paid"
    assert applied is True


def test_capture_is_blocked_until_buyer_approval():
    reason = capture_block_reason(intent="CAPTURE", provider_status="CREATED", authorization_status=None)
    assert reason is not None
    assert "approval" in reason.lower()
    assert capture_block_reason(intent="CAPTURE", provider_status="APPROVED", authorization_status=None) is None


def test_certificate_url_must_be_a_paypal_host():
    assert_paypal_cert_url("https://api.sandbox.paypal.com/v1/notifications/certs/CERT-1")
    with pytest.raises(WebhookVerificationError):
        assert_paypal_cert_url("https://evil.example/cert.pem")
    with pytest.raises(WebhookVerificationError):
        assert_paypal_cert_url("http://api.sandbox.paypal.com/cert.pem")


def _certificate() -> tuple[rsa.RSAPrivateKey, bytes]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "paypal-test")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    return key, cert.public_bytes(serialization.Encoding.PEM)


def test_webhook_signature_accepts_a_valid_signature_and_rejects_tampering():
    key, pem = _certificate()
    body = b'{"id":"WH-1","event_type":"INVOICING.INVOICE.PAID"}'
    message = signed_message(body, "transmission-1", "2026-11-05T00:00:00Z", "WH-TEST")
    signature = key.sign(message, padding.PKCS1v15(), hashes.SHA256())
    import base64

    encoded = base64.b64encode(signature).decode()
    verify_transmission_signature(
        raw_body=body,
        transmission_id="transmission-1",
        transmission_time="2026-11-05T00:00:00Z",
        transmission_sig=encoded,
        cert_pem=pem,
        webhook_id="WH-TEST",
        auth_algo="SHA256withRSA",
    )
    with pytest.raises(WebhookVerificationError):
        verify_transmission_signature(
            raw_body=body + b" ",
            transmission_id="transmission-1",
            transmission_time="2026-11-05T00:00:00Z",
            transmission_sig=encoded,
            cert_pem=pem,
            webhook_id="WH-TEST",
            auth_algo="SHA256withRSA",
        )
