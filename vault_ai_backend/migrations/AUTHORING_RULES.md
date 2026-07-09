# Migration authoring rules

Read this before adding or editing a file in `migrations/versions/`.
Past incidents that bricked backend startup all came back to one of
the rules below. The automated guard in `test_migration_safety.py`
enforces them at test time; this file is the human-readable
reference.

## Pre-flight (every change)

Run from `vault_ai_backend/`:

```pwsh
pwsh scripts/check-migrations.ps1
```

…before pushing. The script:

1. `python -m compileall migrations/versions` — catches Python
   SyntaxErrors (broken f-strings, stray braces).
2. `python -m alembic history` — verifies the revision graph loads.
3. `python -m alembic current` — verifies the local schema head
   (requires `VAULTAI_TEST_DATABASE_URL`).
4. `python -m alembic upgrade head` — actually executes the SQL
   against the test DB; catches PostgreSQL-side syntax issues that
   the static checks miss.

The CI pytest suite runs steps 1-2 unconditionally and step 4 when a
test DB is available.

## JSONB defaults: the brace rule

PostgreSQL syntax for an empty-object JSONB default is `'{}'::jsonb`.
Python's string formatting (`f"..."` and `"...".format(...)`) uses
`{...}` as its substitution syntax. The collision is where it hurts.

### Plain (non-formatted) strings — use `'{}'::jsonb`

```python
op.execute("""
    CREATE TABLE foo (
        metadata_jsonb JSONB NOT NULL DEFAULT '{}'::jsonb
    );
""")
```

PostgreSQL receives `DEFAULT '{}'::jsonb`. Correct.

### f-strings — use `'{{}}'::jsonb` (ESCAPED)

```python
op.execute(f"""
    CREATE TABLE bar (
        kind TEXT NOT NULL CHECK (kind IN ({KINDS_SQL})),
        metadata_jsonb JSONB NOT NULL DEFAULT '{{}}'::jsonb
    );
""")
```

The f-string parser resolves `{{` → `{` at parse time, so PostgreSQL
sees `DEFAULT '{}'::jsonb`. Correct.

The same rule applies to `.format(...)`.

### Anti-patterns the guard rejects

```python
# WRONG — f-string with bare {} is a SyntaxError at module load:
op.execute(f"DEFAULT '{}'::jsonb")
#                    ^^ Python: f-string: empty expression not allowed

# WRONG — .format() with bare {} silently consumes the next positional:
op.execute("DEFAULT '{}'::jsonb".format(123))
#  → "DEFAULT '123'::jsonb"  ← SQL syntax error at upgrade time

# WRONG — escaped {{}} in a plain string reaches PostgreSQL as literal braces:
op.execute("DEFAULT '{{}}'::jsonb")
#  → PostgreSQL: invalid input syntax for type json: "{{}}"
```

### Arrays don't need escaping

`'[]'::jsonb` is fine in both contexts. `[` and `]` are not Python
format-spec characters; they survive both f-strings and `.format()`
unchanged.

## Other authoring rules (lower-frequency footguns)

- **No multi-statement `op.execute` blocks** that mix DDL with
  data-only `UPDATE` statements inside the same transaction; split
  them across `op.execute(...)` calls so a partial failure is
  pin-pointable.
- **`DROP COLUMN IF EXISTS` for backout paths** — every upgrade
  should be paired with an idempotent downgrade that uses `IF EXISTS`
  so re-running `downgrade -1` is safe.
- **One head, one base.** Branching the revision graph is not
  supported and the guard test will fail loudly if a new revision
  doesn't extend the existing head.

## What the startup hook does when a migration fails

`main.py::init_db()` wraps `command.upgrade(alembic_cfg, "head")` in
a `try/except` that:

- prints a `[MIGRATION FAILURE]` banner to stderr (visible at a
  glance, unbuffered)
- logs the full traceback via `logger.exception(...)`
- re-raises so uvicorn aborts startup instead of serving traffic
  against a half-migrated schema

Do not soften this behavior. The whole point is that a developer who
boots the app against a broken migration gets a hard stop with a
clear message, not silent service degradation.
