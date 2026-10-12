# Gemini-backed LangChain tool agent and outbound integrations.

from __future__ import annotations

import html
import json
import math
import re
import smtplib
from email.message import EmailMessage
from typing import Any, Callable
from urllib.parse import quote

import requests
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langchain_google_genai import ChatGoogleGenerativeAI

from .config import AppConfig, SettingsStore
from .shopify_client import ShopifyClient


class AgentError(RuntimeError):
    pass


class StoreAgent:
    """Run a bounded LangChain tool loop; all side effects are implemented locally."""

    def __init__(
        self,
        config: AppConfig,
        settings: SettingsStore,
        approval_callback: Callable[[str], bool],
        log_callback: Callable[[str], None] | None = None,
    ) -> None:
        api_key = settings.get_secret("gemini_api_key")
        if not api_key:
            raise AgentError("Save a Gemini API key in Settings first.")
        self.config = config
        self.settings = settings
        self.approval_callback = approval_callback
        self.log = log_callback or (lambda _message: None)
        self.llm = ChatGoogleGenerativeAI(
            model=config.gemini_model.strip() or "gemini-3.8-flash",
            api_key=api_key,
            max_retries=2,
            timeout=60,
        )
        self.tools = [
            StructuredTool.from_function(
                func=self.add_product, name="add_product",
                description="Generate SEO copy and create a Shopify draft product with title, image URL, and price.",
            ),
            StructuredTool.from_function(
                func=self.handle_marketing, name="handle_marketing",
                description="Generate promotional email and social media copy. Does not send or publish it.",
            ),
            StructuredTool.from_function(
                func=self.reply_to_email, name="reply_to_email",
                description="Draft and send a plain-text customer email reply using SMTP after approval.",
            ),
            StructuredTool.from_function(
                func=self.send_whatsapp_report, name="send_whatsapp_report",
                description="Format order webhook data and send a WhatsApp report to the saved destination.",
            ),
        ]
        self.tools_by_name = {tool.name: tool for tool in self.tools}

    def run(self, command: str) -> str:
        command = command.strip()
        if not command:
            raise AgentError("Enter a command first.")
        messages = [
            SystemMessage(content=(
                "You are a Shopify store operations assistant for digital accessories. "
                "Use tools only when needed. Never claim an action succeeded unless its tool returns success. "
                "Ask for missing required information instead of guessing prices, email addresses, or order data. "
                "Shopify products are created as drafts. Outbound email and product creation require approval. "
                "Do not expose credentials or include unnecessary customer personal data in reports."
            )),
            HumanMessage(content=command),
        ]
        model = self.llm.bind_tools(self.tools)
        for _turn in range(8):
            response: AIMessage = model.invoke(messages)
            messages.append(response)
            calls = getattr(response, "tool_calls", None) or []
            if not calls:
                return self._content_as_text(response.content)
            for call in calls:
                tool = self.tools_by_name.get(call.get("name", ""))
                if tool is None:
                    messages.append(ToolMessage(content="Unknown tool.", tool_call_id=call.get("id", "unknown")))
                    continue
                tool_id = call.get("id") or "tool-call"
                self.log(f"AI requested tool: {tool.name}")
                try:
                    output = tool.invoke(call.get("args") or {})
                    tool_content = json.dumps(output, ensure_ascii=False, default=str)
                    self.log(f"Completed tool: {tool.name}")
                except Exception as exc:  # The model sees a bounded message, never secrets.
                    tool_content = f"Tool failed: {str(exc)[:700]}"
                    self.log(f"Tool failed: {tool.name}: {str(exc)[:240]}")
                messages.append(ToolMessage(content=tool_content, tool_call_id=tool_id))
        raise AgentError("The assistant reached the tool-call limit. Please make the request more specific.")

    @staticmethod
    def _content_as_text(content: Any) -> str:
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            text_parts = [
                str(block.get("text", ""))
                for block in content
                if isinstance(block, dict) and block.get("type") in {"text", "output_text"} and block.get("text")
            ]
            if text_parts:
                return "\n".join(text_parts).strip()
        return json.dumps(content, ensure_ascii=False, default=str)

    def _approve(self, description: str) -> None:
        if self.config.require_confirmation and not self.approval_callback(description):
            raise AgentError("Action cancelled; approval was not granted.")

    def _shopify(self) -> ShopifyClient:
        return ShopifyClient(self.config, self.settings.get_secret("shopify_admin_api_token"))

    def _generate_json(self, prompt: str) -> dict:
        result = self.llm.invoke(prompt)
        raw = self._content_as_text(result.content)
        raw = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", raw, flags=re.IGNORECASE)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AgentError("Gemini did not return valid structured product copy. Please retry.") from exc
        if not isinstance(data, dict):
            raise AgentError("Gemini returned an unexpected product-copy format.")
        return data

    def add_product(self, title: str, image_url: str = "", price: float = 0) -> dict:
        """Generate descriptions and create a draft Shopify product."""
        title = title.strip()
        if not title:
            raise AgentError("A product title is required.")
        try:
            price_number = float(price)
        except (TypeError, ValueError, OverflowError) as exc:
            raise AgentError("A valid positive product price is required.") from exc
        if not math.isfinite(price_number) or price_number <= 0:
            raise AgentError("A positive product price is required.")
        copy = self._generate_json(
            "Create concise, truthful Shopify product copy for a digital accessory. "
            "Do not invent compatibility claims or technical specifications. Return only JSON with keys "
            "description_paragraphs (array of plain-text strings), seo_title (string), "
            "seo_description (string), and tags (array of short strings).\n"
            f"Product title: {title}\nPrice: {price}"
        )
        paragraphs = copy.get("description_paragraphs")
        if not isinstance(paragraphs, list) or not paragraphs:
            raise AgentError("Generated product copy did not include a description.")
        description_html = "".join(f"<p>{html.escape(str(paragraph))}</p>" for paragraph in paragraphs[:8])
        raw_tags = copy.get("tags", [])
        if not isinstance(raw_tags, list):
            raw_tags = []
        tags = [str(tag).strip()[:40] for tag in raw_tags if str(tag).strip()][:20]
        seo_title = str(copy.get("seo_title") or title)
        seo_description = str(copy.get("seo_description") or paragraphs[0])
        self._approve(f"Create Shopify draft product '{title}' at price {price}.")
        product = self._shopify().create_draft_product(
            title=title, image_url=image_url, price=price,
            description_html=description_html, seo_title=seo_title,
            seo_description=seo_description, tags=tags,
        )
        return {"status": "created as draft", **product}

    def handle_marketing(self) -> str:
        """Generate promotional email and social copy without publishing it."""
        result = self.llm.invoke(
            "Write a concise marketing pack for a Shopify store selling digital accessories. "
            "Return: an email subject, a short email body, and three social captions. "
            "Do not invent a discount, product feature, or delivery promise. Label placeholders clearly."
        )
        return self._content_as_text(result.content)

    @staticmethod
    def _validate_email(address: str) -> str:
        address = address.strip()
        if len(address) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", address):
            raise AgentError("Enter a valid customer email address.")
        return address

    def reply_to_email(self, customer_email: str, intent: str) -> dict:
        """Generate and send a plain-text email reply through configured SMTP."""
        recipient = self._validate_email(customer_email)
        if not intent.strip():
            raise AgentError("Describe the customer's question or requested outcome.")
        draft = self.llm.invoke(
            "Draft a helpful, concise plain-text customer service email. Do not promise refunds, "
            "delivery dates, or policy exceptions that are not specified. Sign off as the store team.\n"
            f"Customer intent: {intent.strip()[:3000]}"
        )
        body = self._content_as_text(draft.content)
        if not body:
            raise AgentError("Gemini returned an empty email draft.")
        preview = body[:700] + ("…" if len(body) > 700 else "")
        self._approve(f"Send email to {recipient}. Draft preview:\n\n{preview}")

        config = self.config
        username = self.settings.get_secret("smtp_username")
        password = self.settings.get_secret("smtp_password")
        if not config.smtp_host or not username or not password:
            raise AgentError("Save SMTP host, username, and password in Settings first.")
        sender = config.smtp_from_email.strip() or username
        message = EmailMessage()
        message["Subject"] = "Re: Your message to our store"
        message["From"] = sender
        message["To"] = recipient
        message.set_content(body)
        try:
            if int(config.smtp_port) == 465:
                with smtplib.SMTP_SSL(config.smtp_host, 465, timeout=25) as smtp:
                    smtp.login(username, password)
                    smtp.send_message(message)
            else:
                with smtplib.SMTP(config.smtp_host, int(config.smtp_port), timeout=25) as smtp:
                    smtp.ehlo()
                    smtp.starttls()
                    smtp.ehlo()
                    smtp.login(username, password)
                    smtp.send_message(message)
        except (OSError, smtplib.SMTPException, ValueError) as exc:
            raise AgentError(f"SMTP could not send the email: {exc}") from exc
        return {"status": "email sent", "recipient": recipient}

    def send_whatsapp_report(self, order_data: dict) -> dict:
        """Format a small order summary and send it to the configured WhatsApp number."""
        if not isinstance(order_data, dict):
            raise AgentError("Order data must be a JSON object.")
        order = order_data.get("order") if isinstance(order_data.get("order"), dict) else order_data
        order_name = str(order.get("name") or order.get("order_number") or order.get("id") or "Shopify order")[:80]
        total = order.get("total_price")
        if total is None:
            total_set = order.get("totalPriceSet") or {}
            total = ((total_set.get("shopMoney") or {}).get("amount"))
        currency = str(order.get("currency") or ((order.get("totalPriceSet") or {}).get("shopMoney") or {}).get("currencyCode") or "")[:8]
        line_items = order.get("line_items") or (order.get("lineItems") or {}).get("nodes") or []
        item_count = len(line_items) if isinstance(line_items, list) else 0
        report = f"New order {order_name}\nTotal: {total if total is not None else 'not provided'} {currency}\nItems: {item_count}"

        recipient = re.sub(r"[^0-9]", "", self.settings.get_secret("whatsapp_number"))
        phone_number_id = self.config.whatsapp_phone_number_id.strip()
        access_token = self.settings.get_secret("whatsapp_cloud_api_token")
        if not recipient or not phone_number_id or not access_token:
            raise AgentError("Save WhatsApp destination, sender Phone Number ID, and Cloud API token in Settings first.")
        if not re.fullmatch(r"\d{8,15}", recipient):
            raise AgentError("WhatsApp destination must be an international number with 8–15 digits.")
        version = self.config.whatsapp_graph_api_version.strip()
        if not re.fullmatch(r"v\d+\.\d+", version):
            raise AgentError("WhatsApp Graph API version must look like v23.0.")
        url = f"https://graph.facebook.com/{version}/{quote(phone_number_id, safe='')}/messages"
        template_name = self.config.whatsapp_template_name.strip()
        if template_name:
            # Configure an approved Meta template with three body placeholders:
            # order name, total (including currency), and item count.
            payload = {
                "messaging_product": "whatsapp", "to": recipient, "type": "template",
                "template": {
                    "name": template_name,
                    "language": {"code": self.config.whatsapp_template_language.strip() or "en_US"},
                    "components": [{"type": "body", "parameters": [
                        {"type": "text", "text": order_name},
                        {"type": "text", "text": f"{total if total is not None else 'not provided'} {currency}".strip()},
                        {"type": "text", "text": str(item_count)},
                    ]}],
                },
            }
        else:
            payload = {"messaging_product": "whatsapp", "to": recipient, "type": "text",
                       "text": {"preview_url": False, "body": report}}
        try:
            response = requests.post(
                url, json=payload,
                headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
                timeout=(10, 30),
            )
        except requests.RequestException as exc:
            raise AgentError(f"Could not reach WhatsApp Cloud API: {exc}") from exc
        if not response.ok:
            raise AgentError(f"WhatsApp Cloud API returned HTTP {response.status_code}; check credentials and message eligibility.")
        result = response.json()
        return {"status": "WhatsApp report sent", "order": order_name,
                "message_id": ((result.get("messages") or [{}])[0]).get("id", "")}

