"""Actual inherited-export SQL guards and reversible function migration; synthetic data."""

# ruff: noqa: F811
from copy import deepcopy
from importlib import import_module
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, func, select, text
from sqlalchemy.exc import DBAPIError

from app.db.schema import tables
from app.domain.product_workspace import digest
from tests.migration_fixtures import rollback_migration_operations
from tests.test_product_export_scope_recovery_api import _released_derived, _stored
from tests.test_product_planning_findings_api import post, setup_candidate
from tests.test_test_runs_api import Scope
from tests.test_test_runs_api import client as client
from tests.test_test_runs_api import isolated_test_run_database as isolated_test_run_database

GUARD_ERROR = "Definition export requires actual version, state and explicit internal template"


def _receipt(
    client: TestClient, scope: Scope, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[dict[str, Any], dict[str, Any]]:
    base, headers, parent, calls = setup_candidate(
        client,
        scope,
        tmp_path,
        monkeypatch,
        "product_definition",
        revision=True,
        seed_only=True,
    )
    assert calls == []
    child = _released_derived(client, scope, base, headers, parent)
    selection = dict(definition_id=child["id"], format="docx", reason="合成派生数据库守卫核对")
    preview = post(client, base, headers, "/definition-export-preview", selection)
    saved = post(
        client,
        base,
        headers,
        "/definition-export-save",
        {**selection, "request_id": str(uuid4()), "expected_digest": preview["digest"]},
    )
    original = _stored(scope, saved["id"])
    with scope.engine.connect() as c:
        raw = dict(
            c.execute(
                select(tables.product_definitions.c.content).where(
                    tables.product_definitions.c.tenant_id == scope.tenant_id,
                    tables.product_definitions.c.id == UUID(child["id"]),
                )
            ).scalar_one()
        )
    assert "scenarios" not in raw and original["snapshot"]["definition"]["content"] != raw
    return original, raw


def _copy_receipt(original: dict[str, Any]) -> dict[str, Any]:
    return {**deepcopy(original), "id": uuid4(), "request_id": uuid4()}


def _function_state(c: Connection) -> tuple[Any, ...]:
    return tuple(
        c.execute(
            text(
                "SELECT pg_get_functiondef(p.oid),p.proacl,p.proowner,p.prosecdef,p.proconfig,"
                "obj_description(p.oid,'pg_proc') FROM pg_proc p "
                "WHERE p.oid=CAST(:name AS regprocedure)"
            ),
            {"name": "cehub_product.guard_definition_export()"},
        ).one()
    )


def test_inherited_export_sql_rejects_sparse_forged_content_and_original_guard_mismatches(
    client: TestClient,
    isolated_test_run_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = Scope(client, isolated_test_run_database)
    try:
        original, raw = _receipt(client, scope, tmp_path, monkeypatch)
        cases = (
            "sparse_content",
            "inherited_content",
            "local_content",
            "id",
            "version",
            "state",
            "approval",
            "template",
            "audience",
            "source_digest",
        )
        with scope.engine.begin() as c:
            for case in cases:
                incoming = _copy_receipt(original)
                snapshot = incoming["snapshot"]
                definition = snapshot["definition"]
                if case == "sparse_content":
                    definition["content"] = deepcopy(raw)
                elif case == "inherited_content":
                    definition["content"]["scenarios"] = ["伪造继承章节"]
                elif case == "local_content":
                    definition["content"]["items"][0]["target_value"] = "999"
                elif case == "id":
                    definition["id"] = str(uuid4())
                elif case == "version":
                    definition["version"] += 1
                elif case == "state":
                    definition["state"] = "draft"
                elif case == "approval":
                    definition["approval"] = {"reason": "伪造批准"}
                elif case == "template":
                    snapshot["template_version"] = "internal-definition.v2"
                elif case == "audience":
                    snapshot["audience"] = "external"
                # Matching claimed hashes cannot turn an altered source into actual content.
                snapshot["digest"] = digest(
                    {key: value for key, value in snapshot.items() if key != "digest"}
                )
                incoming["source_digest"] = snapshot["digest"]
                if case == "source_digest":
                    incoming["source_digest"] = "0" * 64
                with pytest.raises(DBAPIError, match=GUARD_ERROR), c.begin_nested():
                    c.execute(tables.definition_exports.insert(), incoming)
            assert (
                c.execute(select(func.count()).select_from(tables.definition_exports)).scalar_one()
                == 1
            )
        assert _stored(scope, str(original["id"])) == original
    finally:
        scope.dispose()


def test_export_content_guard_roundtrip_preserves_acl_and_append_only_history(
    client: TestClient,
    isolated_test_run_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = Scope(client, isolated_test_run_database)
    try:
        original, _ = _receipt(client, scope, tmp_path, monkeypatch)
        migration = import_module("migrations.versions.0414_definition_export_inheritance")
        with rollback_migration_operations(scope.engine) as c:
            current = _function_state(c)
            assert migration.NEW_CONTENT in current[0] and migration.OLD_CONTENT not in current[0]
            with pytest.raises(RuntimeError, match="content guard is unavailable"):
                migration.upgrade()
            assert _function_state(c) == current
            migration.downgrade()
            previous = _function_state(c)
            assert previous[0] == current[0].replace(migration.NEW_CONTENT, migration.OLD_CONTENT)
            assert previous[1:] == current[1:]
            with pytest.raises(RuntimeError, match="content guard is unavailable"):
                migration.downgrade()
            with pytest.raises(DBAPIError, match=GUARD_ERROR), c.begin_nested():
                c.execute(tables.definition_exports.insert(), _copy_receipt(original))
            migration.upgrade()
            assert _function_state(c) == current
            c.execute(tables.definition_exports.insert(), _copy_receipt(original))

            for action in (
                tables.definition_exports.update()
                .where(tables.definition_exports.c.id == original["id"])
                .values(reason="不可覆盖原件"),
                tables.definition_exports.delete().where(
                    tables.definition_exports.c.id == original["id"]
                ),
            ):
                with pytest.raises(DBAPIError, match="history is append-only"), c.begin_nested():
                    c.execute(action)
            with (
                pytest.raises(DBAPIError, match="Retain definition export history"),
                c.begin_nested(),
            ):
                import_module("migrations.versions.0358_definition_exports").downgrade()
            with (
                pytest.raises(DBAPIError, match="Cannot remove definition inheritance history"),
                c.begin_nested(),
            ):
                import_module("migrations.versions.0402_definition_inheritance").downgrade()
            assert _function_state(c) == current
            assert not c.execute(
                text(
                    "SELECT has_table_privilege('pdos_agent','cehub_product.definition_exports',"
                    "'INSERT,UPDATE,DELETE')"
                )
            ).scalar_one()
        assert _stored(scope, str(original["id"])) == original
        with scope.engine.connect() as c:
            assert (
                c.execute(select(func.count()).select_from(tables.definition_exports)).scalar_one()
                == 1
            )
            assert (
                c.execute(select(func.count()).select_from(tables.model_invocations)).scalar_one()
                == 0
            )
    finally:
        scope.dispose()
