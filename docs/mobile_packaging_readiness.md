# Mobile packaging readiness (Android + iOS)

Notes and a checklist for the eventual Play Store + App Store
submission. **Do not build store binaries yet** — this is a
planning doc so store-ready work is not blocking the web launch.

The web launch runs against `https://app.svaultai.com` and does not
require any store presence. Mobile is a separate track that can
follow at its own pace.

---

## 1. Identifiers

| Field | Proposal |
|---|---|
| Android package name    | `com.svaultai.app` |
| iOS bundle identifier   | `com.svaultai.app` |
| macOS bundle identifier | `com.svaultai.app` |
| Windows package name    | `com.svaultai.app` |
| Linux app id            | `com.svaultai.app` |
| Display name            | `VaultAI` |
| Legal entity name       | (fill in the actual entity that files the store listing) |

Reserve the identifier once in each store console before writing
code that assumes it. Renaming after publish is painful.

**Current tree** (as of `flutter create` defaults): the app is
still under `vault_ai_frontend` with the generic Flutter identifier.
Before store submission, run:

```bash
cd vault_ai_frontend
flutter pub add --dev change_app_package_name
dart run change_app_package_name:main com.svaultai.app
```

Verify the change in:

- `vault_ai_frontend/android/app/build.gradle` — `applicationId`
- `vault_ai_frontend/ios/Runner.xcodeproj/project.pbxproj` —
  `PRODUCT_BUNDLE_IDENTIFIER`
- `vault_ai_frontend/macos/Runner.xcodeproj/project.pbxproj`
- `vault_ai_frontend/linux/CMakeLists.txt` — `APPLICATION_ID`
- `vault_ai_frontend/windows/runner/main.cpp` — window class name

---

## 2. Store assets

- [ ] **App icon** — 1024×1024 master (square, opaque, no
      transparency at edges, no rounded corners baked in). Use
      `flutter_launcher_icons` to derive per-density Android + iOS
      variants.
- [ ] **Splash screen** — `flutter_native_splash` for both Android
      (`android/app/src/main/res/`) and iOS
      (`ios/Runner/Assets.xcassets/LaunchImage.imageset/`). Dark
      background matches the app shell (`#1F1F1F` / `#262626`).
- [ ] **Screenshots**:
    - Android — phone (1080×1920), 7-inch tablet, 10-inch tablet.
    - iOS — iPhone 6.7" (1290×2796), iPhone 6.5", iPad 12.9".
    - Minimum 3 per size class, maximum 8. Show: landing, chat,
      Crypto Vault receive, Files list, Settings.
- [ ] **Feature graphic** (Play Store) — 1024×500.
- [ ] **Promo video** (optional, both stores).

---

## 3. Store metadata

Both stores need the same core copy in slightly different formats.

- [ ] **Short description** (Play Store, 80 chars) — one-liner
      matching the README opener: "Your private digital vault with
      an assistant that speaks your language."
- [ ] **Full description** (Play Store, 4000 chars) — pull from
      the "What you can put in it" and "VaultAI Chat" sections of
      the README.
- [ ] **App Store subtitle** (30 chars) — e.g. "Private vault + AI
      assistant".
- [ ] **App Store keywords** (100 chars total) — comma-sep, e.g.
      `vault,privacy,passwords,files,crypto,wallet,encrypted,assistant,secure,storage`.
- [ ] **App Store promotional text** (170 chars).
- [ ] **Category**: Productivity (primary), Utilities (secondary).
- [ ] **Content rating**:
    - Play Store IARC — "Everyone" with the "Cryptocurrency
      references" disclosure marked truthfully.
    - App Store — 12+ (Infrequent/Mild Simulated Gambling: No;
      Cryptocurrency: Yes, informational only).

---

## 4. Legal + support surfaces (required by stores)

- [ ] **Privacy Policy URL** — public at `https://svaultai.com/privacy`
      or `https://www.svaultai.com/privacy`. Both stores reject
      submissions without one. Content must state:
    - What data VaultAI collects (email + vault ciphertext + billing
      metadata; nothing plaintext beyond the mail address).
    - That client-side encryption means we cannot read vault
      contents.
    - Third parties involved: Stripe (billing), OpenAI (chat,
      masked projections only), your DB provider, your hosting
      provider.
    - Retention and deletion policy (delete-vault flow +
      inactive-unpaid cleanup).
- [ ] **Terms of Service URL** — public at
      `https://svaultai.com/terms`.
- [ ] **Support email** — `support@svaultai.com` (or wherever you
      route it). Must be a real inbox someone reads.
- [ ] **Contact info** — legal entity name + street address (both
      stores require this; App Store shows it publicly on the
      listing).

---

## 5. Backend / config

- [ ] Production API URL baked into the mobile release build:
      ```
      flutter build apk       --release \
        --dart-define=BACKEND_BASE_URL=https://api.svaultai.com
      flutter build appbundle --release \
        --dart-define=BACKEND_BASE_URL=https://api.svaultai.com
      flutter build ios       --release --no-codesign \
        --dart-define=BACKEND_BASE_URL=https://api.svaultai.com
      ```
- [ ] The same release-mode guard that fires on web
      (`vault_ai_frontend/lib/main.dart` ~L595) fires on mobile —
      a release build without `https://…` refuses to boot.

---

## 6. Signing + distribution

### Android

- [ ] Upload key generated (`keytool -genkey -v -keystore
      upload-keystore.jks -storetype JKS -keyalg RSA -keysize 2048
      -validity 10000 -alias upload`).
- [ ] `key.properties` created **outside** the repo (e.g. in
      `$HOME/.gradle/`), referenced from
      `vault_ai_frontend/android/key.properties.local` via an
      untracked `.gitignore`d symlink.
- [ ] `vault_ai_frontend/android/app/build.gradle` release signing
      block set up; `signingConfigs.release` points at
      `key.properties`.
- [ ] Play Play App Signing enabled — Google holds the app signing
      key; you keep the upload key.
- [ ] First upload: internal testing track.
- [ ] Play Console → Data safety form filled — VaultAI collects
      email, transaction history (billing), and app activity;
      encrypted vault contents are user-only.

### iOS

- [ ] Apple Developer Program account paid.
- [ ] `Certificates, Identifiers & Profiles` set up:
    - App ID: `com.svaultai.app` with Push, Sign in with Apple,
      Associated Domains enabled (associated domains needed if you
      later add universal links to `app.svaultai.com`).
    - Distribution certificate.
    - App Store provisioning profile.
- [ ] Xcode signing team set on `Runner.xcodeproj` (target `Runner`
      → Signing & Capabilities).
- [ ] First upload: TestFlight internal testers.
- [ ] App Store Connect → App Privacy: same disclosure as Play
      Store Data Safety.
- [ ] Encryption Export Compliance — check "Yes, uses non-exempt
      encryption" (VaultAI uses AES-GCM); provide the annual
      self-classification report (ATS 5D002 exemption applies
      because encryption is a supporting feature, not the product
      offering; consult a real lawyer, not this doc).

---

## 7. Play Store — Data Safety answers

Fill on submission. Ballpark answers based on the current
architecture:

- **Data collected** — user email (account), vault ciphertext
  (encrypted at rest, unreadable to us), billing metadata (Stripe
  customer id, subscription status), app activity (last-login,
  last-unlock), device info (trusted device id + label + user-
  agent brand).
- **Data shared** — Stripe (billing metadata). OpenAI (chat
  messages sent as-is, without vault ciphertext — the message
  string may include free-form text the user types). Nothing else.
- **Encryption in transit** — Yes, HTTPS everywhere.
- **Encryption at rest** — Yes, AES-GCM-256 per vault, keyed by a
  PIN we never receive in plaintext.
- **Data deletion request** — In-app "Delete Vault" wipes the
  vault + cascade + sessions. There is no separate email-to-delete
  request path yet.

---

## 8. App Store — App Privacy answers

- **Data used to track you** — None.
- **Data linked to you** — Contact Info (email), Financial Info
  (via Stripe — we do not store card data), Identifiers (device
  id used only for trusted-device gate), Usage Data (last-login),
  User Content (vault ciphertext; not readable to us).
- **Data not linked to you** — Diagnostics (crash logs, if you
  wire a crash reporter).

Restate the encryption-in-transit + encryption-at-rest disclosures.

---

## 9. Release cadence proposal

- **Web first** — `https://app.svaultai.com` goes live using the
  existing Flutter web build. No store approval needed.
- **TestFlight + Play internal** — same codebase, same
  `BACKEND_BASE_URL=https://api.svaultai.com`, distributed to
  internal testers only. Runtime is identical to web except for
  packaging and OS-integration.
- **Public store rollout** — after 2 weeks of TestFlight without
  regressions, submit to both public stores. Expect 1-3 days of
  review each.

---

## 10. Non-blockers for the web launch

- Store icons / screenshots / metadata — needed for store
  submission, not for web.
- Privacy Policy / Terms URLs — needed for store submission AND
  for web launch. Draft even if unpolished before public URL.
- Play App Signing / Apple certificates — needed for store
  binaries only.
- Package rename — do before the FIRST store upload; not urgent
  for web.
