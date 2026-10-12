# Shopify AI Store Manager

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

