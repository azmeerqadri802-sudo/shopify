# Shopify AI Manager V2.0

An enterprise-style PyQt6 desktop cockpit for Shopify store operations: a frameless Windows 11 Mica/Acrylic window, animated AI status orb, interactive sales and inventory charts, microphone command entry, and a Gemini tool-calling agent.

This is a desktop client, not an unattended web service. Shopify, Gemini, search, SMTP, voice transcription and WhatsApp features need network access and valid third-party credentials.

## Local run and upgrade

1. Install Python 3.12 and Git.
2. Create a virtual environment and install dependencies with python -m pip install -r requirements.txt.
3. Start the UI with python app.py.
4. Configure credentials in Settings.

The master upgrade_to_v2.py script expects an existing clean Git checkout. It replaces the V1 source, writes the PyQt6 project, creates the V2 commit and v2.0.0 tag, then runs git push origin main --tags. It refuses to overwrite uncommitted work.

## GitHub release

Pushing a tag beginning with v builds the Windows no-console one-file executable with PyInstaller and publishes it as an asset on that GitHub Release. A published-release trigger is also supported for a pre-created release. GitHub Actions must be enabled and the workflow token must have contents: write permission.

## Gemini and agent tools

Gemini 1.5 Pro is no longer listed in Google's current Gemini API model catalog. The default model is gemini-3.8-flash and can be changed in Settings to another model supported by the configured Google key. LangChain's Google integration provides function calling with a bounded tool loop.

- add_product(title, image_url, price): drafts SEO copy and creates a Shopify draft product with its initial price after approval.
- handle_marketing(): creates email/social copy and returns it without publishing.
- reply_to_email(customer_email, intent): drafts and sends a plain-text support reply after approval.
- send_whatsapp_report(order_data): formats webhook-shaped order JSON and sends via Meta WhatsApp Cloud API after approval.
- analyze_market_price(product_name): searches current public results through Tavily and produces an advisory range with URLs. Configure a Tavily API key.
- predict_inventory(): estimates variant stock-out timing using sellable inventory and trailing 90-day order quantities.
- analyze_sales(days): summarizes daily revenue and today's sales for the selected window.

## Credentials and access

Gemini, Shopify, SMTP, WhatsApp and Tavily secrets are stored via Python Keyring in Windows Credential Manager or macOS Keychain. Non-secret preferences go in the user's application config folder. If the OS vault is unavailable, the app reports an error and does not write secrets in plaintext.

Shopify scopes include read_orders, read_products, and write_products. Grant the minimum scopes that support your enabled features; inventory access may require an additional inventory read scope in your store. The API version defaults to 2026-10 and is editable in Settings.

WhatsApp requires a Meta Business Cloud API sender, sender Phone Number ID, access token, recipient number, and recipient opt-in. Meta may require an approved message template. Email needs SMTP credentials. Competitor search needs a Tavily API key.

Voice commands record one utterance and send it to Google's speech-recognition endpoint for transcription. Speech transcription needs a microphone, OS permission and an internet connection.

## Analytics limits

The sales chart displays up to 30 daily points from a trailing 90-day Shopify history query. Inventory uses current sellable quantities divided by average variant units sold per day. Results are estimates affected by seasonality, promotions, stock adjustments and incomplete history. Variants without tracked inventory or recent sales do not have a stock-out estimate.

Shopify webhooks require a public HTTPS receiver and HMAC validation. This desktop application does not expose an inbound webhook endpoint; only a trusted integration should forward verified order data to the WhatsApp report tool.

Windows applies native Mica where supported and falls back to Acrylic or the Qt dark surface. macOS keeps the premium dark UI and does not claim to have Windows blur. The executable is not code-signed; sign it before broad distribution.

## Safeguards

Product creation, email and WhatsApp sends require desktop approval by default. Disabling approval in Settings allows those actions without a confirmation dialog. Activity logs stay in memory for the current session. Review provider retention and privacy terms before using customer data.

