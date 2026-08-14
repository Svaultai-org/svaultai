# SVaultAI keyless Google Play Billing deployment

This runbook deploys only the isolated Android Publisher bridge. SVaultAI's
production database, user authentication, vault backend, encrypted records,
files, AI, and wallet systems remain on Hostinger. No Play build or purchase is
created by these steps.

## Fixed production contract

```text
PROJECT_ID=svaultai-production
REGION=us-east4
SERVICE=svaultai-google-play-billing
RUNTIME_SERVICE_ACCOUNT=svaultai-play-billing@svaultai-production.iam.gserviceaccount.com
BUILD_SERVICE_ACCOUNT=svaultai-cloud-run-builder@svaultai-production.iam.gserviceaccount.com
PACKAGE_NAME=com.svaultai.app
PRODUCT_ID=svaultai_storage_50gb
BASE_PLAN_ID=monthly-auto
BASE_PLAN_TYPE=AUTO_RENEWING
BILLING_PERIOD=P1M
SECRET_ID=svaultai-google-play-bridge-hmac
```

`us-east4` is selected because the production Hostinger node is in
Massachusetts. Cloud Run must run with one worker and `--max-instances=1` so
the bounded nonce replay cache covers all live requests. Restarts can erase
that short cache, but requests still expire after 60 seconds and every exposed
Google operation is read-only or idempotent; the bridge has no entitlement
grant capability.

## Owner bootstrap (keyless)

Run from the repository root on an owner-controlled workstation after
interactive `gcloud auth login`. Do not use `gcloud auth
activate-service-account`, create a key, or set `GOOGLE_APPLICATION_CREDENTIALS`.

```bash
PROJECT_ID=svaultai-production
REGION=us-east4
SERVICE=svaultai-google-play-billing
PLAY_SA=svaultai-play-billing@svaultai-production.iam.gserviceaccount.com
BUILD_SA=svaultai-cloud-run-builder@svaultai-production.iam.gserviceaccount.com
SECRET_ID=svaultai-google-play-bridge-hmac

gcloud config set project "$PROJECT_ID"
gcloud services enable \
  androidpublisher.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  run.googleapis.com \
  secretmanager.googleapis.com \
  pubsub.googleapis.com
```

The interactive deployer needs `roles/iam.serviceAccountUser` on `PLAY_SA`.
Grant that binding only to the exact human/group that deploys the service; do
not make the Play service account an Owner or project Admin.

Use a separate keyless build-only identity. `roles/run.builder` supplies the
documented source-build permissions without broadening the default Compute
Engine identity or the Play runtime identity:

```bash
gcloud iam service-accounts describe "$BUILD_SA" >/dev/null 2>&1 || \
  gcloud iam service-accounts create svaultai-cloud-run-builder \
    --display-name="SVaultAI Cloud Run source builder" \
    --description="Keyless build-only identity for the Play billing bridge"

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${BUILD_SA}" \
  --role=roles/run.builder \
  --condition=None
```

Create one application HMAC secret without printing its value. Generate it on
the Hostinger host in its existing root-only secret directory, then stream it
directly into Secret Manager from the authenticated workstation:

```bash
ssh root@2.25.204.202 \
  'install -d -o root -g root -m 0700 /root/svaultai-secrets; umask 077; test -s /root/svaultai-secrets/google-play-bridge-hmac || openssl rand -base64 48 > /root/svaultai-secrets/google-play-bridge-hmac'

gcloud secrets describe "$SECRET_ID" >/dev/null 2>&1 || \
  gcloud secrets create "$SECRET_ID" --replication-policy=automatic

ssh root@2.25.204.202 \
  'cat /root/svaultai-secrets/google-play-bridge-hmac' | \
  gcloud secrets versions add "$SECRET_ID" --data-file=-

gcloud secrets add-iam-policy-binding "$SECRET_ID" \
  --member="serviceAccount:${PLAY_SA}" \
  --role=roles/secretmanager.secretAccessor
```

This secret authenticates only the Hostinger-to-bridge application channel. It
is not a Google credential and cannot be used to obtain a Google access token.

## Deploy Cloud Run

```bash
gcloud run deploy "$SERVICE" \
  --source=google_play_billing_bridge \
  --region="$REGION" \
  --service-account="$PLAY_SA" \
  --build-service-account="projects/${PROJECT_ID}/serviceAccounts/${BUILD_SA}" \
  --set-env-vars="VAULTAI_GOOGLE_PROJECT_ID=${PROJECT_ID},VAULTAI_GOOGLE_PLAY_SERVICE_ACCOUNT_EMAIL=${PLAY_SA},VAULTAI_GOOGLE_PLAY_PACKAGE_NAME=com.svaultai.app" \
  --set-secrets="VAULTAI_GOOGLE_PLAY_BRIDGE_HMAC_SECRET=${SECRET_ID}:latest" \
  --allow-unauthenticated \
  --ingress=all \
  --cpu=1 \
  --memory=512Mi \
  --concurrency=20 \
  --min-instances=0 \
  --max-instances=1 \
  --timeout=30

BRIDGE_URL="$(gcloud run services describe "$SERVICE" \
  --region="$REGION" --format='value(status.url)')"
curl --fail --silent --show-error "${BRIDGE_URL}/v1/health"
```

`--allow-unauthenticated` is needed because the external Hostinger host has no
Google workload identity. It does not expose an unauthenticated grant path:
the service contains no grant route, and all three Google operations enforce
application HMAC before resolving ADC. `/v1/health` is the only public
operation.

## Hostinger activation and proof

Do not remove direct ADC settings or activate the bridge until `/v1/health` is
healthy. Add the exact Cloud Run HTTPS origin and the existing secret value to
the root-owned production environment without printing the secret:

```text
VAULTAI_GOOGLE_PLAY_BRIDGE_URL=<exact Cloud Run status.url>
VAULTAI_GOOGLE_PLAY_BRIDGE_HMAC_SECRET=<contents of root-only secret file>
VAULTAI_GOOGLE_PLAY_SERVICE_ACCOUNT_EMAIL=svaultai-play-billing@svaultai-production.iam.gserviceaccount.com
VAULTAI_GOOGLE_PLAY_PACKAGE_NAME=com.svaultai.app
```

Do not set `GOOGLE_APPLICATION_CREDENTIALS` and do not mount a JSON credential.
Deploy the reviewed Hostinger backend image, then run:

```bash
docker exec vaultai-backend python scripts/verify_google_play_bridge.py
curl --fail --silent --show-error https://api.svaultai.com/health
```

The expected safe probe output is:

```text
GOOGLE_ADC_RESOLUTION=PASS
ADC_IDENTITY=svaultai-play-billing@svaultai-production.iam.gserviceaccount.com
ANDROID_PUBLISHER_API_AUTH=PASS
GOOGLE_PLAY_PRODUCT_ID=svaultai_storage_50gb
GOOGLE_PLAY_BASE_PLAN_ID=monthly-auto
GOOGLE_PLAY_BASE_PLAN_TYPE=AUTO_RENEWING
GOOGLE_PLAY_BILLING_PERIOD=P1M
```

## RTDN: direct authenticated delivery to Hostinger

RTDN is not routed through Cloud Run. Reuse the hardened Hostinger endpoint and
a separate push-only identity:

```text
TOPIC=projects/svaultai-production/topics/svaultai-google-play-rtdn
SUBSCRIPTION=svaultai-google-play-rtdn-push
PUSH_SERVICE_ACCOUNT=svaultai-play-rtdn-push@svaultai-production.iam.gserviceaccount.com
PUSH_ENDPOINT=https://api.svaultai.com/billing/google-play/rtdn
PUSH_AUDIENCE=https://api.svaultai.com/billing/google-play/rtdn
```

Use the exact Pub/Sub commands in `docs/BILLING_PROVIDER_CUTOVER.md`. Grant
`roles/pubsub.publisher` on only this topic to
`google-play-developer-notifications@system.gserviceaccount.com`. Give the
Pub/Sub service agent Token Creator on only the RTDN push identity. That push
identity receives no Play Console billing permission. Leave payload unwrapping
disabled because Hostinger requires the standard signed Pub/Sub envelope.

## Security invariants

- `iam.disableServiceAccountKeyCreation` stays enabled.
- No service-account key exists in source, images, Hostinger, Cloud Run, or the
  Android app.
- The bridge sends Google only the fixed package/product and opaque Play
  purchase token required by Android Publisher.
- Vault plaintext, PINs, MVKs, credentials, files, memories, wallet keys, and
  seed phrases never enter the bridge.
- Hostinger verifies the signed bridge response and independently validates
  product, base plan, lifecycle, and hashed account binding before writing.
- No production database reset, data migration, crypto change, transaction,
  fund movement, Play upload, or real purchase is part of this deployment.

Official references:

- https://cloud.google.com/run/docs/securing/service-identity
- https://cloud.google.com/run/docs/configuring/services/service-identity
- https://cloud.google.com/run/docs/configuring/services/secrets
- https://cloud.google.com/run/docs/deploying-source-code
- https://cloud.google.com/pubsub/docs/authenticate-push-subscriptions
- https://developer.android.com/google/play/billing/getting-ready
