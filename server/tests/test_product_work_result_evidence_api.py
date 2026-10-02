"""PostgreSQL/API result evidence regression candidates; synthetic inputs, not executed here."""

from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Literal, cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.auth.passwords import PasswordService
from app.db.schema import tables
from app.domain.evidence import EvidenceService
from tests.test_product_manager_loop_api import command
from tests.test_product_work_preparation_api import space
from tests.test_test_runs_api import PASSWORD, Scope, bearer_headers
from tests.test_test_runs_api import client as client
from tests.test_test_runs_api import isolated_test_run_database as isolated_test_run_database

Kind = Literal["research", "work"]


def post(
    client: TestClient,
    base: str,
    headers: dict[str, str],
    path: str,
    body: dict[str, Any],
    expected: int = 200,
) -> dict[str, Any]:
    response = client.post(base + path, headers=headers, json=body)
    assert response.status_code == expected, (path, response.text)
    return cast(dict[str, Any], response.json())


def started(
    client: TestClient,
    base: str,
    headers: dict[str, str],
    owner: UUID,
    kind: Kind,
) -> dict[str, Any]:
    common = dict(request_id=str(uuid4()), owner_user_id=str(owner))
    if kind == "research":
        row = post(
            client,
            base,
            headers,
            "/research",
            {
                **common,
                "question": "合成正文验证研究",
                "user_groups": ["合成用户"],
                "regions": ["TEST"],
                "time_scope": "本轮",
                "method": "核对原始快照",
                "expected_decision": "是否补证",
                "stop_conditions": ["区分已知与未决"],
            },
            201,
        )
        return post(
            client,
            base,
            headers,
            f"/research/{row['id']}/start",
            {
                **command(row),
                "research_task_id": row["id"],
            },
        )
    row = post(
        client,
        base,
        headers,
        "/work-items",
        {
            **common,
            "title": "合成资料补证",
            "action_type": "evidence_collection",
            "expected_output": "可回查原文",
            "completion_criteria": "核对固定引用",
        },
        201,
    )
    return post(
        client,
        base,
        headers,
        f"/work-items/{row['id']}/actions",
        {
            **command(row),
            "action": "start",
            "note": "开始合成补证",
        },
    )


def submission(row: dict[str, Any], kind: Kind, ref: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if kind == "research":
        return f"/research/{row['id']}/conclude", {
            **command(row),
            "research_task_id": row["id"],
            "conclusion": "合成来源核对结论",
            "findings": ["原文支持此项合成记录"],
            "unresolved": ["不代表真实业务"],
            "source_refs": [ref],
        }
    return f"/work-items/{row['id']}/actions", {
        **command(row),
        "action": "submit",
        "note": "合成输出可回查",
        "evidence": [ref],
    }


def state(scope: Scope, identity: UUID, kind: Kind) -> tuple[dict[str, Any], int, int]:
    table = tables.research_tasks if kind == "research" else tables.scoped_work_items
    with scope.engine.connect() as c:
        row = dict(c.execute(select(table).where(table.c.id == identity)).mappings().one())
        audits = c.execute(
            select(func.count())
            .select_from(tables.audit_log)
            .where(
                tables.audit_log.c.tenant_id == scope.tenant_id,
                tables.audit_log.c.entity_id == identity,
            )
        ).scalar_one()
        events = c.execute(
            select(func.count())
            .select_from(tables.events)
            .where(
                tables.events.c.tenant_id == scope.tenant_id,
            )
        ).scalar_one()
    return row, audits, events


def evidence(scope: Scope, variant: Literal["body", "metadata", "blank"]) -> dict[str, Any]:
    service = EvidenceService(scope.engine)
    source = service.create_source(
        tenant_id=scope.tenant_id,
        actor_user_id=scope.owner_id,
        name=f"合成来源-{uuid4()}",
        source_type="file",
        allowed_use="internal_analysis",
        collection_frequency="on_demand",
        retention_policy="standard",
        trust_tier="unknown",
    )
    if variant == "body":
        snapshot = service.capture(
            tenant_id=scope.tenant_id,
            actor_user_id=scope.owner_id,
            source_id=source.id,
            content=f"合成可回查正文-{uuid4()}",
        )
        return dict(
            tenant_id=str(scope.tenant_id),
            kind="evidence_snapshot",
            ref_id=str(snapshot.id),
            as_of=snapshot.captured_at.isoformat(),
            digest=snapshot.content_digest,
        )
    # New independent immutable rows only. Missing-body legacy metadata and whitespace
    # content are legal schema states; byte_size > 0 prevents an empty-body stored row.
    body = f"metadata-only-{uuid4()}" if variant == "metadata" else " \n\t "
    content_digest = sha256(body.encode()).hexdigest()
    identity, captured = uuid4(), datetime.now(UTC)
    with scope.engine.begin() as c:
        if variant == "blank":
            c.execute(
                tables.evidence_contents.insert().values(
                    tenant_id=scope.tenant_id,
                    content_digest=content_digest,
                    body=body,
                    byte_size=len(body.encode()),
                )
            )
        c.execute(
            tables.evidence_snapshots.insert().values(
                id=identity,
                tenant_id=scope.tenant_id,
                source_id=source.id,
                captured_at=captured,
                captured_by_user_id=scope.owner_id,
                content_digest=content_digest,
                content_ref=f"evidence-content:{content_digest}",
                trust_tier="unknown",
                taint="untrusted_external",
                byte_size=len(body.encode()),
                source_version="synthetic-legacy",
            )
        )
    return dict(
        tenant_id=str(scope.tenant_id),
        kind="evidence_snapshot",
        ref_id=str(identity),
        as_of=captured.isoformat(),
        digest=content_digest,
    )


@pytest.mark.parametrize("kind", ["research", "work"])
@pytest.mark.parametrize("variant", ["metadata", "blank"])
def test_missing_or_blank_body_rejected_without_result_audit_or_event(
    client: TestClient,
    isolated_test_run_database: str,
    kind: Kind,
    variant: Literal["metadata", "blank"],
) -> None:
    scope = Scope(client, isolated_test_run_database)
    try:
        headers = bearer_headers(client)
        base = f"/api/product-work/spaces/{space(client, headers)}"
        row = started(client, base, headers, scope.owner_id, kind)
        ref = evidence(scope, variant)
        before = state(scope, UUID(row["id"]), kind)
        path, body = submission(row, kind, ref)
        rejected = post(client, base, headers, path, body, 409)
        assert "正文" in str(rejected)
        assert state(scope, UUID(row["id"]), kind) == before
    finally:
        scope.dispose()


@pytest.mark.parametrize("kind", ["research", "work"])
def test_readable_body_result_and_original_request_are_atomic_and_idempotent(
    client: TestClient,
    isolated_test_run_database: str,
    kind: Kind,
) -> None:
    scope = Scope(client, isolated_test_run_database)
    try:
        headers = bearer_headers(client)
        sid = space(client, headers)
        base = f"/api/product-work/spaces/{sid}"
        row = started(client, base, headers, scope.owner_id, kind)
        ref = evidence(scope, "body")
        path, body = submission(row, kind, ref)
        done = post(client, base, headers, path, body)
        assert done["state"] == "completed" and done["version"] == row["version"] + 1
        assert done["sources" if kind == "research" else "evidence"][0]["ref_id"] == ref["ref_id"]
        other = f"/api/product-work/spaces/{space(client, headers)}"
        before = state(scope, UUID(row["id"]), kind)
        assert post(client, base, headers, path, body) == done
        assert state(scope, UUID(row["id"]), kind) == before
        post(client, other, headers, path, body, 403)
        assert state(scope, UUID(row["id"]), kind) == before
    finally:
        scope.dispose()


@pytest.mark.parametrize("kind", ["research", "work"])
def test_original_completion_receipt_remains_inaccessible_after_member_revocation(
    client: TestClient,
    isolated_test_run_database: str,
    kind: Kind,
) -> None:
    scope = Scope(client, isolated_test_run_database)
    try:
        owner_headers = bearer_headers(client)
        sid = space(client, owner_headers)
        base = f"/api/product-work/spaces/{sid}"
        username = f"result-{uuid4().hex[:12]}"
        member = scope._insert(
            tables.users,
            dict(
                username=username,
                display_name="合成研究员",
                role="engineer",
                password_hash=PasswordService().hash(PASSWORD),
                is_active=True,
            ),
        )
        response = client.put(
            base + f"/members/{member}", headers=owner_headers, json={"access": "contributor"}
        )
        assert response.status_code == 204, response.text
        login = client.post(
            "/api/auth/login",
            json={"tenant_slug": "beepump", "username": username, "password": PASSWORD},
        )
        assert login.status_code == 200, login.text
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        row = started(client, base, headers, member, kind)
        path, body = submission(row, kind, evidence(scope, "body"))
        post(client, base, headers, path, body)
        response = client.put(
            base + f"/members/{member}", headers=owner_headers, json={"access": None}
        )
        assert response.status_code == 204, response.text
        before = state(scope, UUID(row["id"]), kind)
        post(client, base, headers, path, body, 403)
        assert state(scope, UUID(row["id"]), kind) == before
    finally:
        scope.dispose()
