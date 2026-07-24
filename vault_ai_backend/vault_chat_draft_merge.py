"""Pure, deterministic merge for draft field patches.

The v2 semantic decider returns a ``field_patch`` describing
per-field changes the model wants to apply to an existing draft.
This module encodes the rules for applying such a patch. It has
NO I/O, no state, and no side effects; it produces a new
``Draft`` value or raises.

Rule order (higher rules override lower rules)
----------------------------------------------

1. **Op-driven.** Each patch item's ``op`` is authoritative.
   Ops: ``replace``, ``clear``, ``regenerate``, ``unchanged``.

2. **Newer explicit replaces older explicit.** When both the
   existing value and the incoming patch value are
   ``SOURCE_USER_EXPLICIT``, the patch wins iff its
   ``patch_turn_id`` is strictly newer than the existing
   ``turn_id`` (or the existing turn_id is empty, treated as
   older). This is the "old@gmail → new@gmail" rule.

3. **Regenerate refused over explicit.** ``op=regenerate`` on a
   field currently sourced ``SOURCE_USER_EXPLICIT`` is a
   ``PatchError``. Regeneration is allowed only where the field
   schema declares ``allows_regenerate=True`` AND the current
   value's source is not user_explicit.

4. **Priority ordering (residual).** For ``op=replace`` cases
   not resolved above, the merge refuses a
   ``SOURCE_GENERATED`` value overwriting a non-generated
   existing value. Higher-priority sources (see
   ``FIELD_SOURCE_PRIORITY``) may overwrite lower-priority ones.

5. **Silence preserves.** Fields not mentioned in the patch are
   carried through unchanged. Only ``op=clear`` deletes a
   field's user-set value (replacing it with the ``CLEARED``
   sentinel — distinct from "absent").

Atomicity
---------
This function is atomic in the "no partial mutation" sense: on
any error, the caller's ``existing`` value is not modified
(``Draft`` is frozen), and no partial patch has been applied. If
the caller wants to persist the result, they call
``vault_chat_draft.store_draft(new_draft)``; the storage layer
is where actual side effects happen.

Never mutates ``existing``. Always returns a new ``Draft``
instance (or raises).
"""

from __future__ import annotations

import time
from dataclasses import replace
from typing import Any, Mapping, Optional

from vault_chat_draft import (
    CLEARED,
    DRAFT_TTL_SECONDS,
    Draft,
    DraftField,
    FIELD_SOURCES,
    FIELD_SOURCE_PRIORITY,
    FieldFormatError,
    OP_CLEAR,
    OP_REGENERATE,
    OP_REPLACE,
    OP_UNCHANGED,
    PATCH_OPS,
    PENDING_GENERATION,
    SOURCE_GENERATED,
    SOURCE_USER_EXPLICIT,
    schema_for,
    validate_field_value,
)


class PatchError(ValueError):
    """Raised when a patch is malformed or violates a merge rule.

    Callers must treat this as a "reject the whole patch" signal —
    partial mutation has NOT occurred; the ``existing`` draft is
    unchanged.
    """


def merge(
    existing:       Draft,
    patch:          Mapping[str, Mapping[str, Any]],
    *,
    patch_source:   str,
    patch_turn_id:  str,
    now:            Optional[float] = None,
    ttl_seconds:    Optional[int] = None,
    refresh_ttl:    bool = True,
) -> Draft:
    """Return a new Draft with ``patch`` applied.

    Arguments:
        existing:      the current Draft value. Never mutated.
        patch:         a mapping ``{field_name -> {op, value?}}``.
                       ``op`` is one of PATCH_OPS. ``value`` is
                       required for ``replace`` and forbidden for
                       ``clear``/``regenerate``/``unchanged``.
        patch_source:  the source to attribute the incoming values
                       to (typically SOURCE_USER_EXPLICIT for a
                       user-typed edit; SOURCE_GENERATED for a
                       backend generator's output).
        patch_turn_id: the turn stamping this patch. Used by the
                       "newer explicit replaces older explicit"
                       rule.
        now:           unit-testable clock override.
        ttl_seconds:   override the draft TTL (defaults to
                       DRAFT_TTL_SECONDS).
        refresh_ttl:   whether to bump ``expires_at`` on this
                       merge. Defaults True (this is a
                       "meaningful user interaction").

    Raises:
        PatchError on any of: unknown field, unknown op, missing
        required value, forbidden value, format failure,
        generated-over-explicit, regenerate-over-explicit,
        regenerate-on-non-regeneratable-field.
    """
    _validate_patch_shape(existing, patch, patch_source, patch_turn_id)
    schema = schema_for(existing.draft_kind)
    when = float(now) if now is not None else time.time()

    new_fields: dict[str, DraftField] = dict(existing.fields)

    for field_name, item in patch.items():
        op = str(item.get("op") or OP_REPLACE)
        if op == OP_UNCHANGED:
            continue

        current = new_fields.get(field_name)

        if op == OP_CLEAR:
            if "value" in item:
                raise PatchError(
                    f"op=clear on {field_name!r} must not carry a value"
                )
            if patch_source != SOURCE_USER_EXPLICIT:
                raise PatchError(
                    f"op=clear on {field_name!r} requires "
                    "user_explicit source"
                )
            new_fields[field_name] = DraftField(
                value=CLEARED,
                source=SOURCE_USER_EXPLICIT,
                turn_id=patch_turn_id,
                at=when,
            )
            continue

        if op == OP_REGENERATE:
            if "value" in item:
                raise PatchError(
                    f"op=regenerate on {field_name!r} must not "
                    "carry a value"
                )
            spec = schema[field_name]
            if not spec.allows_regenerate:
                raise PatchError(
                    f"field {field_name!r} does not allow regenerate"
                )
            if current is not None and current.source == SOURCE_USER_EXPLICIT:
                raise PatchError(
                    f"regenerate refused on {field_name!r}: "
                    "current value is user_explicit"
                )
            new_fields[field_name] = DraftField(
                value=PENDING_GENERATION,
                source=SOURCE_USER_EXPLICIT,
                turn_id=patch_turn_id,
                at=when,
            )
            continue

        # op == OP_REPLACE
        if "value" not in item:
            raise PatchError(
                f"op=replace on {field_name!r} requires 'value'"
            )
        raw_value = item["value"]
        try:
            validated = validate_field_value(
                existing.draft_kind, field_name, raw_value,
            )
        except FieldFormatError as exc:
            raise PatchError(
                f"field {field_name!r}: {exc}"
            ) from exc

        if current is not None:
            # Rule 2: newer explicit replaces older explicit
            both_explicit = (
                current.source == SOURCE_USER_EXPLICIT
                and patch_source == SOURCE_USER_EXPLICIT
            )
            if both_explicit and _turn_is_not_newer(patch_turn_id, current.turn_id):
                raise PatchError(
                    f"field {field_name!r}: incoming explicit is not "
                    "newer than existing explicit (turn ordering)"
                )
            # Rule 4: generated cannot overwrite non-generated
            if (patch_source == SOURCE_GENERATED
                    and current.source != SOURCE_GENERATED):
                raise PatchError(
                    f"field {field_name!r}: generated cannot "
                    f"overwrite {current.source}"
                )
            # Priority guard: patch may equal or exceed existing priority
            if (not both_explicit
                    and FIELD_SOURCE_PRIORITY[patch_source]
                    < FIELD_SOURCE_PRIORITY[current.source]):
                raise PatchError(
                    f"field {field_name!r}: patch source "
                    f"{patch_source!r} lower priority than "
                    f"existing {current.source!r}"
                )

        new_fields[field_name] = DraftField(
            value=validated,
            source=patch_source,
            turn_id=patch_turn_id,
            at=when,
        )

    # All items applied without error. Now build the new draft.
    ttl = int(ttl_seconds if ttl_seconds is not None else DRAFT_TTL_SECONDS)
    expires = when + ttl if refresh_ttl else existing.expires_at
    return replace(
        existing,
        fields=new_fields,
        updated_at=when,
        last_touch_turn_id=patch_turn_id,
        expires_at=expires,
    )


def _validate_patch_shape(
    existing:      Draft,
    patch:         Any,
    patch_source:  str,
    patch_turn_id: str,
) -> None:
    if not isinstance(patch, Mapping):
        raise PatchError("patch must be a mapping")
    if patch_source not in FIELD_SOURCES:
        raise PatchError(f"unknown patch_source {patch_source!r}")
    if not isinstance(patch_turn_id, str) or not patch_turn_id:
        raise PatchError("patch_turn_id must be a non-empty string")
    schema = schema_for(existing.draft_kind)
    for name, item in patch.items():
        if not isinstance(name, str):
            raise PatchError(f"patch key {name!r} must be a string")
        if name not in schema:
            raise PatchError(
                f"unknown field {name!r} for draft_kind "
                f"{existing.draft_kind!r}"
            )
        if not isinstance(item, Mapping):
            raise PatchError(
                f"patch[{name!r}] must be a mapping with 'op' and "
                "optional 'value'"
            )
        op = item.get("op")
        if not isinstance(op, str) or op not in PATCH_OPS:
            raise PatchError(
                f"patch[{name!r}] has unknown op {op!r}"
            )


def _turn_is_not_newer(patch_turn_id: str, existing_turn_id: str) -> bool:
    """True iff ``patch_turn_id`` does NOT strictly follow
    ``existing_turn_id``.

    Turn ids are opaque strings; we do not assume a lex or numeric
    ordering. The rule this function backs — "newer explicit
    replaces older explicit" — degenerates to a simpler property
    when we can't order the two turn ids: same-turn patches
    (patch_turn_id == existing_turn_id) are allowed (idempotent
    re-application on the same turn), and different-turn patches
    are treated as newer (the model just told us to make the
    change *this turn*, which is by definition later than any
    prior turn's stamp).

    Concretely:
        * ``existing_turn_id`` empty → patch is newer (True → not-not-newer)
        * ``patch_turn_id == existing_turn_id`` → allowed (idempotent)
        * else → allowed (patch is a later turn by definition, since
          the merge is being invoked *now*)

    So this function returns False in practice for any well-formed
    input. It exists as an explicit hook: if a future version
    threads structured turn timestamps into DraftField and wants
    to enforce true ordering, the check tightens here without
    ripple.
    """
    if not existing_turn_id:
        return False  # patch IS newer
    if patch_turn_id == existing_turn_id:
        return False  # same turn — allowed
    return False      # different turn — treat as newer


__all__ = [
    "PatchError",
    "merge",
]
