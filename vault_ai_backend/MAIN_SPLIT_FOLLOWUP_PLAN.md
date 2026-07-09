# `main.py` + `main.dart` split — follow-up plan (NOT this slice)

## Status

* `vault_ai_backend/main.py` is **~14 100 lines**.
* `vault_ai_frontend/lib/main.dart` is **~10 400 lines**.
* Both files are unmistakably a maintenance risk: locality of behaviour
  is gone, dead branches are hard to spot, and review-time effort
  scales super-linearly.

Per the config-cleanup slice spec, we are NOT splitting these in this
slice. This document captures the plan for the next slice that DOES
take them on, so we don't start cold when we do.

## Why we're not splitting now

* The cleanup slice is about **risk reduction** (fail-closed secrets,
  centralised config, no demo magic numbers). A 14 k-line refactor in
  the same slice multiplies merge conflicts, blast radius, and review
  surface.
* `main.py` and `main.dart` contain the highest-value behaviour AND
  the densest hidden coupling. Splitting them safely requires a
  separate dedicated slice with its own test plan.
* Splitting also depends on `vault_config` being in place first —
  modules pulled out of `main.py` need a single import surface for
  tunables, which is exactly what this slice ships.

## Target shape (backend)

```
vault_ai_backend/
  routes/
    auth_routes.py           # /auth/* (already partially extracted)
    billing_routes.py        # /billing/*
    chat_routes.py           # /chat  (the big one)
    file_routes.py           # /upload-file/*, /file-text/*, /download/*
    folder_routes.py         # /folders/*, /folder-browser/*
    semantic_search_routes.py
    deep_answer_routes.py    # already extracted
    health_routes.py         # /health, /debug/*
  services/
    chat_pipeline.py         # orchestration that today lives inline
    chat_intent_router.py    # detect_vault_intent + dispatch
    chat_responses.py        # encrypted_reply + SSE shaping
    chat_brain_layer.py      # the brain wiring slice just landed
    pending_file_naming.py
    structured_envelopes.py  # _build_*_envelope helpers
  vault_config.py            # already shipped (this slice)
  main.py                    # bootstrap + lifespan + middleware ONLY
```

`main.py` should shrink to roughly **400 – 600 lines** after the split:
imports, FastAPI app construction, middleware, router includes,
lifespan, and the OpenAI client.

## Target shape (frontend)

```
vault_ai_frontend/lib/
  app/
    app_widget.dart          # MaterialApp root
    router.dart              # navigation
    theme.dart
  features/
    auth/
      auth_screen.dart
      auth_controller.dart
    chat/
      chat_screen.dart       # screen-level widget
      chat_controller.dart   # state + actions
      chat_envelope_parser.dart  # the type=... JSON parser
      chat_attachments.dart
    vault/
      vault_screen.dart
      vault_controller.dart
    files/
      file_open_pipeline.dart
      file_disambiguation_controller.dart
    settings/
      settings_screen.dart
    billing/
      billing_screen.dart
  ui/                        # already exists — chat_bubble, chat_cards, etc.
  main.dart                  # main() + runApp() only — <100 lines
```

## Order of operations (when we run the split slice)

1. **Carve `routes/` first.** Each route function is a self-contained
   boundary; pulling them out of `main.py` adds no new behaviour.
2. **Carve structured envelopes second.** `_build_*_envelope`
   helpers are pure functions of their inputs — easy to move and
   easy to test independently.
3. **Carve the chat pipeline last.** It's the densest and the most
   intertwined; do it once everything else is out of the way and
   the surface area to inspect is smaller.
4. **Frontend mirror.** Pull each chat-card screen / state controller
   out of `main.dart` one at a time, behind tests. Don't try to
   carve everything at once.

## Acceptance gates for the split slice

* Full backend pytest still passes (no behaviour change).
* Full flutter analyze + flutter test still pass.
* `compileall vault_ai_backend` succeeds.
* Source guard: no file ≥ 2 000 lines except `main.py` (≤ 600
  after split) and `chat_cards.dart` (UI card definitions are
  fine — they're not coupled).
* New test: a guard that fails if anyone adds a new route inside
  `main.py` after the split lands (route handlers go in `routes/`).

## Tracking

When this work starts, link this file from the slice plan and check
off each carve-out as it lands. Do NOT delete this file until both
halves are below 2 k lines.
