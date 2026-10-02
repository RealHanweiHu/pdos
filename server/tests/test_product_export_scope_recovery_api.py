"""Real same-line export revocation/recovery and synthetic historical v1 receipts."""

# ruff: noqa: F811
from copy import deepcopy
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db.schema import tables
from app.domain.product_workspace import digest
from app.exports.definition_documents import MIMES, render
from tests.test_definition_exports_api import extracted_text
from tests.test_product_manager_loop_api import command
from tests.test_product_planning_findings_api import post, release_definition, setup_candidate
from tests.test_test_runs_api import PASSWORD, Scope
from tests.test_test_runs_api import client as client
from tests.test_test_runs_api import isolated_test_run_database as isolated_test_run_database


def _scoped_reader(client: TestClient, scope: Scope, base: str) -> tuple[UUID, dict[str, str]]:
    member = uuid4()
    with scope.engine.begin() as c:
        password = c.execute(
            select(tables.users.c.password_hash).where(tables.users.c.id == scope.owner_id)
        ).scalar_one()
        c.execute(
            tables.users.insert().values(
                id=member,
                tenant_id=scope.tenant_id,
                username="export-reader",
                display_name="合成受限产品经理",
                role="project_manager",
                password_hash=password,
                is_active=True,
            )
        )
        c.execute(
            tables.market_space_members.insert().values(
                tenant_id=scope.tenant_id,
                market_space_id=UUID(base.rsplit("/", 1)[1]),
                user_id=member,
                access="viewer",
                added_by_user_id=scope.owner_id,
            )
        )
    login = client.post(
        "/api/auth/login",
        json={"tenant_slug": "beepump", "username": "export-reader", "password": PASSWORD},
    )
    assert login.status_code == 200, login.text
    return member, {"Authorization": "Bearer " + login.json()["access_token"]}


def _line_access(
    client: TestClient,
    base: str,
    headers: dict[str, str],
    line_id: str,
    member: UUID,
    access: str | None,
) -> None:
    response = client.get(base + "/products", headers=headers)
    assert response.status_code == 200, response.text
    line = next(node for node in response.json()["nodes"] if node["id"] == line_id)
    post(
        client,
        base,
        headers,
        f"/products/{line_id}/members",
        {**command(line), "user_id": str(member), "access": access},
    )


def _stored(scope: Scope, identity: str) -> dict[str, Any]:
    with scope.engine.connect() as c:
        return dict(
            c.execute(
                select(tables.definition_exports).where(
                    tables.definition_exports.c.id == UUID(identity)
                )
            )
            .mappings()
            .one()
        )


def _released_derived(
    client: TestClient,
    scope: Scope,
    base: str,
    headers: dict[str, str],
    parent: dict[str, Any],
) -> dict[str, Any]:
    definition = post(
        client,
        base,
        headers,
        f"/definitions/{parent['id']}/derive",
        {
            **command(parent),
            "code": "EXPORT-SCOPED-DERIVED",
            "name": "合成派生导出产品",
            "reason": "合成来源范围核对",
        },
        201,
    )
    content = deepcopy(definition["content"])
    content["reviewers"] = {
        discipline: str(scope.owner_id) for discipline in ["id", "md", "ee", "fw", "dqe"]
    }
    content["items"][0].update(state="confirmed", owner_user_id=str(scope.owner_id))
    definition = post(
        client,
        base,
        headers,
        f"/definitions/{definition['id']}/changes",
        {**command(definition), "content": content, "reason": "合成具名确认，非真实协审"},
    )
    return release_definition(client, base, headers, definition)


@pytest.mark.parametrize("derived", [False, True])
def test_same_line_export_revocation_denies_reads_and_recovers_original_receipt(
    client: TestClient,
    isolated_test_run_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    derived: bool,
) -> None:
    scope = Scope(client, isolated_test_run_database)
    try:
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
        definition = parent
        if derived:
            definition = _released_derived(client, scope, base, headers, parent)
        member, own = _scoped_reader(client, scope, base)
        line = definition["product_line_id"]
        # Approved APIs keep the strategy and derived parent on this same product line.
        assert line == parent["product_line_id"]
        _line_access(client, base, headers, line, member, "viewer")
        selected = dict(definition_id=definition["id"], format="docx", reason="合成内部范围核对")
        preview = post(client, base, own, "/definition-export-preview", selected)
        assert preview["source"]["lineage"]["strategy"]["reference"] == definition["strategy_ref"]
        if derived:
            assert (
                preview["source"]["lineage"]["parent_definition"]["reference"]["ref_id"]
                == parent["id"]
            )
        request = {**selected, "request_id": str(uuid4()), "expected_digest": preview["digest"]}
        saved = post(client, base, own, "/definition-export-save", request)
        url = base + f"/definition-exports/{saved['id']}/download"
        original = client.get(url, headers=own)
        assert original.status_code == 200, original.text
        assert sha256(original.content).hexdigest() == saved["content_digest"]
        frozen = _stored(scope, saved["id"])

        _line_access(client, base, headers, line, member, None)
        for path, body in [
            ("/definition-export-preview", selected),
            ("/definition-export-save", request),
            ("/definition-export-history", {"definition_id": definition["id"]}),
        ]:
            rejected = client.post(base + path, headers=own, json=body)
            assert rejected.status_code == 403, rejected.text
            assert definition["title"] not in rejected.text and saved["id"] not in rejected.text
        denied = client.get(url, headers=own)
        assert denied.status_code == 403, denied.text
        assert "content-disposition" not in denied.headers
        assert saved["filename"] not in denied.text
        options = post(client, base, own, "/definition-export-options", {})
        assert options["items"] == []
        assert _stored(scope, saved["id"]) == frozen

        _line_access(client, base, headers, line, member, "viewer")
        restored = post(client, base, own, "/definition-export-preview", selected)
        assert restored == preview
        assert post(client, base, own, "/definition-export-save", request) == saved
        download = client.get(url, headers=own)
        assert download.status_code == 200 and download.content == original.content
        history = post(
            client, base, own, "/definition-export-history", {"definition_id": definition["id"]}
        )
        assert history["items"] == [{**saved, "sources_current": True}]
        assert _stored(scope, saved["id"]) == frozen
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


def _legacy_source(current: dict[str, Any]) -> dict[str, Any]:
    """Exact pre-lineage v1 projection fields, as retained in the committed source."""
    definition = {
        key: deepcopy(current["definition"][key])
        for key in (
            "id",
            "title",
            "product_id",
            "series_id",
            "revision_number",
            "version",
            "state",
            "review_round",
            "review_digest",
            "approval",
            "published_at",
            "content",
        )
    }
    body = {
        "definition": definition,
        **{
            key: deepcopy(current[key])
            for key in (
                "product",
                "status_label",
                "reviews",
                "releases",
                "current_release",
                "sources",
                "warnings",
                "template_version",
                "audience",
            )
        },
        "source_policy": "definition-export.v1",
    }
    return {**body, "digest": digest(body)}


def test_real_v1_projection_receipt_replays_original_bytes_without_proving_v2_sources(
    client: TestClient,
    isolated_test_run_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = Scope(client, isolated_test_run_database)
    try:
        base, headers, definition, calls = setup_candidate(
            client,
            scope,
            tmp_path,
            monkeypatch,
            "product_definition",
            revision=True,
            seed_only=True,
        )
        assert calls == []
        selected = dict(definition_id=definition["id"], format="docx", reason="合成留存旧版原件")
        current = post(client, base, headers, "/definition-export-preview", selected)
        snapshot = _legacy_source(current["source"])
        assert "lineage" not in snapshot
        assert "strategy_id" not in snapshot["definition"]
        assert "strategy_ref" not in snapshot["definition"]
        assert snapshot["digest"] != current["source"]["digest"]
        old_preview = {
            "source": snapshot,
            "format": selected["format"],
            "reason": selected["reason"],
            "template_version": snapshot["template_version"],
        }
        request = {
            **selected,
            "request_id": str(uuid4()),
            "expected_digest": digest(old_preview),
        }
        identity, now = uuid4(), datetime.now(UTC)
        receipt = {
            "编号": str(identity),
            "生成时点": now.isoformat(),
            "记录人": str(scope.owner_id),
            "来源摘要": snapshot["digest"],
            "用途": selected["reason"],
        }
        content = render(snapshot, "docx", receipt)
        text = extracted_text(content, "docx")
        assert snapshot["digest"] in text and str(identity) in text
        assert "所消费的锁定策略版本" not in text
        assert "锁定业务来源的当前状态" not in text
        filename = f"definition-{definition['id']}-v{definition['version']}-{identity}.docx"
        # Seed an actual old-shape historical receipt, through the unchanged INSERT guard.
        # The modern save API intentionally cannot create a new file from this old digest.
        with scope.engine.begin() as c:
            c.execute(
                tables.definition_exports.insert().values(
                    id=identity,
                    tenant_id=scope.tenant_id,
                    market_space_id=UUID(base.rsplit("/", 1)[1]),
                    definition_id=UUID(definition["id"]),
                    format="docx",
                    template_version="internal-definition.v1",
                    filename=filename,
                    mime_type=MIMES["docx"],
                    byte_size=len(content),
                    content=content,
                    content_digest=sha256(content).hexdigest(),
                    snapshot=snapshot,
                    source_digest=snapshot["digest"],
                    preview_digest=request["expected_digest"],
                    reason=selected["reason"],
                    actor_user_id=scope.owner_id,
                    request_id=UUID(request["request_id"]),
                    request_digest=digest({"space": base.rsplit("/", 1)[1], "command": request}),
                    created_at=now,
                )
            )
        frozen = _stored(scope, str(identity))
        saved = post(client, base, headers, "/definition-export-save", request)
        assert saved["id"] == str(identity) and saved["source_digest"] == snapshot["digest"]
        assert saved["content_digest"] == sha256(content).hexdigest()
        assert saved["template_version"] == "internal-definition.v1"
        url = base + f"/definition-exports/{identity}/download"
        download = client.get(url, headers=headers)
        assert download.status_code == 200 and download.content == content
        assert download.headers["content-type"] == MIMES["docx"]
        assert filename in download.headers["content-disposition"]
        assert download.headers["x-content-type-options"] == "nosniff"
        assert "no-store" in download.headers["cache-control"]
        history = post(
            client, base, headers, "/definition-export-history", {"definition_id": definition["id"]}
        )
        assert history["items"] == [{**saved, "sources_current": False}]
        rejected = post(
            client,
            base,
            headers,
            "/definition-export-save",
            {**request, "request_id": str(uuid4())},
            409,
        )
        assert "重新预览" in rejected["detail"]["message"]
        modern = post(
            client,
            base,
            headers,
            "/definition-export-save",
            {**request, "request_id": str(uuid4()), "expected_digest": current["digest"]},
        )
        assert modern["id"] != saved["id"]
        assert modern["source_digest"] == current["source"]["digest"]
        assert _stored(scope, modern["id"])["snapshot"]["source_policy"] == "definition-export.v2"

        post(
            client,
            base,
            headers,
            f"/definitions/{definition['id']}/actions",
            {
                **command(definition),
                "action": "withdraw",
                "reason": "合成撤回后的旧版原件核对",
                "expected_release_id": definition["current_release"]["id"],
            },
        )
        assert post(client, base, headers, "/definition-export-save", request) == saved
        historical = client.get(url, headers=headers)
        assert historical.status_code == 200 and historical.content == content
        assert _stored(scope, str(identity)) == frozen
        with scope.engine.connect() as c:
            assert (
                c.execute(select(func.count()).select_from(tables.definition_exports)).scalar_one()
                == 2
            )
            assert (
                c.execute(select(func.count()).select_from(tables.model_invocations)).scalar_one()
                == 0
            )
    finally:
        scope.dispose()
