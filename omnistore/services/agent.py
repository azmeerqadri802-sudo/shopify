"""Gemini function-calling agent and omnichannel commerce tools."""

from __future__ import annotations

import json
import logging
import smtplib
import ssl
from email.message import EmailMessage
from typing import Any, Callable

from google import genai
from google.genai import types

from ..adapters import ADAPTERS
from ..database import SecureDatabase
from ..models import UniversalProduct
from .bulk import process_bulk_file
from .channels import whatsapp_summary

LOG = logging.getLogger(__name__)
DEFAULT_MODEL = "gemini-3.8-flash"

TOOL_DECLARATIONS = [
    {"name": "add_product", "description": "Use AI to normalize and create a product on selected connected stores.",
     "parameters": {"type": "OBJECT", "properties": {
         "title": {"type": "STRING"}, "price": {"type": "NUMBER"},
         "description": {"type": "STRING"}, "image_url": {"type": "STRING"},
         "sku": {"type": "STRING"}, "target_platforms": {"type": "ARRAY", "items": {"type": "STRING"}},
     }, "required": ["title", "price"]}},
    {"name": "list_on_all_platforms", "description": "Create this product on every connected marketplace adapter.",
     "parameters": {"type": "OBJECT", "properties": {
         "title": {"type": "STRING"}, "price": {"type": "NUMBER"},
         "description": {"type": "STRING"}, "image_url": {"type": "STRING"},
         "sku": {"type": "STRING"},
     }, "required": ["title", "price"]}},
    {"name": "process_bulk_file", "description": "Read an Excel, CSV, DOCX, or Google Sheets source and sequentially create each row on selected platforms.",
     "parameters": {"type": "OBJECT", "properties": {
         "file_source": {"type": "STRING"},
         "target_platforms": {"type": "ARRAY", "items": {"type": "STRING"}},
     }, "required": ["file_source", "target_platforms"]}},
    {"name": "handle_marketing", "description": "Generate multi-store-aware email and social marketing copy. Does not publish anything.",
     "parameters": {"type": "OBJECT", "properties": {}}},
    {"name": "reply_to_email", "description": "Draft a store-aware customer email reply; sends only if automatic email sending was explicitly enabled in Settings.",
     "parameters": {"type": "OBJECT", "properties": {
         "customer_email": {"type": "STRING"}, "intent": {"type": "STRING"},
     }, "required": ["customer_email", "intent"]}},
]


class GeminiAgent:
    """Bounded Gemini function-call loop whose functions remain local and explicit."""

    def __init__(self, database: SecureDatabase, log: Callable[[str], None] | None = None,
                 progress: Callable[[int, int, str], None] | None = None) -> None:
        self.db = database
        self.log = log or (lambda _: None)
        self.progress = progress
        google = database.get_credentials("google")
        api_key = str(google.get("api_key") or "").strip()
        if not api_key:
            raise RuntimeError("Add a Google Gemini API key in Settings before using the AI agent")
        self.model = str(google.get("model_name") or DEFAULT_MODEL).strip()
        self.google_credentials = google
        self._adapter_cache: dict[str, Any] = {}
        self.client = genai.Client(api_key=api_key)
        self._tool_schemas = [types.FunctionDeclaration(**decl) for decl in TOOL_DECLARATIONS]
        self._config = types.GenerateContentConfig(
            system_instruction=(
                "You are OmniStore, a careful omnichannel commerce copilot. Use tools only when a user "
                "requests that action. Never claim a product was published unless a tool confirms it. "
                "Marketplace tools create draft listings where the platform supports drafts. Ask a "
                "clarifying question rather than inventing prices, URLs, or product details. Mention "
                "which stores are connected and disclose partial failures."
            ),
            tools=[types.Tool(function_declarations=self._tool_schemas)],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            temperature=0.3,
        )

    def connected_adapters(self) -> dict[str, Any]:
        available: dict[str, Any] = {}
        for name, adapter_type in ADAPTERS.items():
            credentials = self.db.get_credentials(name)
            if not credentials:
                continue
            try:
                available[name] = adapter_type(credentials)
                self._adapter_cache[name] = available[name]
            except Exception as exc:
                self.log(f"{name.title()} credentials need attention: {exc}")
        return available

    def _adapter(self, name: str) -> Any:
        name = str(name).lower().replace(" ", "_")
        if name not in ADAPTERS:
            raise ValueError(f"Unknown marketplace: {name}")
        if name in self._adapter_cache:
            return self._adapter_cache[name]
        creds = self.db.get_credentials(name)
        if not creds:
            raise RuntimeError(f"{name.title()} is not configured in Settings")
        self._adapter_cache[name] = ADAPTERS[name](creds)
        return self._adapter_cache[name]

    def _call_model(self, prompt: str, *, json_mode: bool = False) -> str:
        config = types.GenerateContentConfig(
            system_instruction="Return only valid JSON." if json_mode else
            "Write concise, accurate copy for a digital accessories business. Do not invent product specifications.",
            response_mime_type="application/json" if json_mode else "text/plain",
            temperature=0.25,
        )
        response = self.client.models.generate_content(model=self.model, contents=prompt, config=config)
        text = str(getattr(response, "text", "") or "").strip()
        if not text:
            raise RuntimeError("Gemini returned an empty response")
        return text

    def enrich_product(self, row: dict[str, Any]) -> UniversalProduct:
        base = UniversalProduct.from_mapping(row)
        prompt = (
            "Normalize this product once for multiple commerce channels. Improve the description for clarity "
            "and create 5-8 useful SEO tags. Do not invent compatibility, materials, warranty, or performance "
            "claims. Preserve supplied facts. Return JSON with keys description and tags (array of strings).\n" +
            json.dumps({"title": base.title, "description": base.description, "price": str(base.price),
                        "product_type": base.product_type, "vendor": base.vendor}, ensure_ascii=False)
        )
        try:
            content = json.loads(self._call_model(prompt, json_mode=True))
            base.description = str(content.get("description") or base.description)
            generated_tags = content.get("tags", [])
            if isinstance(generated_tags, list):
                base.tags = [str(tag) for tag in generated_tags if str(tag).strip()][:12]
        except (ValueError, TypeError, json.JSONDecodeError):
            if not base.description:
                raise RuntimeError("Gemini did not return usable product copy")
            self.log(f"AI copy normalization was unavailable for {base.title}; supplied description retained")
        return base

    def add_product(self, values: dict[str, Any], targets: list[str]) -> dict[str, Any]:
        row = {**values}
        if row.get("image_url") and not row.get("image_urls"):
            row["image_urls"] = [row["image_url"]]
        product = self.enrich_product(row)
        outcomes = []
        for platform in dict.fromkeys(targets):
            try:
                result = self._adapter(platform).create_product(product)
                outcomes.append({"platform": platform, "ok": True,
                                 "external_id": result.get("id") or result.get("sku") or "created"})
                self.log(f"Created {product.title} on {platform}")
            except Exception as exc:
                outcomes.append({"platform": platform, "ok": False, "error": str(exc)})
                self.log(f"Could not create {product.title} on {platform}: {exc}")
        return {"title": product.title, "outcomes": outcomes}

    def bulk(self, file_source: str, targets: list[str]) -> dict[str, Any]:
        return process_bulk_file(file_source, targets, google_credentials=self.google_credentials,
                                 resolve_adapter=self._adapter, enrich_product=self.enrich_product,
                                 progress=self.progress)

    def handle_marketing(self) -> str:
        adapters = self.connected_adapters()
        orders = self.db.recent_orders(100)
        store_names = sorted(adapters.keys())
        product_names: list[str] = []
        for entry in orders[:40]:
            payload = entry["data"]
            for item in payload.get("line_items", [])[:5] if isinstance(payload.get("line_items", []), list) else []:
                if isinstance(item, dict):
                    title = item.get("title") or item.get("name")
                    if title and str(title) not in product_names:
                        product_names.append(str(title))
        context = {"connected_stores": store_names, "recent_order_count": len(orders),
                   "recent_product_names": product_names[:25]}
        prompt = ("Generate a coordinated marketing pack for this multi-store digital-accessories business. "
                  "Return an email subject and body, three social captions, and a short offer idea. "
                  "Do not invent discounts or product specifications. Context: " + json.dumps(context))
        return self._call_model(prompt)

    def reply_to_email(self, customer_email: str, intent: str) -> dict[str, Any]:
        if "@" not in customer_email or len(customer_email) > 254:
            raise ValueError("Enter a valid customer email address")
        orders = self.db.recent_orders(200)
        context = []
        for entry in orders:
            data = entry["data"]
            email = str((data.get("customer") or {}).get("email") or data.get("email") or "").lower()
            if email == customer_email.lower():
                context.append({"platform": entry["platform"], "id": entry["external_id"],
                                "status": data.get("financial_status") or data.get("status"),
                                "items": [item.get("title") for item in data.get("line_items", [])[:8]
                                          if isinstance(item, dict)]})
        prompt = ("Draft a polite customer support reply for a multi-store digital accessories shop. "
                  "Do not claim refunds, deliveries, or policy exceptions occurred. If context is insufficient, "
                  "request the missing order details.\nIntent: " + intent + "\nMatching order context: " +
                  json.dumps(context[:5], ensure_ascii=False))
        body = self._call_model(prompt)
        general = self.db.get_credentials("general")
        smtp = self.db.get_credentials("smtp")
        if not general.get("auto_send_email"):
            return {"status": "draft", "to": customer_email, "body": body}
        if not all(smtp.get(key) for key in ("host", "username", "password", "from_address")):
            raise RuntimeError("Automatic email sending is enabled but SMTP credentials are incomplete")
        message = EmailMessage()
        message["From"] = smtp["from_address"]
        message["To"] = customer_email
        message["Subject"] = str(smtp.get("reply_subject") or "Re: Your order")[:200]
        message.set_content(body)
        context_ssl = ssl.create_default_context()
        with smtplib.SMTP(smtp["host"], int(smtp.get("port") or 587), timeout=30) as server:
            server.starttls(context=context_ssl)
            server.login(smtp["username"], smtp["password"])
            server.send_message(message)
        return {"status": "sent", "to": customer_email}

    def format_order_report(self, order: dict[str, Any], platform: str) -> str:
        # Only send order number, amounts, statuses and line-item names to Gemini.
        items = order.get("line_items") or order.get("items") or []
        safe_order = {
            "order_number": order.get("name") or order.get("order_number") or order.get("id"),
            "total": order.get("total_price") or order.get("total"),
            "currency": order.get("currency"),
            "status": order.get("financial_status") or order.get("status"),
            "items": [{"name": item.get("title") or item.get("name"), "quantity": item.get("quantity") or 1}
                      for item in items[:8] if isinstance(item, dict)] if isinstance(items, list) else [],
        }
        try:
            return self._call_model(
                f"Format this new {platform} order as a concise WhatsApp operations report (under 700 characters). "
                "Do not add customer contact or address information. Data: " + json.dumps(safe_order),
            )
        except Exception as exc:
            self.log(f"Gemini order formatting unavailable; used standard template: {exc}")
            return whatsapp_summary(order, platform)

    def run(self, prompt: str) -> str:
        if not prompt.strip():
            return "Enter a command first."
        contents: list[types.Content] = [types.Content(role="user", parts=[types.Part(text=prompt.strip())])]
        for _round in range(6):
            response = self.client.models.generate_content(model=self.model, contents=contents,
                                                           config=self._config)
            candidate = response.candidates[0].content if response.candidates else None
            if candidate is None:
                return str(getattr(response, "text", "") or "Gemini returned no response")
            calls = [part.function_call for part in candidate.parts
                     if getattr(part, "function_call", None) and part.function_call.name]
            if not calls:
                return str(getattr(response, "text", "") or "Task completed.")
            contents.append(candidate)
            function_results = []
            for call in calls[:8]:
                try:
                    result = self._execute(str(call.name), dict(call.args or {}))
                    response_body = {"ok": True, "result": result}
                except Exception as exc:
                    self.log(f"Tool {call.name} failed: {exc}")
                    response_body = {"ok": False, "error": str(exc)}
                function_results.append(types.Part.from_function_response(
                    name=call.name, response=response_body))
            contents.append(types.Content(role="user", parts=function_results))
        return "I stopped after the safe tool-call limit. Review the activity log for completed actions."

    def _execute(self, name: str, args: dict[str, Any]) -> Any:
        if name == "add_product":
            targets = args.get("target_platforms") or list(self.connected_adapters())
            return self.add_product(args, list(targets))
        if name == "list_on_all_platforms":
            return self.add_product(args, list(self.connected_adapters()))
        if name == "process_bulk_file":
            targets = args.get("target_platforms") or list(self.connected_adapters())
            return self.bulk(str(args["file_source"]), list(targets))
        if name == "handle_marketing":
            return self.handle_marketing()
        if name == "reply_to_email":
            return self.reply_to_email(str(args["customer_email"]), str(args["intent"]))
        raise ValueError(f"Gemini requested unknown tool: {name}")
