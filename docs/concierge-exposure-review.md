# Concierge exposure checks — review candidate, not a production claim

The implementation is additive and disabled by default. No existing account,
authentication, billing, wallet, login, file or memory rows are transformed.
Migration `0047_concierge_exposure` adds separate feature tables. User/account
deletion cascades through their vault foreign keys. A downgrade removes only
these new feature tables; back up any required feature history before downgrading.

## Privacy boundaries

Password checks and email hash-range matching happen on the unlocked client.
The backend accepts only a six-character email hash prefix for the range API;
unmatched response rows are transient, never persisted or cached. Passwords,
private keys, vault keys, PINs and private file contents are never provider inputs.
Client state sync is a bounded opaque AES-GCM blob encrypted by the client; the
server does not decrypt this state. It has its own table, not a dummy saved login.

Background email monitoring is a DIFFERENT opt-in boundary. The user explicitly
authorizes sending a chosen full email address to SVaultAI and HIBP and storing it
under a dedicated server operational key. This is encryption at rest, not zero
knowledge against the operator. Only that selected email and optional item
reference are stored; no vault login name or original credential password is
read. Results are encrypted under the same operational key. Stop monitoring is
available even if the feature/key becomes unavailable. It waits for any already
in-flight bounded check; once withdrawal returns, no later poll can disclose that
address. Withdrawal cannot undo an email already disclosed to the provider.

An item reference is verified as belonging to the current vault. If that source
item later disappears, the monitor stops instead of querying an orphaned address.
A monitored address is a consented snapshot: changing a login's email does not
silently authorize disclosing its new address. Withdraw/recreate the monitor.

## Provider capability contract

Use [HIBP's official API documentation](https://haveibeenpwned.com/API/v3) and
verify the purchased plan through `subscription/status`. Email ranges require
`IncludesKAnon`; the optional email stealer-log API requires `IncludesStealerLogs`
and the email domain to appear in the provider's verified subscribed domains.
An arbitrary personal Gmail address is not supported by that stealer API.
The service covers known provider records, not every leak or a comprehensive
dark-web crawl. It excludes sensitive, retired and opted-out records. A successful
no-match means only “no known findings in this source,” never “safe/all clear.”
Private-file exposure has no verified provider here and is explicitly unsupported.
HIBP attribution remains visible. API keys stay server-side.

## Configuration before any reviewed rollout

- Configure `CONCIERGE_HIBP_API_KEY` through the secret store, not a chat or client.
- Provision independent 32-byte `CONCIERGE_MONITORING_KEY` (unpadded base64url).
  Neither vault keys nor PINs are suitable. For rotation supply
  `CONCIERGE_MONITORING_KEYRING_JSON` and `CONCIERGE_MONITORING_ACTIVE_KEY_ID`;
  retain previous keys until every row is rewrapped by successful checks.
- Set `VAULTAI_CONCIERGE_HIBP_RPM` no higher than the actual provider plan. Durable
  database coordination applies to both foreground and background requests.
- Enable `VAULTAI_CONCIERGE_ENABLED` only after review. Background polling and
  optional stealer logs each have additional default-off feature switches.
- Run migration in a disposable database and review consent/retention language,
  secret provisioning, provider access, quota and network failure behavior.
- All tests use synthetic fixtures/injected transport. Passing them does not
  prove a paid subscription, domain approval or live coverage is available.

The scheduler claims one due monitor per 30-second iteration. A lease plus row
locking avoids concurrent duplicate work; shared provider pacing and vault
budgets bound usage. Success is normally polled every 24 hours (configurable
between one hour and seven days); failures are retried with explicit unavailable
status. It does not depend on a vault being decrypted. It does not push personal
results to external notification services; alerts are read when Concierge opens.

## API contract

All routes require the existing authenticated trusted-device dependency:

- `GET /concierge/capabilities`: explicit status per provider capability, consent
  version, coverage, attribution, verified email domains for conditional stealer
  support. Missing keys/unsupported plans/provider failures never look healthy.
- `POST /concierge/email-range`: six hex `prefix`, current `consent_version`,
  `prefix_disclosure_consent:true`; returns transient range rows and check times.
- `GET /concierge/breaches/{name}`: bounded, sanitized public breach metadata, no
  provider HTML, arbitrary URL forwarding, script content or remote image fetch.
- `POST /concierge/monitors`: explicit full-email/background consent, email,
  optional owned string `source_item_id`, optional separately consented stealer
  logs. Create returns not-checked; it never invents a successful result.
- `GET /concierge/monitors`, `POST /concierge/monitors/{id}/check`, and
  `DELETE /concierge/monitors/{id}` list, check or withdraw same-vault monitors.
  Responses never echo the full email; the client can label the affected item.
  Status, last attempted/successful timestamps and retry/error codes distinguish
  current results from retained previous findings on an unsuccessful attempt.
- `GET /concierge/state`: `{ciphertext,revision,envelope_version,updated_at}`;
  an absent row returns null ciphertext/revision zero. `PUT /concierge/state`
  accepts unpadded base64url ciphertext (29–204800 decoded bytes), envelope
  `v1`, and `expected_revision`; a stale write returns 409. Unknown fields are
  rejected. Client encryption must authenticate purpose/schema/vault ID.

Before production: validate real provider access without private vault contents,
exercise consent/withdrawal and key rotation in staging, test two-process leases
and rate coordination on actual PostgreSQL, review the client UI and show the
user the candidate. No deployment is authorized solely by this document.
