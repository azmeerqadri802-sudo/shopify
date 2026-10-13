# OmniStore AI Manager V3.0

A PyQt6 desktop cockpit for omnichannel digital-accessory operations. The single-screen dashboard combines AI activity, recent orders, a voice-command button, product-file drop zone, text commands, and a compact order chart. Marketplace logic, Gemini tools, persistence, and the UI are separated into the `omnistore` package.

## Run locally

1. Use Python 3.12 and a clean checkout of this repository's `main` branch.
2. Create and activate a virtual environment.
3. Install dependencies: `python -m pip install -r requirements.txt`.
4. Start the desktop app: `python app.py`.
5. Open **Settings** and configure Gemini and the marketplaces you use.

Credentials and order payloads are encrypted in the local SQLite database. The Fernet key is stored in Windows Credential Manager or macOS Keychain. The application refuses to save credentials if an OS keychain backend is unavailable. No credentials are committed to Git.

## Supabase cloud sync

The optional **Supabase Cloud** Settings tab uses the pinned `supabase==2.32.0` Python SDK. Before enabling it, run [`supabase/setup.sql`](supabase/setup.sql) once in the project's Supabase SQL Editor, enable the `public` schema in the Data API if the project has restricted exposed schemas, and create/confirm a Supabase Auth email/password user. Enter the project URL, publishable (or legacy anon) key, and that user's email/password in Settings. The password and key remain in the encrypted local database. Secret/service-role keys are rejected.

Cloud sync sends only fixed activity summaries and daily order-count/sales aggregates; raw orders, customer details, prompts, file paths, and marketplace credentials stay local. All cloud reads/writes run on a dedicated `QThread`. The included SQL enables RLS and grants authenticated users only the minimum select/insert/update permissions needed for their own rows. The dashboard reads back the signed-in user's activity and sales data. The session signs out when the worker shuts down.

## AI and voice

Gemini uses the Google GenAI SDK with a bounded tool-calling loop for product creation, all-connected-store listings, bulk file ingestion, store-aware marketing, and customer support drafts. The default model is `gemini-3.8-flash`; Settings accepts another model ID supported by the configured API key. Gemini 1.5 Pro is no longer available in the current model catalog; consult [Google's model catalog](https://ai.google.dev/gemini-api/docs/models) and [deprecation schedule](https://ai.google.dev/gemini-api/docs/deprecations) before changing model IDs.

SpeechRecognition captures one utterance and uses Google's recognition service to transcribe it before sending it to Gemini. Microphone permissions, an input device, and internet access are required.

## Omnichannel capabilities

- Shopify Admin REST: draft product creation, order reads, and inventory-level updates.
- WooCommerce REST: draft product creation, order reads, and stock updates.
- Amazon SP-API: LWA token refresh, optional STS role assumption, SigV4 requests, listing calls, and order polling. Marketplace schemas and seller permissions apply.
- eBay Sell APIs: inventory item and offer publishing, order reads, and quantity changes. OAuth token and listing policies are required.
- TikTok Shop and Daraz: adapter contracts and credential forms are included as scaffolds. Regional signing/OAuth and category mappings remain incomplete, so these channels are deliberately not enabled for live writes.
- Shopify and WooCommerce webhooks are HMAC-verified on a loopback HTTP listener. Remote webhook providers need a trusted HTTPS relay that forwards the original body and signature. Amazon/Daraz order polling runs in the background when a supported adapter is connected.
- WhatsApp Cloud API reports are sent only after order deduplication and contain operational order details without customer addresses or email.

See [integration notes](docs/INTEGRATIONS.md) for API prerequisites and bulk-file columns.

## Safety and operational limits

Products are created as drafts where the marketplace supports draft state. Email replies are drafts by default; enabling automatic SMTP send is an explicit Settings option. WhatsApp reporting requires valid Meta credentials and an opted-in destination. Bulk imports run sequentially with a 1,000 row cap and report partial failures without claiming rollback. Review product data and platform compliance before publishing.

The local webhook listener binds to `127.0.0.1` and is not itself a public endpoint. Do not expose it without TLS and a hardened relay. Amazon SP-API product type attributes are marketplace-specific. Gemini model availability, marketplace APIs, webhook policies, and OAuth permissions can change; verify with providers before operational use.

## Windows release

Pushing to `main` creates a Windows build artifact. Pushing a `v*` tag builds `OmniStoreAIManager.exe` on `windows-latest` and creates/updates a GitHub Release with the executable. GitHub Actions must be enabled and allow the workflow token to write repository contents. The binary is not code-signed; Windows SmartScreen may warn until a publisher certificate is configured.

The self-contained `upgrade_to_v3.py` master script expects a clean existing clone on `main`, safely overwrites the V3-owned files, removes only the known V2 source/generator paths, writes the V3 project, and performs the `git add`, commit, `v3.0.0` tag, and `git push origin main --tags` operations.
