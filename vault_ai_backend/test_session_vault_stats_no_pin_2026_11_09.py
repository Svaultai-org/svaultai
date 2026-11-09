"""Trusted sessions can read aggregate storage counts without a PIN."""

from __future__ import annotations

import asyncio
import inspect

import main
from device_gate import verify_trusted_device


def test_session_stats_route_requires_trusted_device_and_no_pin():
    routes = [
        route for route in main.app.routes
        if getattr(route, "path", None) == "/vault-stats/session"
    ]
    assert len(routes) == 1
    route = routes[0]
    assert route.methods == {"GET"}
    assert verify_trusted_device in {
        dependency.call for dependency in route.dependant.dependencies
    }
    assert "pin" not in inspect.signature(main.session_vault_stats_endpoint).parameters


def test_session_stats_use_authenticated_vault_without_pin(monkeypatch):
    calls = []

    def fake_collect(vault_id, *, require_zk=False):
        calls.append((vault_id, require_zk))
        return {"file_count": 2}

    monkeypatch.setattr(main, "_collect_vault_stats", fake_collect)
    result = asyncio.run(main.session_vault_stats_endpoint(
        principal={"vault_id": "synthetic-legacy-vault"},
    ))
    assert result == {"file_count": 2}
    assert calls == [("synthetic-legacy-vault", False)]
