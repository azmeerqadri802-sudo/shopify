#!/usr/bin/env python3
"""Generate the Shopify AI Store Manager project and optionally push it to GitHub.

The script itself uses only Python's standard library. Run it from a workspace
directory, then enter a GitHub URL (the supplied repository is the default):

    python build_and_push.py

By default the project is generated into ./shopify-ai-store-manager. The script
commits and pushes to the provided remote without a second prompt. No force push
is ever used. Use --no-push to generate the files without contacting Git.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterable


DEFAULT_REPO_URL = "https://github.com/azmeerqadri802-sudo/shopify.git"
DEFAULT_PROJECT_DIR = "shopify-ai-store-manager"
COMMIT_MESSAGE = "Initial AI Store Manager Commit"


PROJECT_FILES: dict[str, str] = {
    ".gitignore": r'''# Python
__pycache__/
*.py[cod]
*.pyd
.venv/
venv/
env/
.env
.pytest_cache/
.mypy_cache/

# PyInstaller build output
build/
dist/
*.spec

# Local state and editor files
.DS_Store
Thumbs.db
.idea/
.vscode/
''',
    "requirements.txt": r'''# Supported runtime: Python 3.11 or newer.
customtkinter>=5.2.2,<7
keyring>=25,<27
platformdirs>=4.3,<5
requests>=2.32,<3
langchain-core>=0.3.72,<2
langchain-google-genai>=4.0,<5
''',
    ".github/workflows/build-release.yml": r'''name: Build desktop apps and publish release

on:
  push:
    branches: [main]
  workflow_dispatch:

permissions:
  contents: write

concurrency:
  group: desktop-release-${{ github.ref }}
  cancel-in-progress: false

jobs:
  build:
    name: Build on ${{ matrix.os }}
    runs-on: ${{ matrix.os }}
    strategy:
      fail-fast: false
      matrix:
        os: [windows-latest, macos-latest]
    steps:
      - name: Check out source
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip

      - name: Install dependencies
        run: python -m pip install --upgrade pip && python -m pip install -r requirements.txt pyinstaller

      - name: Build Windows executable
        if: runner.os == 'Windows'
        run: >-
          python -m PyInstaller --noconfirm --clean --onefile --windowed
          --name ShopifyAIStoreManager --collect-all customtkinter
          --collect-submodules langchain_google_genai
          --collect-submodules langchain_core
          --collect-submodules keyring.backends app.py

      - name: Build macOS application bundle
        if: runner.os == 'macOS'
        run: >-
          python -m PyInstaller --noconfirm --clean --windowed
          --name ShopifyAIStoreManager --collect-all customtkinter
          --collect-submodules langchain_google_genai
          --collect-submodules langchain_core
          --collect-submodules keyring.backends app.py

      - name: Package macOS application
        if: runner.os == 'macOS'
        run: ditto -c -k --sequesterRsrc --keepParent dist/ShopifyAIStoreManager.app dist/ShopifyAIStoreManager-macOS.zip

      - name: Upload Windows executable
        if: runner.os == 'Windows'
        uses: actions/upload-artifact@v4
        with:
          name: desktop-windows
          path: dist/ShopifyAIStoreManager.exe
          if-no-files-found: error
          retention-days: 7

      - name: Upload macOS application
        if: runner.os == 'macOS'
        uses: actions/upload-artifact@v4
        with:
          name: desktop-macos
          path: dist/ShopifyAIStoreManager-macOS.zip
          if-no-files-found: error
          retention-days: 7

  release:
    name: Publish GitHub Release
    needs: build
    runs-on: ubuntu-latest
    steps:
      - name: Download platform builds
        uses: actions/download-artifact@v4
        with:
          pattern: desktop-*
          path: release-assets
          merge-multiple: true

      - name: Create a release for this main-branch build
        env:
          GH_TOKEN: ${{ github.token }}
          BUILD_TAG: build-${{ github.run_number }}-${{ github.run_attempt }}
        run: >-
          gh release create "$BUILD_TAG" release-assets/*
          --repo "$GITHUB_REPOSITORY"
          --target "$GITHUB_SHA"
          --title "Desktop build $GITHUB_RUN_NUMBER (attempt $GITHUB_RUN_ATTEMPT)"
          --notes "Automated Windows and macOS build from commit $GITHUB_SHA."
''',
    "README.md": r'''# Shopify AI Store Manager

A Windows/macOS desktop client built with CustomTkinter. It connects to Google Gemini, Shopify Admin GraphQL, SMTP, and the official Meta WhatsApp Business Cloud API. The executable bundles the UI and Python runtime; these cloud-connected features still require internet access and valid credentials.

## Generate and publish this project

Run the supplied `build_and_push.py` from a working directory. It creates `shopify-ai-store-manager/`, writes the source and GitHub Actions workflow, initializes `main`, commits the generated files, configures `origin`, and pushes to GitHub. The push happens automatically when you run the script; it never force-pushes. The default remote is the repository URL supplied with the setup request; pass a different URL at the prompt or as an argument.

The GitHub Actions workflow builds a Windows `.exe` and a zipped macOS `.app`, then publishes both in a GitHub Release after each push to `main` (or a manual workflow dispatch). GitHub Actions must be enabled and the workflow token must have permission to create releases.

## Local development

1. Install Python 3.11+ and Git.
2. Create and activate a virtual environment.
3. Install dependencies with `python -m pip install -r requirements.txt`.
4. Start the UI with `python app.py`.
5. Enter credentials in **Settings** and click **Save settings**.

The app stores non-secret preferences in the operating system's application settings directory. Gemini, Shopify, SMTP, and WhatsApp credentials, plus the destination WhatsApp number, are stored through Python Keyring (Windows Credential Manager or macOS Keychain). Sensitive values are never written to this repository or its JSON settings file. If the OS credential store is unavailable, saving credentials fails visibly rather than falling back to plaintext.

## Credentials and required access

- **Gemini:** create a Gemini API key and choose an available model in Settings. The model field defaults to `gemini-3.8-flash`; model availability and pricing are controlled by Google and can change.
- **Shopify:** enter the `https://your-store.myshopify.com` domain and an Admin API access token. Grant `write_products` to create draft products and `read_orders` to list recent orders. The app uses the versioned Admin GraphQL API; change its API version in Settings when Shopify advances the supported version.
- **SMTP:** supply an SMTP server, port, account, password, and sender address. The app uses TLS/STARTTLS and sends plain-text replies only after confirmation.
- **WhatsApp:** a recipient number alone is insufficient. Set up a Meta WhatsApp Business Cloud API sender, then provide its Phone Number ID, access token, and the destination number in Settings. Meta may require recipient opt-in and an approved template for messages outside an eligible service window. If you enter a template name, create an approved template with three body placeholders in this order: order name, total, item count. The Graph API version is configurable.

## Available agent tools

- `add_product(title, image_url, price)` asks Gemini for product copy, SEO fields, and tags, creates a Shopify **draft**, then sets its initial variant price. A non-empty image URL is attached as product media.
- `handle_marketing()` generates email/social copy and returns it in the dashboard; it does not publish or send the copy.
- `reply_to_email(customer_email, intent)` drafts a plain-text reply and sends it through SMTP after confirmation. The app does not read an inbox.
- `send_whatsapp_report(order_data)` formats an order payload into a short notification and sends it through WhatsApp Cloud API.

Shopify product creation and outbound email require an on-screen approval by default. This can be changed in Settings, but the confirmation is a useful guard against mistaken model tool calls.

## Orders and webhooks

The Dashboard can request the latest Shopify orders on demand. Shopify webhook delivery needs a publicly reachable HTTPS endpoint and HMAC verification. A desktop app behind a home/office firewall has no public ingress by itself, so this project does **not** claim to receive Shopify webhooks directly. The WhatsApp reporting function accepts webhook-shaped order data when called by a trusted, separately hosted webhook receiver or another integration. Do not expose an unverified webhook endpoint to the internet.

## Packaging notes

The Windows workflow produces `ShopifyAIStoreManager.exe`; the macOS workflow produces `ShopifyAIStoreManager-macOS.zip`. The macOS bundle is not code-signed or notarized. For broad macOS distribution, configure Apple signing/notarization credentials and add those steps to the workflow. API keys, Shopify tokens, SMTP passwords, and WhatsApp tokens must be entered separately on each installed machine.

This is an integration starter requiring store-specific configuration and operational review before unattended production use. Shopify scopes, Meta messaging policy, SMTP provider policy, model availability, data retention, and any legal requirements are the operator's responsibility.
''',
    "shopify_agent/__init__.py": r'''# Core services for the Shopify AI Store Manager.
''',
    "shopify_agent/config.py": r'''# Settings storage. Secrets stay in the operating system credential manager.

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import keyring
from platformdirs import user_config_path


APP_NAME = "ShopifyAIStoreManager"
SERVICE_NAME = "ShopifyAIStoreManager"
CONFIG_DIR = Path(user_config_path(APP_NAME, appauthor=False))
CONFIG_FILE = CONFIG_DIR / "settings.json"


@dataclass
class AppConfig:
    store_url: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_from_email: str = ""
    gemini_model: str = "gemini-3.8-flash"
    shopify_api_version: str = "2026-10"
    whatsapp_graph_api_version: str = "v23.0"
    whatsapp_phone_number_id: str = ""
    whatsapp_template_name: str = ""
    whatsapp_template_language: str = "en_US"
    require_confirmation: bool = True


SECRET_KEYS = (
    "gemini_api_key",
    "shopify_admin_api_token",
    "smtp_username",
    "smtp_password",
    "whatsapp_cloud_api_token",
    "whatsapp_number",
)


class SettingsStore:
    """Persist non-secret preferences as JSON and secrets through OS keyring."""

    def load(self) -> AppConfig:
        try:
            raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            allowed = AppConfig.__dataclass_fields__.keys()
            return AppConfig(**{key: value for key, value in raw.items() if key in allowed})
        except FileNotFoundError:
            return AppConfig()
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            # Keep a damaged preferences file from preventing the app from opening.
            return AppConfig()

    def save(self, config: AppConfig) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(asdict(config), indent=2, ensure_ascii=False)
        fd, temporary_name = tempfile.mkstemp(prefix="settings-", suffix=".tmp", dir=CONFIG_DIR)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, CONFIG_FILE)
        finally:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass

    def get_secret(self, key: str) -> str:
        self._validate_secret_key(key)
        return keyring.get_password(SERVICE_NAME, key) or ""

    def set_secret(self, key: str, value: str) -> None:
        self._validate_secret_key(key)
        if value:
            keyring.set_password(SERVICE_NAME, key, value)

    @staticmethod
    def _validate_secret_key(key: str) -> None:
        if key not in SECRET_KEYS:
            raise ValueError("Unknown secret name")

    def secret_is_configured(self, key: str) -> bool:
        return bool(self.get_secret(key))
''',
    "shopify_agent/shopify_client.py": r'''# Small Shopify Admin GraphQL client with bounded requests and validation.

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

import requests

from .config import AppConfig


class ShopifyError(RuntimeError):
    pass


@dataclass
class OrderSummary:
    name: str
    created_at: str
    customer: str
    total: str
    currency: str
    financial_status: str


class ShopifyClient:
    def __init__(self, config: AppConfig, access_token: str) -> None:
        if not access_token:
            raise ShopifyError("Save a Shopify Admin API token in Settings first.")
        parsed = urlparse(config.store_url.strip())
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not (host.endswith(".myshopify.com") or host == "myshopify.com"):
            raise ShopifyError("Use a Shopify store URL like https://your-store.myshopify.com.")
        if parsed.username or parsed.password or parsed.port:
            raise ShopifyError("The Shopify store URL must not contain credentials or a custom port.")
        version = config.shopify_api_version.strip()
        if not version or any(ch not in "0123456789-" for ch in version):
            raise ShopifyError("Shopify API version must look like 2026-10.")
        self.url = f"https://{host}/admin/api/{version}/graphql.json"
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Shopify-Access-Token": access_token,
            "User-Agent": "ShopifyAIStoreManager/1.0",
        })

    def graphql(self, query: str, variables: dict | None = None) -> dict:
        try:
            response = self.session.post(
                self.url, json={"query": query, "variables": variables or {}}, timeout=(10, 45)
            )
        except requests.RequestException as exc:
            raise ShopifyError(f"Could not reach Shopify: {exc}") from exc
        if not response.ok:
            # Avoid echoing full response bodies, which may contain customer data.
            raise ShopifyError(f"Shopify returned HTTP {response.status_code}.")
        try:
            payload = response.json()
        except ValueError as exc:
            raise ShopifyError("Shopify returned an invalid JSON response.") from exc
        if payload.get("errors"):
            messages = "; ".join(str(error.get("message", "GraphQL error")) for error in payload["errors"])
            raise ShopifyError(messages[:800])
        return payload.get("data") or {}

    def recent_orders(self, limit: int = 12) -> list[OrderSummary]:
        query = """
        query RecentOrders($first: Int!) {
          orders(first: $first, sortKey: CREATED_AT, reverse: true) {
            nodes {
              name createdAt displayFinancialStatus
              totalPriceSet { shopMoney { amount currencyCode } }
              customer { displayName }
            }
          }
        }
        """
        data = self.graphql(query, {"first": max(1, min(limit, 50))})
        result: list[OrderSummary] = []
        for order in data.get("orders", {}).get("nodes", []):
            money = order.get("totalPriceSet", {}).get("shopMoney", {})
            result.append(OrderSummary(
                name=order.get("name") or "Order",
                created_at=order.get("createdAt") or "",
                customer=(order.get("customer") or {}).get("displayName") or "Guest",
                total=money.get("amount") or "0.00",
                currency=money.get("currencyCode") or "",
                financial_status=order.get("displayFinancialStatus") or "UNKNOWN",
            ))
        return result

    def create_draft_product(
        self, *, title: str, price: float, description_html: str,
        seo_title: str, seo_description: str, tags: list[str], image_url: str = ""
    ) -> dict:
        try:
            decimal_price = Decimal(str(price)).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError) as exc:
            raise ShopifyError("Price must be a valid positive amount.") from exc
        if not decimal_price.is_finite() or decimal_price <= 0 or decimal_price > Decimal("100000000"):
            raise ShopifyError("Price must be greater than zero and within Shopify's supported range.")
        title = title.strip()
        if not title or len(title) > 255:
            raise ShopifyError("Product title must contain 1–255 characters.")

        media = []
        if image_url.strip():
            parsed = urlparse(image_url.strip())
            if parsed.scheme != "https" or not parsed.netloc:
                raise ShopifyError("Image URL must be a public HTTPS URL.")
            media = [{
                "originalSource": image_url.strip(),
                "mediaContentType": "IMAGE",
                "alt": title[:255],
            }]

        create_mutation = """
        mutation CreateDraftProduct($product: ProductCreateInput!, $media: [CreateMediaInput!]) {
          productCreate(product: $product, media: $media) {
            product {
              id title
              variants(first: 1) { nodes { id } }
            }
            userErrors { field message }
          }
        }
        """
        product = {
            "title": title,
            "descriptionHtml": description_html,
            "status": "DRAFT",
            "seo": {"title": seo_title[:70], "description": seo_description[:320]},
            "tags": tags[:20],
        }
        result = self.graphql(create_mutation, {"product": product, "media": media})
        created = result.get("productCreate") or {}
        errors = created.get("userErrors") or []
        if errors:
            raise ShopifyError("; ".join(item.get("message", "Product creation failed") for item in errors)[:800])
        shopify_product = created.get("product") or {}
        variants = (shopify_product.get("variants") or {}).get("nodes") or []
        if not variants:
            raise ShopifyError("Shopify created the product but returned no initial variant; price was not set.")

        price_mutation = """
        mutation SetInitialVariantPrice($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
          productVariantsBulkUpdate(productId: $productId, variants: $variants) {
            productVariants { id price }
            userErrors { field message }
          }
        }
        """
        priced = self.graphql(price_mutation, {
            "productId": shopify_product["id"],
            "variants": [{"id": variants[0]["id"], "price": str(decimal_price)}],
        }).get("productVariantsBulkUpdate") or {}
        price_errors = priced.get("userErrors") or []
        if price_errors:
            raise ShopifyError(
                "Product draft was created, but Shopify could not set its price: "
                + "; ".join(item.get("message", "Price update failed") for item in price_errors)[:600]
            )
        return {"id": shopify_product.get("id", ""), "title": shopify_product.get("title", title), "price": str(decimal_price)}
''',
    "shopify_agent/ai_agent.py": r'''# Gemini-backed LangChain tool agent and outbound integrations.

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
''',
    "app.py": r'''# CustomTkinter desktop shell for Shopify AI Store Manager.

from __future__ import annotations

import queue
from concurrent.futures import Future, ThreadPoolExecutor
from tkinter import messagebox
from typing import Callable

import customtkinter as ctk

from shopify_agent.ai_agent import StoreAgent
from shopify_agent.config import AppConfig, SettingsStore
from shopify_agent.shopify_client import ShopifyClient


BG = "#10131a"
PANEL = "#191e29"
ACCENT = "#7c5cff"
MUTED = "#9aa4b2"
TEXT = "#f2f4f8"


class StoreManagerApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        ctk.set_appearance_mode("dark")
        self.title("Shopify AI Store Manager")
        self.geometry("1240x820")
        self.minsize(980, 680)
        self.configure(fg_color=BG)
        self.settings = SettingsStore()
        self.config = self.settings.load()
        self.executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="store-agent")
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self._closing = False
        self._config_widgets: dict[str, ctk.CTkEntry] = {}
        self._secret_widgets: dict[str, ctk.CTkEntry] = {}
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._drain_events)

    def _build_ui(self) -> None:
        header = ctk.CTkFrame(self, fg_color=BG)
        header.pack(fill="x", padx=28, pady=(22, 8))
        ctk.CTkLabel(header, text="STORE MANAGER", text_color=ACCENT,
                     font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(header, text="Your Shopify operations, in one place",
                     text_color=TEXT, font=ctk.CTkFont(size=26, weight="bold")).pack(anchor="w", pady=(4, 0))
        ctk.CTkLabel(header, text="Gemini assistant  •  Shopify Admin  •  Local credential vault",
                     text_color=MUTED, font=ctk.CTkFont(size=13)).pack(anchor="w", pady=(5, 4))

        self.tabs = ctk.CTkTabview(self, fg_color=BG, segmented_button_selected_color=ACCENT,
                                  segmented_button_selected_hover_color="#6646e8")
        self.tabs.pack(fill="both", expand=True, padx=24, pady=(8, 22))
        self.dashboard = self.tabs.add("Dashboard")
        self.settings_tab = self.tabs.add("Settings")
        self._build_dashboard()
        self._build_settings()

    def _build_dashboard(self) -> None:
        self.dashboard.grid_columnconfigure(0, weight=3)
        self.dashboard.grid_columnconfigure(1, weight=2)
        self.dashboard.grid_rowconfigure(0, weight=1)
        left = ctk.CTkFrame(self.dashboard, fg_color=PANEL, corner_radius=16)
        right = ctk.CTkFrame(self.dashboard, fg_color=PANEL, corner_radius=16)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10), pady=8)
        right.grid(row=0, column=1, sticky="nsew", padx=(10, 0), pady=8)
        left.grid_rowconfigure(1, weight=1)
        left.grid_columnconfigure(0, weight=1)
        title_row = ctk.CTkFrame(left, fg_color="transparent")
        title_row.grid(row=0, column=0, sticky="ew", padx=18, pady=(17, 8))
        ctk.CTkLabel(title_row, text="Activity", text_color=TEXT,
                     font=ctk.CTkFont(size=17, weight="bold")).pack(side="left")
        self.activity = ctk.CTkTextbox(left, fg_color="#11151d", text_color="#d2d9e3",
                                       corner_radius=12, wrap="word", font=ctk.CTkFont(size=12))
        self.activity.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 14))
        self.activity.configure(state="disabled")
        command_frame = ctk.CTkFrame(left, fg_color="transparent")
        command_frame.grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 18))
        command_frame.grid_columnconfigure(0, weight=1)
        self.command_entry = ctk.CTkEntry(command_frame, placeholder_text="Ask the agent to help manage your store…",
                                          height=42, fg_color="#11151d", border_color="#303848")
        self.command_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.command_entry.bind("<Return>", lambda _event: self._send_command())
        self.send_button = ctk.CTkButton(command_frame, text="Run", width=90, height=42,
                                         fg_color=ACCENT, command=self._send_command)
        self.send_button.grid(row=0, column=1)

        right.grid_rowconfigure(1, weight=1)
        right.grid_columnconfigure(0, weight=1)
        order_header = ctk.CTkFrame(right, fg_color="transparent")
        order_header.grid(row=0, column=0, sticky="ew", padx=16, pady=(17, 9))
        ctk.CTkLabel(order_header, text="Recent orders", text_color=TEXT,
                     font=ctk.CTkFont(size=17, weight="bold")).pack(side="left")
        ctk.CTkButton(order_header, text="Refresh", width=78, height=30, fg_color="#293143",
                      hover_color="#35415a", command=self._refresh_orders).pack(side="right")
        self.orders_list = ctk.CTkScrollableFrame(right, fg_color="transparent")
        self.orders_list.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        self._render_orders([])
        self._log("Ready. Save your API credentials in Settings to begin.")

    def _render_orders(self, orders: list) -> None:
        for child in self.orders_list.winfo_children():
            child.destroy()
        if not orders:
            ctk.CTkLabel(self.orders_list, text="No orders loaded yet.\nChoose Refresh to fetch recent orders.",
                         text_color=MUTED, justify="left").pack(anchor="w", padx=8, pady=12)
            return
        for order in orders:
            card = ctk.CTkFrame(self.orders_list, fg_color="#202634", corner_radius=11)
            card.pack(fill="x", padx=3, pady=5)
            ctk.CTkLabel(card, text=order.name, text_color=TEXT,
                         font=ctk.CTkFont(size=13, weight="bold")).pack(anchor="w", padx=12, pady=(9, 0))
            ctk.CTkLabel(card, text=f"{order.customer}   ·   {order.total} {order.currency}",
                         text_color="#c2cad5", font=ctk.CTkFont(size=12)).pack(anchor="w", padx=12, pady=(4, 0))
            ctk.CTkLabel(card, text=f"{order.created_at[:16].replace('T', ' ')}   ·   {order.financial_status}",
                         text_color=MUTED, font=ctk.CTkFont(size=11)).pack(anchor="w", padx=12, pady=(3, 9))

    def _build_settings(self) -> None:
        self.settings_tab.grid_columnconfigure(0, weight=1)
        self.settings_tab.grid_columnconfigure(1, weight=1)
        self.settings_tab.grid_rowconfigure(0, weight=1)
        left = ctk.CTkScrollableFrame(self.settings_tab, fg_color=PANEL, corner_radius=16)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 9), pady=8)
        right = ctk.CTkScrollableFrame(self.settings_tab, fg_color=PANEL, corner_radius=16)
        right.grid(row=0, column=1, sticky="nsew", padx=(9, 0), pady=8)
        ctk.CTkLabel(left, text="Store and AI", text_color=TEXT,
                     font=ctk.CTkFont(size=17, weight="bold")).pack(anchor="w", padx=18, pady=(18, 12))
        self._add_field(left, "Gemini API key", "gemini_api_key", secret=True)
        self._add_field(left, "Gemini model", "gemini_model", value=self.config.gemini_model)
        self._add_field(left, "Shopify store URL", "store_url", value=self.config.store_url,
                        placeholder="https://your-store.myshopify.com")
        self._add_field(left, "Shopify Admin API token", "shopify_admin_api_token", secret=True)
        self._add_field(left, "Shopify API version", "shopify_api_version", value=self.config.shopify_api_version)
        self._add_field(left, "WhatsApp destination number", "whatsapp_number", secret=True,
                        placeholder="International format, e.g. +15551234567")
        self._add_field(left, "WhatsApp sender Phone Number ID", "whatsapp_phone_number_id",
                        value=self.config.whatsapp_phone_number_id)
        self._add_field(left, "WhatsApp Cloud API token", "whatsapp_cloud_api_token", secret=True)
        self._add_field(left, "WhatsApp Graph API version", "whatsapp_graph_api_version",
                        value=self.config.whatsapp_graph_api_version)
        self._add_field(left, "Optional approved message template", "whatsapp_template_name",
                        value=self.config.whatsapp_template_name)
        self._add_field(left, "Template language", "whatsapp_template_language",
                        value=self.config.whatsapp_template_language)

        ctk.CTkLabel(right, text="Email and safeguards", text_color=TEXT,
                     font=ctk.CTkFont(size=17, weight="bold")).pack(anchor="w", padx=18, pady=(18, 12))
        self._add_field(right, "SMTP server", "smtp_host", value=self.config.smtp_host)
        self._add_field(right, "SMTP port", "smtp_port", value=str(self.config.smtp_port))
        self._add_field(right, "SMTP username", "smtp_username", secret=True)
        self._add_field(right, "SMTP password", "smtp_password", secret=True)
        self._add_field(right, "From email address", "smtp_from_email", value=self.config.smtp_from_email)
        self.confirm_switch = ctk.CTkSwitch(
            right, text="Confirm product creation and outbound email",
            progress_color=ACCENT, text_color=TEXT,
        )
        self.confirm_switch.pack(anchor="w", padx=18, pady=(20, 6))
        if self.config.require_confirmation:
            self.confirm_switch.select()
        ctk.CTkLabel(right, text="Credentials are stored in the OS credential manager. Leave a secret field blank to keep its saved value.",
                     text_color=MUTED, wraplength=420, justify="left").pack(anchor="w", padx=18, pady=(4, 12))
        ctk.CTkButton(right, text="Save settings", height=42, fg_color=ACCENT,
                      command=self._save_settings).pack(fill="x", padx=18, pady=(6, 18))

    def _add_field(self, parent, label: str, key: str, *, value: str = "", secret: bool = False,
                   placeholder: str = "") -> None:
        group = ctk.CTkFrame(parent, fg_color="transparent")
        group.pack(fill="x", padx=18, pady=5)
        ctk.CTkLabel(group, text=label, text_color="#c7cfda",
                     font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", pady=(0, 4))
        entry = ctk.CTkEntry(group, height=36, fg_color="#11151d", border_color="#303848",
                             placeholder_text=placeholder or ("Saved securely · leave blank to keep" if secret else ""),
                             show="•" if secret else "")
        if value:
            entry.insert(0, str(value))
        entry.pack(fill="x")
        if secret:
            self._secret_widgets[key] = entry
        else:
            self._config_widgets[key] = entry

    def _save_settings(self) -> None:
        try:
            port_text = self._config_widgets["smtp_port"].get().strip() or "587"
            port = int(port_text)
            if not 1 <= port <= 65535:
                raise ValueError("SMTP port must be between 1 and 65535.")
            config = AppConfig(
                store_url=self._config_widgets["store_url"].get().strip(),
                smtp_host=self._config_widgets["smtp_host"].get().strip(),
                smtp_port=port,
                smtp_from_email=self._config_widgets["smtp_from_email"].get().strip(),
                gemini_model=self._config_widgets["gemini_model"].get().strip() or "gemini-3.8-flash",
                shopify_api_version=self._config_widgets["shopify_api_version"].get().strip() or "2026-10",
                whatsapp_graph_api_version=self._config_widgets["whatsapp_graph_api_version"].get().strip() or "v23.0",
                whatsapp_phone_number_id=self._config_widgets["whatsapp_phone_number_id"].get().strip(),
                whatsapp_template_name=self._config_widgets["whatsapp_template_name"].get().strip(),
                whatsapp_template_language=self._config_widgets["whatsapp_template_language"].get().strip() or "en_US",
                require_confirmation=bool(self.confirm_switch.get()),
            )
            self.settings.save(config)
            for key, entry in self._secret_widgets.items():
                secret_value = entry.get()
                if secret_value:
                    self.settings.set_secret(key, secret_value)
                    entry.delete(0, "end")
            self.config = config
            self._log("Settings saved. Secret values were written to the OS credential manager.")
            messagebox.showinfo("Settings saved", "Settings and credentials were saved securely.")
        except Exception as exc:
            messagebox.showerror("Could not save settings", str(exc))

    def _send_command(self) -> None:
        command = self.command_entry.get().strip()
        if not command:
            return
        self.command_entry.delete(0, "end")
        self._log(f"You: {command}")
        self.send_button.configure(state="disabled", text="Working…")
        self._submit("agent", lambda: self._run_agent(command))

    def _run_agent(self, command: str) -> str:
        config = self.settings.load()
        agent = StoreAgent(config, self.settings, self._ask_approval,
                           log_callback=lambda text: self.events.put(("log", text)))
        return agent.run(command)

    def _refresh_orders(self) -> None:
        self._log("Loading recent Shopify orders…")
        self._submit("orders", self._load_orders)

    def _load_orders(self) -> list:
        config = self.settings.load()
        token = self.settings.get_secret("shopify_admin_api_token")
        return ShopifyClient(config, token).recent_orders()

    def _ask_approval(self, description: str) -> bool:
        """Ask from the Tk thread while a worker waits for the user's decision."""
        future: Future = Future()
        def show_prompt() -> None:
            if self._closing:
                future.set_result(False)
                return
            future.set_result(messagebox.askyesno("Confirm store action", description, parent=self))
        self.after(0, show_prompt)
        try:
            return bool(future.result(timeout=300))
        except Exception:
            return False

    def _submit(self, event_name: str, task: Callable):
        future = self.executor.submit(task)
        def completed(done_future: Future) -> None:
            try:
                result = done_future.result()
                self.events.put((event_name, result))
            except Exception as exc:
                self.events.put(("error", str(exc)))
        future.add_done_callback(completed)

    def _drain_events(self) -> None:
        try:
            while True:
                name, value = self.events.get_nowait()
                if name == "log":
                    self._log(str(value))
                elif name == "agent":
                    self._log(f"Assistant: {value}")
                    self.send_button.configure(state="normal", text="Run")
                elif name == "orders":
                    self._render_orders(value)
                    self._log(f"Loaded {len(value)} recent order(s).")
                elif name == "error":
                    self._log(f"Error: {value}")
                    self.send_button.configure(state="normal", text="Run")
                    messagebox.showerror("Operation failed", str(value))
        except queue.Empty:
            pass
        if not self._closing:
            self.after(120, self._drain_events)

    def _log(self, text: str) -> None:
        if not hasattr(self, "activity"):
            return
        self.activity.configure(state="normal")
        self.activity.insert("end", f"{text}\n")
        self.activity.see("end")
        self.activity.configure(state="disabled")

    def _on_close(self) -> None:
        self._closing = True
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.destroy()


if __name__ == "__main__":
    StoreManagerApp().mainloop()
''',
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate and push the Shopify AI Store Manager project.")
    parser.add_argument("repo_url", nargs="?", help="GitHub HTTPS or SSH repository URL")
    parser.add_argument("--output-dir", type=Path, default=Path.cwd() / DEFAULT_PROJECT_DIR,
                        help=f"Project output directory (default: ./{DEFAULT_PROJECT_DIR})")
    parser.add_argument("--no-push", action="store_true", help="Generate the project without running Git push")
    parser.add_argument("--force-overwrite", action="store_true",
                        help="Overwrite generated project files that already exist")
    return parser.parse_args(argv)


def choose_repo_url(argument: str | None) -> str:
    candidate = (argument or "").strip()
    if not candidate:
        entered = input(f"GitHub repository URL [{DEFAULT_REPO_URL}]: ").strip()
        candidate = entered or DEFAULT_REPO_URL
    if not (candidate.startswith("https://") or candidate.startswith("ssh://") or candidate.startswith("git@")):
        raise ValueError("Use a GitHub HTTPS URL (https://...) or SSH URL (git@github.com:owner/repo.git).")
    if "\n" in candidate or "\r" in candidate:
        raise ValueError("Repository URL must be a single line.")
    return candidate


def safe_write(path: Path, content: str, overwrite: bool) -> None:
    if path.exists():
        try:
            if path.read_text(encoding="utf-8") == content:
                return
        except (OSError, UnicodeDecodeError):
            pass
        if not overwrite:
            raise FileExistsError(f"Refusing to overwrite existing file: {path}. Use --force-overwrite after reviewing it.")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass


def generate_project(project_dir: Path, overwrite: bool) -> None:
    project_dir.mkdir(parents=True, exist_ok=True)
    # Never let `git add .` accidentally include arbitrary files in the output folder.
    expected_files = set(PROJECT_FILES) | {"build_and_push.py"}
    expected_paths = set(expected_files)
    for name in expected_files:
        parent = Path(name).parent
        while parent != Path("."):
            expected_paths.add(parent.as_posix())
            parent = parent.parent
    unexpected = []
    for item in project_dir.rglob("*"):
        if ".git" in item.relative_to(project_dir).parts:
            continue
        relative = item.relative_to(project_dir).as_posix()
        if relative not in expected_paths:
            unexpected.append(relative)
    if unexpected:
        joined = ", ".join(sorted(unexpected)[:8])
        raise RuntimeError(f"Output directory contains unmanaged files ({joined}). Choose a clean directory so they are not pushed.")

    for relative, content in PROJECT_FILES.items():
        safe_write(project_dir / relative, content, overwrite=overwrite)

    builder = Path(__file__).resolve()
    destination = project_dir / "build_and_push.py"
    if builder != destination.resolve():
        safe_write(destination, builder.read_text(encoding="utf-8"), overwrite=overwrite)


def run(command: Iterable[str], cwd: Path | None = None, *, capture: bool = False) -> subprocess.CompletedProcess:
    command = list(command)
    print("$ " + " ".join(command))
    try:
        result = subprocess.run(
            command, cwd=cwd, check=True, text=True,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.STDOUT if capture else None,
        )
        if capture and result.stdout:
            print(result.stdout.rstrip())
        return result
    except FileNotFoundError as exc:
        raise RuntimeError(f"Required command not found: {command[0]}. Install Git and ensure it is on PATH.") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stdout or "").strip()
        raise RuntimeError(f"Command failed with exit code {exc.returncode}: {' '.join(command)}\n{detail}") from exc


def ensure_git_identity(project_dir: Path) -> None:
    """Prompt for repo-local author details only when Git has no identity configured."""
    identity = subprocess.run(
        ["git", "var", "GIT_AUTHOR_IDENT"], cwd=project_dir,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    if identity.returncode == 0:
        return
    print("Git needs a commit author identity. These values are saved only in this repository.")
    name = input("Commit author name: ").strip()
    email = input("Commit author email: ").strip()
    if not name or "\n" in name or not email or "\n" in email or "@" not in email:
        raise RuntimeError("A valid Git author name and email are required to commit.")
    run(["git", "config", "user.name", name], cwd=project_dir)
    run(["git", "config", "user.email", email], cwd=project_dir)


def git_push(project_dir: Path, repo_url: str) -> None:
    if not (project_dir / ".git").exists():
        run(["git", "init"], cwd=project_dir)
        run(["git", "symbolic-ref", "HEAD", "refs/heads/main"], cwd=project_dir)
    else:
        has_head = subprocess.run(["git", "rev-parse", "--verify", "HEAD"], cwd=project_dir,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
        if has_head:
            run(["git", "branch", "-M", "main"], cwd=project_dir)
        else:
            run(["git", "symbolic-ref", "HEAD", "refs/heads/main"], cwd=project_dir)

    tracked = run(["git", "ls-files", "-z"], cwd=project_dir, capture=True)
    tracked_names = {name for name in tracked.stdout.split("\0") if name}
    if not tracked_names.issubset(set(PROJECT_FILES) | {"build_and_push.py"}):
        raise RuntimeError("Git already tracks files outside this generated project; refusing to alter that repository.")
    status = run(["git", "status", "--porcelain"], cwd=project_dir, capture=True)
    if status.stdout and any(line and line[:2] == "??" for line in status.stdout.splitlines()):
        # The only allowed untracked files are those this generator manages.
        names = {line[3:].replace("\\", "/").rstrip("/") for line in status.stdout.splitlines() if line.startswith("?? ")}
        allowed = set(PROJECT_FILES) | {"build_and_push.py"}
        for name in tuple(allowed):
            parent = Path(name).parent
            while parent != Path("."):
                allowed.add(parent.as_posix())
                parent = parent.parent
        if not names.issubset(allowed):
            raise RuntimeError("Git contains untracked files outside this generated project; refusing to include them.")

    run(["git", "add", "."], cwd=project_dir)
    diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=project_dir)
    if diff.returncode == 1:
        ensure_git_identity(project_dir)
        # Keep the requested initial commit message when the repository has no history.
        has_head = subprocess.run(["git", "rev-parse", "--verify", "HEAD"], cwd=project_dir,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
        message = "Update AI Store Manager project" if has_head else COMMIT_MESSAGE
        run(["git", "commit", "-m", message], cwd=project_dir)
    elif diff.returncode != 0:
        raise RuntimeError("Git could not inspect the staged changes.")
    else:
        print("No staged changes; keeping the existing commit.")

    remotes = run(["git", "remote"], cwd=project_dir, capture=True).stdout.split()
    if "origin" in remotes:
        run(["git", "remote", "set-url", "origin", repo_url], cwd=project_dir)
    else:
        run(["git", "remote", "add", "origin", repo_url], cwd=project_dir)

    print(f"\nPushing branch 'main' to {repo_url}")
    run(["git", "push", "-u", "origin", "main"], cwd=project_dir)
    print("Push completed. GitHub Actions will build the Windows and macOS releases.")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        repo_url = choose_repo_url(args.repo_url) if not args.no_push else ""
        project_dir = args.output_dir.expanduser().resolve()
        generate_project(project_dir, overwrite=args.force_overwrite)
        print(f"Project generated at: {project_dir}")
        if args.no_push:
            print("Git operations skipped (--no-push).")
            return 0
        git_push(project_dir, repo_url)
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nCancelled. Generated files are preserved.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

