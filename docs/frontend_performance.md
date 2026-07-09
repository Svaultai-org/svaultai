# VaultAI frontend performance

_Last updated: 2026-07-08._

VaultAI is a private vault app. It has to feel fast — but it must
never feel fast because it's lying. This doc captures the perf
targets we hold ourselves to, the rules for how loading states can
and can't be used, how caching works, how VaultAI Chat is expected
to respond, and how to profile the app locally.

## Perf targets

### General UI

| Interaction | Target |
|---|---|
| Any user action feedback (button ripple, form focus) | under 100 ms |
| Cached screen render (data in memory, no network) | under 300 ms |
| Normal screen usable when backend is healthy | under 1 s |
| Full-page loader when cached data exists | **never** |
| Duplicate identical requests within 30–60 s window | **never** (unless the user explicitly refreshes) |

### VaultAI Chat

| Milestone | Target |
|---|---|
| User bubble appears after send click | immediately, before the network call is even in-flight |
| Assistant "thinking" indicator | under 100 ms |
| Deterministic FAQ / vault-card response | under 500 ms end-to-end |
| Chat waits on a slow crypto provider before showing the card shell | **never** — show the shell + inline loading, refresh the number when the provider responds |
| Chat hangs indefinitely on backend timeout | **never** — show retry or "still working…" |

### Crypto Vault

| Behaviour | Target |
|---|---|
| Dashboard shell paints | under 300 ms |
| Cached balances appear on remount | immediately |
| Provider refresh | inline, not a full-screen loader |
| XMR balance shown when the scanner isn't ready | never — the scanner-gated `unavailable` state is the truth |
| Duplicate balance / activity request on remount | never |

## Loading-state rules

1. If cached data exists **and** the cache entry is not expired,
   render it immediately and refresh quietly in the background.
2. Never show a blank full-screen loader when partial data is
   already available.
3. Skeleton placeholders are OK when there is genuinely no data.
   Use them where the shape of what's coming is predictable.
4. **No fake values ever.** No fake `0` for a balance the provider
   never confirmed. No fake row for a transaction that isn't real.
5. Provider errors are closed-set (`provider_unavailable`,
   `scanner_not_ready`, etc.). They render as an inline reason
   with a retry action, not as an endless spinner.
6. Every request that could hang has a timeout + a fallback. The
   fallback is a safe error state ("Still working…", retry
   button) — not a fake success.

## Cache rules

Live cache module: [`vault_ai_frontend/lib/perf/frontend_cache.dart`](../vault_ai_frontend/lib/perf/frontend_cache.dart).

Rules:

- **In-memory only.** Nothing persists to disk / localStorage /
  SharedPreferences.
- **Cache clears on logout.** `clearCacheOnLogout()` runs
  when the session token is cleared.
- **Cache clears on vault switch.** `clearCacheOnVaultSwitch(prev, new)`
  wipes everything when the vault id changes.
- **Cache refuses secrets at insertion time.** Keys or values that
  look like `pin`, `password`, `seed`, `mnemonic`, `private key`,
  `spend/view key`, `bearer`, `api_key`, `auth_token`,
  `encrypted_data`, `session_token`, or `pin_verifier` raise
  `SensitiveDataCachedException` at `put(...)`. Sensitive values
  simply are not cacheable.
- **Safe metadata only.** Storage quota, billing status shape,
  FAQ envelopes, secure-item counts, vault overview counts, public
  crypto balances (numbers, not keys), delete-vault status envelope.
- **Stale-while-revalidate.** UI shows cached value immediately,
  fires a fresh request in the background, and updates when the
  new response lands.

### Recommended TTLs

| Bucket | TTL | Rationale |
|---|---|---|
| `crypto:balance:` | 60 s | Real balances move on-chain rarely inside a browsing session |
| `crypto:activity:` | 60 s | Same |
| `vault:overview:` | 15 s | Counts don't change often |
| `storage:quota:` | 60 s | Bytes don't churn between screens |
| `billing:status:` | 5 min | Stripe status is slow to update |
| `faq:envelope:` | 5 min | FAQ content is static within a session |
| `logins:list:` | 15 s | List rows are safe metadata; passwords never cached |
| `secureitems:list:` | 15 s | List rows only; values never cached |
| `ids:list:` | 15 s | List rows only; full ID numbers never cached |
| `vaultdelete:status:` | 60 s | Subscription-status envelope only |
| `settings:profile:` | 60 s | Display name, plan label, etc. |

## VaultAI Chat responsiveness architecture

The chat controller is
[`vault_ai_frontend/lib/perf/chat_send_state.dart`](../vault_ai_frontend/lib/perf/chat_send_state.dart).
Timeline of a single send:

```
click Send
    │
    ├─ 0 ms   controller.onUserSendClicked(message)
    │         → user bubble is added synchronously
    │
    ├─ <100ms controller.onAssistantThinking()
    │         → thinking indicator paints before the network call
    │
    ├─ ~500ms controller.onAssistantFirstResponse()  (fast path)
    │         → deterministic FAQ / vault card renders
    │
    └─ done   controller.onAssistantDone()
              → indicator hides
```

Fast-path routing that the backend delivers under 500 ms:

- FAQ — `vault_faq_router.py` runs regex over 66 entries; no LLM.
- Delete-vault FAQ (`delete-my-vault`, `crypto-when-vault-deleted`, etc.) — same path.
- Crypto vault status / balance shell — `crypto_vault_chat_control.py` returns the card shell immediately; the balance number arrives via a separate async fetch.
- Vault overview counts, billing status, storage usage — the closed-set intents in `vault_chat_router.py` return safe cards without touching the LLM.

LLM fallback only runs when none of those match. When it runs, the
controller stays in `ChatSendPhase.thinking` and the frontend
shows the indicator — never a fake response.

Absolute rules:

- Chat never reveals secrets. `crypto_vault_chat_control.py`
  refuses seed / private key / mnemonic / spend key / view key
  questions with a refusal card.
- Chat never broadcasts a crypto transaction. Send-draft cards
  ship with `canBroadcast=False`.
- Chat never bypasses the trusted-device / PIN / phrase gates for
  reveal, delete, or send flows.

## Known slow paths (as of 2026-07-08)

These are called out honestly so future readers can either measure
them again or fix them if the perf reg comes back:

- **First paint after cold start on web.** Flutter web ships a
  large main.dart.js. First paint is bound by main bundle size —
  not something the app code can fix short of a code-split.
  Tracked separately.
- **LLM-fallback chat responses.** When a message doesn't match any
  deterministic route (`vault_chat_router.classify_and_build_vault_intent`
  returns `INTENT_UNRECOGNIZED`), the backend falls through to an
  LLM call. That call can take 3–8 s. The UI shows the thinking
  indicator throughout — never a fake response.
- **First-open Crypto Vault balances on a cold cache.** The
  provider round-trip dominates. Once cached (60 s TTL) the second
  open is instant.
- **XMR balance on web.** Never shown fake. `monero-balance-in-browser`
  FAQ explains why — real Monero scanning requires the desktop
  scanner. In-web the card renders `unavailable` immediately.

## Instrumentation

Dev-only instrumentation lives in
[`vault_ai_frontend/lib/perf/perf_trace.dart`](../vault_ai_frontend/lib/perf/perf_trace.dart).

- `PerfTrace.instance.span('screen.open.settings', () => …)` —
  wrap a synchronous block.
- `PerfTrace.instance.spanAsync('screen.open.crypto_vault', () async => …)` —
  wrap an async block.
- `PerfTrace.instance.recordRequest('request.crypto.balance')` —
  bump a counter every time the client fires the request. Used to
  detect duplicate calls.
- `PerfTrace.instance.duplicateCount('request.crypto.balance')` —
  read the excess call count.

The tracer refuses any span name that looks like a secret
(`pin`, `password`, `seed`, `mnemonic`, `private_key`, etc.). It
records only names + millisecond elapsed times. It is disabled in
`kReleaseMode` by default.

## How to profile locally

1. Cold start on web:
   ```
   flutter run -d chrome --release
   ```
   Watch the network tab and time-to-interactive.
2. Rebuild time in dev:
   ```
   flutter run -d chrome --profile
   ```
   Open DevTools timeline; look for `PerfTrace` spans in the
   Dart runtime frame timeline (they show up as user timings).
3. Duplicate-request check:
   `PerfTrace.instance.requestCountersSnapshot()` returns a
   `Map<String, int>`. A counter with a value > 1 for the same
   screen open is a bug.
4. Chat-timeline check:
   Wire the four `kSpanChat*` counters to your test or dev overlay:
   `chat.user_bubble.shown` → `chat.thinking.shown` →
   `chat.assistant.first_response` → `chat.assistant.total_response`.
   User bubble must fire before the first network log line.

## Reg tests

See
[`vault_ai_frontend/test/frontend_performance_2026_07_08_test.dart`](../vault_ai_frontend/test/frontend_performance_2026_07_08_test.dart) —
locks in:

- Chat controller shows user bubble synchronously.
- Thinking indicator fires under 100 ms wall-clock.
- Cache refuses to store secrets.
- Cache clears on logout.
- Cache clears on vault switch.
- Perf trace refuses sensitive span names.
- Duplicate-request counter is available.
