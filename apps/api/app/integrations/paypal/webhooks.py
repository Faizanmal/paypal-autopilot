"""Webhook signature checks.

Local SHA256withRSA verification is the primary path (PayPal's preferred
method, and the only one that works for simulator events). The postback
endpoint is the fallback. Certificate URLs are restricted to PayPal hosts.
"""

from __future__ import annotations

import base64
import logging
import zlib
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from cryptography.x509 import load_pem_x509_certificate

from app.core.errors import WebhookVerificationError
from app.integrations.paypal.client import PayPalClient

logger = logging.getLogger("app.paypal")

ALLOWED_CERT_HOSTS = frozenset(
    {
        "api.paypal.com",
        "api.sandbox.paypal.com",
        "api-m.paypal.com",
        "api-m.sandbox.paypal.com",
    }
)

_HEADER_NAMES = (
    "paypal-transmission-id",
    "paypal-transmission-time",
    "paypal-transmission-sig",
    "paypal-cert-url",
    "paypal-auth-algo",
)


def header_value(headers: Mapping[str, str], name: str) -> str:
    wanted = name.lower()
    for key, value in headers.items():
        if key.lower() == wanted:
            return value.strip()
    return ""


def assert_paypal_cert_url(cert_url: str) -> None:
    parsed = urlsplit(cert_url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or host not in ALLOWED_CERT_HOSTS:
        raise WebhookVerificationError("PayPal certificate URL is not a PayPal host.")


def signed_message(raw_body: bytes, transmission_id: str, transmission_time: str, webhook_id: str) -> bytes:
    crc = zlib.crc32(raw_body) & 0xFFFFFFFF
    return f"{transmission_id}|{transmission_time}|{webhook_id}|{crc}".encode()


def verify_transmission_signature(
    *,
    raw_body: bytes,
    transmission_id: str,
    transmission_time: str,
    transmission_sig: str,
    cert_pem: bytes,
    webhook_id: str,
    auth_algo: str,
) -> None:
    if auth_algo.upper() != "SHA256WITHRSA":
        raise WebhookVerificationError("Unsupported PayPal signature algorithm.")
    message = signed_message(raw_body, transmission_id, transmission_time, webhook_id)
    try:
        certificate = load_pem_x509_certificate(cert_pem)
        public_key = certificate.public_key()
        if not isinstance(public_key, RSAPublicKey):
            raise WebhookVerificationError("PayPal certificate is not an RSA key.")
        public_key.verify(base64.b64decode(transmission_sig), message, padding.PKCS1v15(), hashes.SHA256())
    except (InvalidSignature, ValueError) as exc:
        raise WebhookVerificationError("PayPal webhook signature is invalid.") from exc


def require_webhook_headers(headers: Mapping[str, str]) -> dict[str, str]:
    found = {name: header_value(headers, name) for name in _HEADER_NAMES}
    missing = [name for name, value in found.items() if not value]
    if missing:
        raise WebhookVerificationError("PayPal webhook is missing signature headers.")
    assert_paypal_cert_url(found["paypal-cert-url"])
    return found


class PayPalWebhookVerifier:
    """Downloads the PayPal cert and verifies the transmission locally."""

    def __init__(self, client: PayPalClient, webhook_id: str, *, http: httpx.AsyncClient | None = None) -> None:
        self._client = client
        self._webhook_id = webhook_id
        self._http = http or httpx.AsyncClient(timeout=httpx.Timeout(10.0), follow_redirects=False)
        self._owns_http = http is None
        self._certs: dict[str, bytes] = {}

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def verify(self, raw_body: bytes, headers: Mapping[str, str]) -> None:
        if not self._webhook_id:
            raise WebhookVerificationError("PAYPAL_WEBHOOK_ID is not configured.")
        found = require_webhook_headers(headers)
        try:
            cert = await self._certificate(found["paypal-cert-url"])
        except WebhookVerificationError:
            await self._verify_postback(raw_body, found)
            return
        verify_transmission_signature(
            raw_body=raw_body,
            transmission_id=found["paypal-transmission-id"],
            transmission_time=found["paypal-transmission-time"],
            transmission_sig=found["paypal-transmission-sig"],
            cert_pem=cert,
            webhook_id=self._webhook_id,
            auth_algo=found["paypal-auth-algo"],
        )

    async def _certificate(self, cert_url: str) -> bytes:
        assert_paypal_cert_url(cert_url)
        cached = self._certs.get(cert_url)
        if cached is not None:
            return cached
        response = await self._http.get(cert_url)
        if response.status_code != 200 or b"BEGIN CERTIFICATE" not in response.content:
            raise WebhookVerificationError("PayPal certificate could not be downloaded.")
        self._certs[cert_url] = response.content
        return response.content

    async def _verify_postback(self, raw_body: bytes, found: dict[str, str]) -> None:
        try:
            event: Any = httpx.Response(200, content=raw_body).json()
        except ValueError as exc:
            raise WebhookVerificationError("PayPal webhook body is not JSON.") from exc
        if not isinstance(event, dict):
            raise WebhookVerificationError("PayPal webhook body is not an object.")
        try:
            result = await self._client.call(
                "POST",
                "/v1/notifications/verify-webhook-signature",
                json_body={
                    "transmission_id": found["paypal-transmission-id"],
                    "transmission_time": found["paypal-transmission-time"],
                    "cert_url": found["paypal-cert-url"],
                    "auth_algo": found["paypal-auth-algo"],
                    "transmission_sig": found["paypal-transmission-sig"],
                    "webhook_id": self._webhook_id,
                    "webhook_event": event,
                },
            )
        except Exception as exc:
            logger.warning("paypal_webhook_verify_failed", extra={"context": {"error": type(exc).__name__}})
            raise WebhookVerificationError("PayPal webhook signature is invalid.") from exc
        status = result.body.get("verification_status")
        if status != "SUCCESS":
            raise WebhookVerificationError("PayPal webhook signature is invalid.")
