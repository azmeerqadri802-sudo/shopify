"""Verified webhook intake and WhatsApp order-report delivery."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

import requests

LOG = logging.getLogger(__name__)


def verify_signature(body: bytes, secret: str, supplied: str) -> bool:
    if not secret or not supplied:
        return False
    digest = base64.b64encode(hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()).decode("ascii")
    return hmac.compare_digest(digest, supplied.strip())


def whatsapp_summary(order: dict[str, Any], platform: str) -> str:
    """Build a minimal order summary without sharing customer PII to third parties."""
    order_id = order.get("name") or order.get("order_number") or order.get("id") or "New order"
    total = order.get("total_price") or order.get("total") or order.get("amount") or "unknown"
    currency = order.get("currency") or ""
    status = order.get("financial_status") or order.get("status") or "status unavailable"
    lines = order.get("line_items") or order.get("items") or []
    product_lines = []
    for item in lines[:8] if isinstance(lines, list) else []:
        if isinstance(item, dict):
            name = item.get("title") or item.get("name") or "Item"
            quantity = item.get("quantity") or item.get("qty") or 1
            product_lines.append(f"• {name} × {quantity}")
    body = "\n".join(product_lines) or "• Items were not supplied by the marketplace"
    return f"📦 New {platform.title()} order {order_id}\nTotal: {currency} {total}\nStatus: {status}\n{body}"


def send_whatsapp_report(credentials: dict[str, Any], text: str) -> dict[str, Any]:
    token = str(credentials.get("access_token", "")).strip()
    sender_id = str(credentials.get("phone_number_id", "")).strip()
    recipient = str(credentials.get("recipient_number", "")).strip()
    if not token or not sender_id or not recipient:
        raise RuntimeError("WhatsApp needs a Meta access token, sender phone number ID, and recipient number")
    version = str(credentials.get("api_version") or "v23.0")
    response = requests.post(
        f"https://graph.facebook.com/{version}/{sender_id}/messages",
        headers={"Authorization": f"Bearer {token}"},
        json={"messaging_product": "whatsapp", "to": recipient, "type": "text",
              "text": {"preview_url": False, "body": text[:4000]}},
        timeout=30,
    )
    if not response.ok:
        raise RuntimeError(f"WhatsApp Cloud API returned HTTP {response.status_code}: {response.text[:400]}")
    return response.json()


class OrderIntegrations:
    """Local HMAC-verified Shopify/Woo webhook receiver + Amazon/Daraz poller.

    Bind on loopback by default. A public Shopify/Woo webhook needs a trusted
    HTTPS relay that forwards the original body and signature headers.
    """

    def __init__(self, database: Any, adapters: dict[str, Any], log: Callable[[str], None],
                 formatter: Callable[[dict[str, Any], str], str] | None = None,
                 host: str = "127.0.0.1", port: int = 8787, poll_seconds: int = 180,
                 enable_webhooks: bool = True) -> None:
        self.db, self.adapters, self.log = database, adapters, log
        self.formatter = formatter or whatsapp_summary
        self.host, self.port = host, int(port)
        self.poll_seconds = max(30, int(poll_seconds))
        self.enable_webhooks = enable_webhooks
        self._server: ThreadingHTTPServer | None = None
        self._threads: list[threading.Thread] = []
        self._stop = threading.Event()

    def _route(self, platform: str, order: dict[str, Any]) -> None:
        external_id = str(order.get("id") or order.get("order_id") or order.get("name") or "")
        if not external_id:
            self.log(f"Ignored {platform} order without an ID")
            return
        if not self.db.insert_order_if_new(platform, external_id, order):
            return
        self.log(f"New {platform} order received ({external_id})")
        try:
            text = self.formatter(order, platform)
            send_whatsapp_report(self.db.get_credentials("whatsapp"), text)
            self.log(f"WhatsApp report sent for {platform} order {external_id}")
        except Exception as exc:
            self.log(f"Order saved; WhatsApp report could not be sent: {exc}")

    def start(self) -> None:
        if self.enable_webhooks and not self._server:
            owner = self

            class Handler(BaseHTTPRequestHandler):
                def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler protocol
                    route = self.path.split("?", 1)[0]
                    platform = {"/webhooks/shopify": "shopify", "/webhooks/woocommerce": "woocommerce"}.get(route)
                    if not platform:
                        self.send_error(404)
                        return
                    length = min(int(self.headers.get("Content-Length", "0")), 2_000_000)
                    body = self.rfile.read(length)
                    creds = owner.db.get_credentials(platform)
                    secret = str(creds.get("webhook_secret", ""))
                    signature = self.headers.get("X-Shopify-Hmac-Sha256", "") if platform == "shopify" \
                        else self.headers.get("X-WC-Webhook-Signature", "")
                    if not verify_signature(body, secret, signature):
                        owner.log(f"Rejected {platform} webhook with an invalid HMAC")
                        self.send_error(401)
                        return
                    try:
                        payload = json.loads(body.decode("utf-8"))
                        if not isinstance(payload, dict):
                            raise ValueError("Expected a JSON order object")
                    except (UnicodeError, ValueError):
                        self.send_error(400)
                        return
                    owner._route(platform, payload)
                    self.send_response(202)
                    self.end_headers()
                    self.wfile.write(b"accepted")

                def log_message(self, fmt: str, *args: Any) -> None:
                    LOG.debug("Webhook receiver: " + fmt, *args)

            try:
                self._server = ThreadingHTTPServer((self.host, self.port), Handler)
                self._server.daemon_threads = True
                thread = threading.Thread(target=self._server.serve_forever,
                                          name="omni-webhook-server", daemon=True)
                thread.start()
                self._threads.append(thread)
                self.log(f"Webhook listener ready at http://{self.host}:{self.port}/webhooks/{{shopify,woocommerce}}")
            except OSError as exc:
                self.log(f"Webhook listener could not bind port {self.port}: {exc}")
        poller = threading.Thread(target=self._poll_loop, name="omni-order-poller", daemon=True)
        poller.start()
        self._threads.append(poller)

    def _poll_loop(self) -> None:
        while not self._stop.is_set():
            from datetime import datetime, timedelta, timezone
            created_after = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
            for platform in ("amazon", "daraz"):
                adapter = self.adapters.get(platform)
                if adapter is None:
                    continue
                try:
                    orders = adapter.fetch_orders(created_after=created_after)
                    for order in orders:
                        if isinstance(order, dict):
                            self._route(platform, order)
                except Exception as exc:
                    self.log(f"{platform.title()} order polling unavailable: {exc}")
            self._stop.wait(self.poll_seconds)

    def stop(self) -> None:
        self._stop.set()
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
