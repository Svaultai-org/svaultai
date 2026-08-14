# SVaultAI provider-neutral billing cutover

Status: repository implementation complete; external store/provider setup is
required before purchases can be accepted.

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
- Apple product IDs are intentionally unset until App Store Connect creates
  the real IDs.
- Web checkout remains disabled until a provider approves the fully disclosed
  business model in writing.

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

## Public Apple download configuration

- `APP_STORE_URL` is the canonical Apple App Store listing shared by iPhone,
  iPad, and Mac when one listing supports all three platforms. Until it is
  configured, the standard Apple badge remains visible but has no link.
- `MAC_APP_STORE_URL` is optional and must remain empty when the canonical
  Apple listing already serves macOS. If a genuinely distinct Mac destination
  is created later, setting it adds one separate "Download for Mac" action.
- Neither value may point to an invented, placeholder, or unpublished URL.

## Apple work remaining on macOS

1. Create the real auto-renewable subscription and base product configuration
   in App Store Connect; do not reuse the Google identifier by assumption.
2. Configure the actual bundle ID, numeric Apple app ID, Apple PKI root
   certificates, and an explicit `VAULTAI_APPLE_PRODUCT_MAP_JSON` mapping.
3. Set App Store Server Notifications V2 production and sandbox URLs to
   `/billing/apple/notifications-v2`, then use Apple's test-notification API.
4. Implement the StoreKit 2 client with the backend-provided opaque
   `appAccountToken`, send Apple-signed transaction JWS to
   `/billing/apple/verify-transaction`, and finish only verified transactions.
5. Validate purchase, restore, renewal, grace, billing retry, expiration,
   refund, revocation, duplicate notification, and cross-device sign-in using
   Xcode StoreKit testing and App Store sandbox. Windows cannot certify these.

## Web-card provider shortlist

No candidate is activated, and none should be described as approved until it
confirms the exact SVaultAI model in writing: private SaaS/cloud storage plus a
non-custodial wallet whose keys remain client-side and whose transactions are
locally signed.

1. **Adyen — recommended for an approval request.** It supports recurring
   token payments and authoritative webhooks. Its current restricted-business
   list explicitly treats cloud storage/file sharing and several financial or
   crypto categories as restricted for direct merchants, so SVaultAI must seek
   pre-approval and describe the non-custodial boundary accurately. Adyen is a
   PSP, not merchant of record. Legal-entity jurisdiction and expected volume
   must be confirmed during sales underwriting.
2. **PayPal Braintree — second approval request.** It supports subscription
   lifecycle webhooks and signed webhook parsing. PayPal's acceptable-use
   policy requires pre-approval for cryptocurrency-related activity; the
   application must disclose wallet functionality and private cloud storage.
   It is a PSP/gateway, not merchant of record. Availability depends on the
   merchant legal entity's supported country and underwriting.
3. **Paddle — only after written eligibility confirmation.** It provides
   merchant-of-record checkout, subscription lifecycle, tax handling,
   idempotency keys, and webhooks for SaaS. Its acceptable-use policy prohibits
   exchanges/trading platforms and other financial or virtual-currency
   services. Although SVaultAI does none of those, the wallet surface makes
   classification uncertain; do not integrate unless Paddle explicitly
   approves the disclosed non-custodial product.

Official policy/technical sources reviewed on 2026-08-14:

- https://www.adyen.com/legal/list-restricted-prohibited/
- https://docs.adyen.com/online-payments/tokenization/make-token-payments
- https://developer.paypal.com/braintree/docs/reference/general/webhooks/overview
- https://www.paypal.com/us/legalhub/paypal/acceptableuse-full
- https://developer.paddle.com/get-started/how-paddle-works/
- https://www.paddle.com/help/start/intro-to-paddle/what-am-i-not-allowed-to-sell-on-paddle

## Legacy Stripe boundary

`/billing/checkout-session` and `/billing/portal-session` are stable retired
route tombstones and never contact Stripe. The old schema, webhook adapter,
event log, and historical records remain intact for audit/rollback. Core
startup no longer imports, probes, or requires a Stripe merchant account.
