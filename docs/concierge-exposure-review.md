# Concierge free exposure checks review candidate

The release candidate uses free password checks, with no paid API subscription
required. It checks eligible saved passwords for known exposure, weakness and
reuse after the user opts in and unlocks the vault. Email monitoring and stealer
logs are deferred; private-file exposure and comprehensive dark-web scanning are
unsupported. Nothing has been pushed or deployed. Human review remains required.

The implementation is additive and disabled by default. No existing account,
authentication, billing, wallet, login, file or memory rows are transformed.
Migration `0047_concierge_exposure` adds separate feature tables. User/account
deletion cascades through their vault foreign keys. A downgrade removes only
these new feature tables; back up any required feature history before downgrading.

## Privacy boundaries

Free password checks happen on the unlocked client. Only a five-character
password hash prefix goes to HIBP Pwned Passwords; the full password and hash stay
on the device. Local weakness and reuse checks require no external provider.
Passwords, private keys, vault keys, PINs and private file contents are never
provider inputs.
Client state sync is a bounded opaque AES-GCM blob encrypted by the client; the
server does not decrypt this state. It has its own table, not a dummy saved login.

The retained, future paid email integration uses six-character email hash ranges
matched on the client. Unmatched response rows are transient, never persisted or
cached. Free mode blocks this integration even if a paid key is configured.

Future background email monitoring is a different opt-in boundary, also blocked
in free mode. The user explicitly authorizes sending a chosen full email address
to SVaultAI and HIBP and storing it
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

The [Pwned Passwords API](https://haveibeenpwned.com/API/v3#PwnedPasswords)
requires no API key or subscription. `VAULTAI_CONCIERGE_PROVIDER_MODE=free` is the
default. It reports email/background/stealer checks as `deferred` rather than
provider failures, and prevents paid requests, subscription probes and background
monitor claims. Encrypted state synchronization and consent withdrawal remain
available. Unknown provider modes fail closed.

The future `hibp` mode must be enabled deliberately after a separate review.
Use [HIBP's official API documentation](https://haveibeenpwned.com/API/v3) and
verify the purchased plan through `subscription/status`. Email ranges require
`IncludesKAnon`; the optional email stealer-log API requires `IncludesStealerLogs`
and the email domain to appear in the provider's verified subscribed domains.
An arbitrary personal Gmail address is not supported by that stealer API.
The service covers known provider records, not every leak or a comprehensive
dark-web crawl. It excludes sensitive, retired and opted-out records. A successful
no-match means only “no known findings in this source,” never “safe/all clear.”
Private-file exposure has no verified provider here and is explicitly unsupported.
HIBP attribution remains visible. Any future paid API key stays server-side.

## Free email provider assessment

[LeakCheck Public API](https://docs.leakcheck.io/public-api/lookup) offers no-key
email-hash checks at one request per second. Its documentation permits commercial
use with attribution, but [general terms section 5.3](https://leakcheck.io/tos)
restrict redistribution of access or data. Before enabling SVaultAI end-user
results or background rechecks, obtain written clarification of that integration.
The public documentation sample hash returned HTTP 200 without an API key; no
customer address was queried. A stable 24-character email hash is not encryption
or HIBP-style range anonymity, so a future adapter needs its own consent wording.

[XposedOrNot](https://xposedornot.com/api_doc) offers limited free email lookups,
but requires plaintext email and [written permission for commercial
redistribution](https://xposedornot.com/terms). Neither free email alternative is
enabled in this candidate. Neither provides verified private-file scanning or
comprehensive dark-web coverage.

## Configuration before any reviewed rollout

- Keep `VAULTAI_CONCIERGE_PROVIDER_MODE=free`. No paid key, provider subscription
  or server monitoring key is required for password checks.
- Enable `VAULTAI_CONCIERGE_ENABLED` only after human review and the additive
  migration. Keep background and stealer-log feature switches off.
- Run migration in a disposable database and review consent/retention language,
  quota, network failure behavior and the free-only UI before rollout.
- Existing tests use synthetic fixtures/injected transport. Passing them does
  not establish live coverage or paid provider access.

### Optional paid integration for a later release

- Configure `CONCIERGE_HIBP_API_KEY` through the secret store, not a chat or client,
  only after paid service approval. Set provider mode to `hibp` deliberately.
- Provision independent 32-byte `CONCIERGE_MONITORING_KEY` (unpadded base64url).
  Neither vault keys nor PINs are suitable. For rotation supply
  `CONCIERGE_MONITORING_KEYRING_JSON` and `CONCIERGE_MONITORING_ACTIVE_KEY_ID`;
  retain previous keys until every row is rewrapped by successful checks.
- Set `VAULTAI_CONCIERGE_HIBP_RPM` no higher than the actual provider plan. Durable
  database coordination applies to both foreground and background requests.
- Background polling and optional stealer logs each have additional default-off
  feature switches.

In paid mode, the scheduler claims one due monitor per 30-second iteration. A
lease plus row locking avoids concurrent duplicate work; shared provider pacing and vault
budgets bound usage. Success is normally polled every 24 hours (configurable
between one hour and seven days); failures are retried with explicit unavailable
status. It does not depend on a vault being decrypted. It does not push personal
results to external notification services; alerts are read when Concierge opens.

## API contract

All routes require the existing authenticated trusted-device dependency:

- `GET /concierge/capabilities`: explicit status per provider capability, consent
  version, provider mode, coverage, attribution, verified email domains for
  conditional stealer support. Planned free-mode deferral remains distinct from
  missing keys, unsupported plans and actual provider failures.
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

Before production: review the free-only client UI, verify consent/state sync and
real password-prefix checks with synthetic public inputs, and show the user the
candidate. Paid-mode provider access, key rotation and background monitoring are
separate future rollout requirements, not requirements for the free password
release. No deployment is authorized solely by this document.
