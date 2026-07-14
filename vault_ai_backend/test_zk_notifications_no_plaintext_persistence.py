"""Notification producers must never persist readable title/body/
metadata for a ZK/adopted vault.

Uses `mock.patch` to make `is_vault_zk_adopted` return True and a
psycopg2 cursor spy to inspect the exact SQL a notification INSERT
emits. Fails if the SQL writes a user-derived title / body /
metadata value into the plaintext columns.
"""

from __future__ import annotations

from unittest import mock


class _CursorSpy:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql: str, params: tuple = ()) -> None:
        self.calls.append((sql, params))

    def close(self) -> None:
        pass


class _ConnSpy:
    def __init__(self) -> None:
        self.cur = _CursorSpy()
        self.commits = 0

    def cursor(self, *args, **kwargs):
        return self.cur

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        pass


def test_main_create_notification_zk_vault_writes_nulls() -> None:
    """`main._create_notification` for a ZK vault must write NULL
    into title / body / metadata columns."""
    import main
    conn_spy = _ConnSpy()
    with mock.patch("vault_core.is_vault_zk_adopted",
                    return_value=True), \
         mock.patch.object(main, "get_db", return_value=conn_spy):
        main._create_notification(
            vault_id="00000000-0000-0000-0000-000000000001",
            kind="storage_reminder",
            title="You are almost out of storage.",
            body="Only 12 MB left.",
            metadata={"used": 988, "total": 1000},
        )

    assert len(conn_spy.cur.calls) == 1, (
        "expected exactly one INSERT"
    )
    sql, params = conn_spy.cur.calls[0]
    folded = " ".join(sql.split())
    assert "NULL, NULL, NULL" in folded, (
        "ZK notification insert MUST write NULL for title/body/"
        f"metadata columns. Got SQL: {folded}"
    )
    # Params must contain ONLY vault_id + kind — no user-derived text.
    assert len(params) == 2, (
        "ZK notification insert must not carry user-text params. "
        f"Got: {params}"
    )
    assert params[0] == "00000000-0000-0000-0000-000000000001"
    assert params[1] == "storage_reminder"
    assert "You are almost" not in " ".join(str(p) for p in params)
    assert "Only 12 MB" not in " ".join(str(p) for p in params)


def test_device_routes_notify_zk_vault_writes_nulls() -> None:
    """`routes.device_routes._notify` for a ZK vault must write NULL
    into title / body / metadata columns."""
    from routes import device_routes
    conn_spy = _ConnSpy()
    with mock.patch("vault_core.is_vault_zk_adopted",
                    return_value=True), \
         mock.patch.object(device_routes, "get_db",
                           return_value=conn_spy):
        device_routes._notify(
            vault_id="00000000-0000-0000-0000-000000000002",
            kind="device_pending",
            title="New device requesting trust: Chrome 138 on Windows",
            body="Approve or deny from an existing trusted device.",
            metadata={"user_agent_brand": "Chrome/138"},
        )

    assert len(conn_spy.cur.calls) == 1
    sql, params = conn_spy.cur.calls[0]
    folded = " ".join(sql.split())
    assert "NULL, NULL, NULL" in folded, (
        "ZK device notification insert MUST write NULL for title/"
        f"body/metadata columns. Got SQL: {folded}"
    )
    assert len(params) == 2
    assert "Chrome" not in " ".join(str(p) for p in params)


def test_notifications_legacy_vault_still_writes_plaintext() -> None:
    """Non-adopted (legacy) vaults must keep the plaintext write
    path for backward compatibility. This confirms the ZK branch
    doesn't short-circuit legacy behavior."""
    import main
    conn_spy = _ConnSpy()
    with mock.patch("vault_core.is_vault_zk_adopted",
                    return_value=False), \
         mock.patch.object(main, "get_db", return_value=conn_spy):
        main._create_notification(
            vault_id="00000000-0000-0000-0000-000000000003",
            kind="storage_reminder",
            title="You have 42 MB free.",
            body=".",
            metadata={"used": 958},
        )
    assert len(conn_spy.cur.calls) == 1
    sql, params = conn_spy.cur.calls[0]
    folded = " ".join(sql.split())
    assert "NULL, NULL, NULL" not in folded, (
        "Legacy vault insert must still carry the plaintext columns."
    )
    assert any("You have 42 MB free." in str(p) for p in params)
