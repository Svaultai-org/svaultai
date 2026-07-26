from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "vault_ai_backend"
FRONTEND = ROOT / "vault_ai_frontend"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_relationship_dashboard_surface_is_removed_without_nav_or_l10n_hooks():
    assert not (FRONTEND / "lib/ui/dashboards/relationships_page.dart").exists()
    assert not (
        FRONTEND / "test/relationships_page_responsive_2026_07_12_test.dart"
    ).exists()

    main = _read(FRONTEND / "lib/main.dart")
    api = _read(FRONTEND / "lib/api_client.dart")
    localizations = _read(FRONTEND / "lib/l10n/app_localizations.dart")

    forbidden = [
        "RelationshipsPage",
        "_DashboardSection.relationships",
        "sidebarRelationships",
        "unlockToSeeRelationships",
        "relationshipsTitle",
    ]
    for token in forbidden:
        assert token not in main
        assert token not in api
        assert token not in localizations

    assert "getRelationshipList" not in api
    assert "/relationships/list" not in api


def test_shared_relationship_graph_and_inheritance_surfaces_remain_present():
    assert (BACKEND / "relationship_builder.py").exists()
    assert (BACKEND / "vault_relationship_graph.py").exists()
    assert (BACKEND / "vault_relationship_worker.py").exists()
    assert (BACKEND / "routes/relationship_routes.py").exists()
    assert (
        BACKEND / "migrations/versions/0012_vault_file_relationships.py"
    ).exists()

    backend_main = _read(BACKEND / "main.py")
    frontend_main = _read(FRONTEND / "lib/main.dart")
    api = _read(FRONTEND / "lib/api_client.dart")

    assert "app.include_router(relationship_router)" in backend_main
    assert '"/relationships/list"' in backend_main
    assert "build_relationships_for_memory_safe" in backend_main
    assert "app.include_router(inheritance_credential_router)" in backend_main
    assert "app.include_router(inheritance_release_router)" in backend_main

    assert "_DashboardSection.inheritance" in frontend_main
    assert "saveInheritanceCredentials" in api
    assert "listInheritances" in api
