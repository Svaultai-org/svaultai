# SVaultAI provider-neutral billing cutover

Status: store-only billing implementation. Paid storage is verified only by
Apple App Store or Google Play; web card checkout is removed.

## Product contract

- Free tier: 1 GiB.
- Google Play product: `svaultai_storage_50gb`.
- Google Play base plan: `monthly-auto`.
- Google Play base-plan type: auto-renewing.
- Google Play billing period: `P1M`.
- Play Console state supplied for this release: active in 174 countries/regions.
- Entitlement: one 50 GiB storage unit.
- Intended US reference price: USD 25/month. Android displays Google Play's
  localized `ProductDetails.price`; it does not hardcode a localized price.
- Production Android package: `com.svaultai.app`.
- Apple bundle ID: `com.svaultai.app`.
- Apple numeric app ID: `6800601455`.
- Apple subscription group: `SVaultAI Storage`.
- Apple product: `svaultai.storage.50gb.monthly`.
- Apple billing period: auto-renewing `P1M`.
- Apple entitlement: 50 GiB total; the paid plan replaces the free 1 GiB
  limit and is not additive.
- Web has no checkout. A valid Apple/Play subscription follows the same account
  across devices, including web.

The provider-neutral ledger stores provider purchase identity, product/plan,
quantity, normalized status, renewal/expiry, verification state, and minimal
audit metadata. It never stores card data, vault plaintext, PINs, MVKs, wallet
private keys, or seed phrases. Provider purchase identities cannot be rebound
to another SVaultAI account.

## Google Play Console operator actions

1. Confirm the Play listing for `com.svaultai.app` is publicly available. The
   canonical public URL currently returns HTTP 404 from an unauthenticated
   fetch, so this must be resolved before the download badge can succeed.
2. Keep subscription product `svaultai_storage_50gb` and active base plan
   `monthly-auto` configured as an auto-renewing `P1M` subscription granting
   one 50 GiB unit. Keep the current production price unchanged and review
   every regional price/tax treatment in Play Console before release.
3. Link the Play developer account to a Google Cloud project. Create a
   least-privilege server service account, grant the Play Console permissions
   required to view subscriptions/orders and manage purchase acknowledgement,
   and provide credentials to the backend through Application Default
   Credentials. Never add the JSON key to the repository or APK.
4. Create a Pub/Sub topic for Real-time Developer Notifications, grant Google
   Play permission to publish, and configure the topic in Play Console.
5. Create an authenticated Pub/Sub push subscription targeting
   `https://api.svaultai.com/billing/google-play/rtdn`. Configure its OIDC
   service account and set the backend variables
   `VAULTAI_GOOGLE_PLAY_RTDN_AUDIENCE` and
   `VAULTAI_GOOGLE_PLAY_RTDN_SERVICE_ACCOUNT_EMAIL` to the exact values.
6. Add license testers and a closed-test track. Temporarily enable
   `VAULTAI_GOOGLE_PLAY_ALLOW_TEST_PURCHASES=true` only in the controlled test
   environment. Exercise successful, pending, canceled, grace, account-hold,
   expired, revoked/refunded, restore, retry, and duplicate RTDN flows.
7. Keep production test-purchase acceptance disabled after validation. Do not
   upload or roll out a build without explicit release approval.

## Google Play production authentication decision

Organization policy `iam.disableServiceAccountKeyCreation` is preserved. No
downloadable service-account key is required or permitted. Hostinger has no
ambient renewable identity that Google WIF can exchange, so the smallest
keyless topology is an isolated Cloud Run bridge with the existing Play
billing service account attached as its Cloud Run service identity.

Cloud Run resolves `google.auth.default(scopes=[androidpublisher])` through its
metadata server. The bridge rejects any configured
`GOOGLE_APPLICATION_CREDENTIALS`, verifies the exact ADC project and service
account after credential refresh, and exposes only three fixed operations:

- authoritative SubscriptionsV2 lookup;
- acknowledgement for the one fixed product;
- a read-only fixed-catalog/ADC production probe.

It has no database, account authentication, vault code, or entitlement-writing
route. Hostinger remains the only component that correlates the hashed Play
account identifier, validates lifecycle/product/base-plan state, and writes an
entitlement. RTDN continues directly to the hardened Hostinger endpoint.

Cloud Run ingress is reachable from Hostinger, but every billing operation is
protected by a 32-byte-or-longer HMAC secret held in Google Secret Manager and
the root-owned Hostinger environment. Requests carry a signed timestamp and
random nonce. A 60-second clock window, constant-time signature comparison,
single-instance bounded nonce cache, and the idempotent/read-only operation set
limit replay. Responses are independently signed over the request timestamp,
nonce, HTTP status, and exact body; Hostinger verifies that signature before
parsing Google data. The public `/healthz` route cannot call Google or change
billing state.

Deploy the bridge and configure Hostinger exactly as documented in
`docs/GOOGLE_PLAY_KEYLESS_CLOUD_RUN.md`. Then run this read-only probe in the
Hostinger backend container; it makes no purchase and writes no entitlement:

```bash
python scripts/verify_google_play_bridge.py
```

## Exact RTDN Pub/Sub configuration

Use these immutable production values:

```text
PROJECT_ID=svaultai-production
TOPIC_ID=svaultai-google-play-rtdn
TOPIC=projects/svaultai-production/topics/svaultai-google-play-rtdn
SUBSCRIPTION_ID=svaultai-google-play-rtdn-push
PUSH_SERVICE_ACCOUNT=svaultai-play-rtdn-push@svaultai-production.iam.gserviceaccount.com
PUSH_ENDPOINT=https://api.svaultai.com/billing/google-play/rtdn
PUSH_AUDIENCE=https://api.svaultai.com/billing/google-play/rtdn
```

Run from an owner-controlled Cloud Shell or authenticated administrative
workstation. These commands create no key and grant the RTDN push identity no
Play Console permissions:

```bash
PROJECT_ID=svaultai-production
TOPIC_ID=svaultai-google-play-rtdn
SUBSCRIPTION_ID=svaultai-google-play-rtdn-push
RTDN_PUSH_SA=svaultai-play-rtdn-push@svaultai-production.iam.gserviceaccount.com
RTDN_ENDPOINT=https://api.svaultai.com/billing/google-play/rtdn

gcloud config set project "$PROJECT_ID"
gcloud services enable pubsub.googleapis.com
gcloud iam service-accounts create svaultai-play-rtdn-push \
  --display-name="SVaultAI Google Play RTDN push" \
  --description="OIDC identity for authenticated Play RTDN Pub/Sub push only"
gcloud pubsub topics create "$TOPIC_ID"
gcloud pubsub topics add-iam-policy-binding "$TOPIC_ID" \
  --member="serviceAccount:google-play-developer-notifications@system.gserviceaccount.com" \
  --role="roles/pubsub.publisher"

PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" \
  --format='value(projectNumber)')"
PUBSUB_AGENT="service-${PROJECT_NUMBER}@gcp-sa-pubsub.iam.gserviceaccount.com"
gcloud iam service-accounts add-iam-policy-binding "$RTDN_PUSH_SA" \
  --member="serviceAccount:${PUBSUB_AGENT}" \
  --role="roles/iam.serviceAccountTokenCreator" \
  --project="$PROJECT_ID"

gcloud pubsub subscriptions create "$SUBSCRIPTION_ID" \
  --topic="$TOPIC_ID" \
  --push-endpoint="$RTDN_ENDPOINT" \
  --push-auth-service-account="$RTDN_PUSH_SA" \
  --push-auth-token-audience="$RTDN_ENDPOINT" \
  --ack-deadline=30
```

Do not enable payload unwrapping: the backend requires the standard wrapped
Pub/Sub JSON envelope with `message.messageId` and base64 `message.data`.
The subscription creator needs `iam.serviceAccounts.actAs` on the RTDN push
service account. The Pub/Sub service agent receives Token Creator only on that
one push service account, not project-wide. In Play Console, enter the exact
topic path `projects/svaultai-production/topics/svaultai-google-play-rtdn` and
send a test notification only after the backend email/audience variables are
live.

The endpoint verifies Google's signature and token lifetime plus exact
`aud`, `email`, `email_verified`, and issuer claims. Every lifecycle event is
then reconciled against the Android Publisher API. A full subscription void
revokes only the corresponding 50 GiB billing entitlement and preserves all
encrypted user data and billing history.

Official configuration references:

- https://developer.android.com/google/play/billing/getting-ready
- https://developer.android.com/google/play/billing/rtdn-reference
- https://cloud.google.com/pubsub/docs/authenticate-push-subscriptions
- https://cloud.google.com/run/docs/securing/service-identity
- https://cloud.google.com/run/docs/configuring/services/service-identity
- https://cloud.google.com/iam/docs/best-practices-service-accounts

## Public Apple download configuration

- `APP_STORE_URL` is the canonical Apple App Store listing shared by iPhone,
  iPad, and Mac when one listing supports all three platforms. Until it is
  configured, the standard Apple badge remains visible but has no link.
- `MAC_APP_STORE_URL` is optional and must remain empty when the canonical
  Apple listing already serves macOS. If a genuinely distinct Mac destination
  is created later, setting it adds one separate "Download for Mac" action.
- Neither value may point to an invented, placeholder, or unpublished URL.

## Apple production activation

The catalog was verified in App Store Connect on 2026-08-17. Product
`svaultai.storage.50gb.monthly` is in review at USD 25/month with regional
pricing configured; no duplicate Apple products exist.

1. Configure the bundle ID, numeric Apple app ID, Apple PKI root certificates,
   and an explicit `VAULTAI_APPLE_PRODUCT_MAP_JSON` mapping. The mapping must
   contain `quantity=1`, `entitlement_bytes=53687091200`, `plan_id=monthly`,
   and `billing_period=P1M`.
2. Set App Store Server Notifications V2 production and sandbox URLs to
   `/billing/apple/notifications-v2`, then use Apple's test-notification API.
3. Implement the StoreKit 2 client with the backend-provided opaque
   `appAccountToken`, send Apple-signed transaction JWS to
   `/billing/apple/verify-transaction`, and finish only verified transactions.
5. Validate purchase, restore, renewal, grace, billing retry, expiration,
   refund, revocation, duplicate notification, and cross-device sign-in using
   Xcode StoreKit testing and App Store sandbox. Windows cannot certify these.

## Retired card-billing boundary

Stripe runtime routes, SDK, merchant configuration, checkout, portal, and live
cancellation calls are removed. Historical migrations and payment records remain
for accounting and audit; they never grant storage in the store-only resolver.
Migration 0046 releases retired web-card ownership without deleting vault data.

Before deploying, cancel all still-recurring Stripe subscriptions in the merchant
dashboard and confirm no future charge is scheduled. Removing credentials or
code alone cannot stop provider-side charges. Do not finalize draft invoices.
Then disable the obsolete webhook and revoke/remove the old credentials from
production configuration. See STORE_ONLY_BILLING.md for the cutover checklist.
