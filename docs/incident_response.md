# VaultAI incident response

Living runbook for security incidents. Update this after every
incident, real or drill.

## Triage in the first 15 minutes

1. **Confirm the incident is real.** Do not act on a single log
   line; find at least one other signal that agrees. Common false
   positives: legitimate mass-upload during onboarding, PIN typo
   burst by a real user, a Stripe webhook retry storm.
2. **Preserve evidence.** Snapshot logs for the affected time
   window BEFORE you rotate anything.
3. **Pick a comms lane.** One channel, one incident commander.
4. **Decide impact class.** See below.

## Impact classes

| Class | Signal | First response |
|---|---|---|
| P0 — active data breach | Session hijack in progress, or bulk decryption evidence | Revoke ALL sessions, rotate `VAULT_SESSION_SECRET`, freeze auth |
| P1 — mass abuse | Sustained burst-limit hits, `upload_burst_detected` or `delete_burst_detected` for one vault | Freeze the vault (`vaults.must_reset=TRUE` blocks unlock), notify the user |
| P2 — enumeration / brute force | Sustained `rate_limited_auth`, `pin_lockout_triggered`, or `auth_failure_burst` from one origin | Tighten `VAULTAI_AUTH_LOGIN_LIMIT`, block the origin at the edge |
| P3 — webhook spoofing | `webhook_signature_fail` from an IP not owned by Stripe | Rotate `STRIPE_WEBHOOK_SECRET`; verify no fraudulent entitlement grants landed |
| P4 — privacy leak | Sensitive substring found in logs during a spot check | Redact the log store; add a regression test that the substring can't recur |

## Playbooks

### P0 — session or key compromise

1. Rotate `VAULT_SESSION_SECRET` (kill every session).
2. Force logout: `revoke_all_sessions_for_vault(vault_id)` or a
   bulk equivalent. Every existing bearer becomes invalid.
3. Do NOT rotate PIN salts. That would silently break every
   vault. Users re-unlock at their next login and their key
   derives from the same salt.
4. Look for tombstones: `SELECT deleted_at, deletion_reason FROM
   vault_deletion_tombstones WHERE deleted_at > <t0>;`. Compare
   against expected auto-delete volume.
5. Communicate to affected users with a security-page banner and
   an email. Do NOT reveal which vaults are involved in the
   public banner.

### P1 — vault under mass-action attack

Symptoms: repeated `rate_limited_delete_burst`,
`rate_limited_upload_burst`, or unusual spikes in `delete_vault_requested`.

1. Freeze the vault by setting `must_reset=TRUE` in the `vaults`
   row. This blocks unlock at
   `routes/auth_routes.py::login` without touching the encrypted
   data.
2. Revoke sessions for the vault. The compromised session cannot
   re-issue itself.
3. Contact the user through a side channel (email on file if
   any). If none, wait for them to log in — the `must_reset`
   error surfaces to the client.
4. Once the user confirms, unfreeze and rotate their PIN via the
   normal recovery flow (or begin fresh vault if PIN is lost).

### P2 — auth brute force / credential stuffing

1. If concentrated on a small IP range, block at the edge / CDN.
2. Tighten `VAULTAI_AUTH_LOGIN_LIMIT` (e.g. 30 → 10 per hour) and
   restart. Existing legitimate users see occasional 429s; brute
   force sees a hard stop.
3. Check `vault_password_audit` for reused passwords — attacker
   may already have credentials from a leak.
4. If a specific vault crossed 5-strike lockout, that lockout
   already holds for 24h. Confirm the user was the one who
   forgot the PIN before shortening it.

### P3 — Stripe webhook abuse

1. Confirm the signature failures. `provider_event_log` will
   still record the incoming payload; walk backwards to find the
   first bad one.
2. If any bad payload SUCCEEDED a signature check, treat that as
   a full P0 (key compromise on Stripe side).
3. Otherwise rotate `STRIPE_WEBHOOK_SECRET` and reconfigure the
   Stripe endpoint. Existing legitimate webhooks retry.
4. Audit `account_subscriptions` for any grants during the abuse
   window that don't have a matching `subscription_events` row
   from a real event.

### P4 — sensitive substring in logs

1. Identify the leaking callsite. Grep for the substring in
   `logger.info(...)`, `logger.warning(...)`, `print(...)`. Also
   check for a `str(payload)` that reached the log path.
2. Redact the current log store (rotate through your log
   provider's redaction API).
3. Add a test in `test_security_hardening_2026_07_08.py` that scans
   the callsite for the substring so it can't come back silently.
4. If the substring is a PIN, PIN hash, seed, or wallet address,
   treat as P0 and rotate secrets as if session compromise had
   occurred.

## Post-incident checklist

- [ ] Timeline document written and shared internally.
- [ ] Root cause captured with a concrete code / config change.
- [ ] Regression test lands with the fix, referencing this
      incident number.
- [ ] `security_threat_model.md` updated if the attack path
      changes what we defend against.
- [ ] `security_event_log` REASONS extended if a new signal is
      worth capturing.
- [ ] Runbook updated in this file so next time is faster.

## Do NOT

- Delete tombstone rows. They are the audit trail.
- Manually mutate `provider_event_log`. Stripe idempotency depends
  on it.
- Disable rate limits to "make debugging easier" during an
  incident — that just amplifies whatever is happening.
- Log a raw PIN, session token, seed, mnemonic, or wallet
  address to help investigate. If a specific value is needed for
  investigation, hash it with `security_event_log.short_hash` and
  work with the hashed prefix.
