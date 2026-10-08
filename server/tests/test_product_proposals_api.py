"""Real isolated transactions: lightweight review is distinct from specification freeze."""

# ruff: noqa: F811
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
from uuid import UUID, uuid4

import pytest
from docx import Document
from fastapi.testclient import TestClient
from pptx import Presentation
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.ai.gateway import GatewayResult
from app.api.ai import get_application_gateway
from app.contracts.product_proposals import ProposalAssessment
from app.db.schema import tables
from app.domain.documents import DocumentExtractionError, extract_document_details
from app.main import app
from app.storage.documents import get_document_object_store
from tests.migration_fixtures import rollback_migration_operations
from tests.test_product_source_files_api import Store
from tests.test_product_work_preparation_api import space
from tests.test_test_runs_api import PASSWORD, Scope, bearer_headers
from tests.test_test_runs_api import client as client
from tests.test_test_runs_api import isolated_test_run_database as isolated_test_run_database


def proposal_line(client, headers, sid):
    base = f"/api/product-work/spaces/{sid}"
    rows = client.get(base + "/products", headers=headers).json()["nodes"]
    existing = next((r for r in rows if r["level"] == "line"), None)
    if existing:
        return existing["id"]
    owner = client.get(base, headers=headers).json()["current_user_id"]
    response = client.post(
        base + "/products",
        headers=headers,
        json=dict(
            request_id=str(uuid4()),
            code=f"cat-{uuid4().hex}",
            name="自行车充气泵",
            level="line",
            owner_user_id=owner,
        ),
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def create(client: TestClient, headers: dict, sid: str, kind: str = "odm") -> dict:
    response = client.post(
        f"/api/product-work/spaces/{sid}/proposals",
        headers=headers,
        json=dict(
            request_id=str(uuid4()),
            title="合成立项提案",
            entry_kind=kind,
            product_line_id=proposal_line(client, headers, sid),
            brief="客人希望续航30分钟，充气泵要方便骑行携带。",
        ),
    )
    assert response.status_code == 201, response.text
    return response.json()


def command(row: dict) -> dict:
    return dict(
        expected_version=row["version"],
        payload_digest=row["payload_digest"],
        idempotency_key=str(uuid4()),
    )


@pytest.mark.parametrize("kind", ["odm", "new_product", "iteration"])
def test_three_entries_unknowns_can_enter_named_review_without_freeze(
    client: TestClient,
    isolated_test_run_database: str,
    kind: str,
) -> None:
    scope = Scope(client, isolated_test_run_database)
    headers = bearer_headers(client)
    sid = space(client, headers)
    row = create(client, headers, sid, kind)
    path = f"/api/product-work/spaces/{sid}/proposals/{row['id']}"
    submitted = client.post(
        path + "/submit",
        headers=headers,
        json={**command(row), "reviewer_user_id": str(scope.owner_id)},
    )
    assert submitted.status_code == 200, submitted.text
    row = submitted.json()
    assert row["state"] == "in_review"
    assert all(s["state"] == "unknown" for s in row["document"]["specifications"])
    blocked = client.post(
        path + "/decide",
        headers=headers,
        json={**command(row), "outcome": "approved", "rationale": "小额投入验证需求"},
    )
    assert blocked.status_code == 409
    body = {
        **command(row),
        "outcome": "approved",
        "rationale": "小额投入验证需求",
        "accepted_unknowns": "性能、认证与BOM留到项目规格冻结前由工程和品质确认",
    }
    decided = client.post(path + "/decide", headers=headers, json=body)
    assert decided.status_code == 200, decided.text
    assert client.post(path + "/decide", headers=headers, json=body).status_code == 200
    detail = client.get(path, headers=headers).json()
    assert len(detail["decisions"]) == 1
    assert detail["decisions"][0]["actor_user_id"] == str(scope.owner_id)
    assert detail["decisions"][0]["snapshot"]["specifications_frozen"] is False
    assert not detail["can_edit"] and not detail["can_decide"]
    with scope.engine.connect() as c:
        assert c.execute(select(tables.definition_releases.c.id)).first() is None


def test_document_versions_idempotency_scope_and_immutable_history(
    client: TestClient,
    isolated_test_run_database: str,
) -> None:
    scope = Scope(client, isolated_test_run_database)
    headers = bearer_headers(client)
    sid, other = space(client, headers), space(client, headers)
    row = create(client, headers, sid)
    path = f"/api/product-work/spaces/{sid}/proposals/{row['id']}"
    document = deepcopy(row["document"])
    document["specifications"][0].update(value="骑行者", state="confirmed", source_ids=["brief"])
    body = {**command(row), "document": document}
    edited = client.post(path + "/changes", headers=headers, json=body)
    assert edited.status_code == 200, edited.text
    assert client.post(path + "/changes", headers=headers, json=body).json()["version"] == 2
    assert (
        client.post(
            path + "/changes",
            headers=headers,
            json={**body, "document": {**document, "narrative": "改变同一请求"}},
        ).status_code
        == 409
    )
    assert (
        client.get(
            f"/api/product-work/spaces/{other}/proposals/{row['id']}", headers=headers
        ).status_code
        == 403
    )
    detail = client.get(path, headers=headers).json()
    assert len(detail["history"]) == 2
    with pytest.raises(DBAPIError), scope.engine.begin() as c:
        c.execute(tables.product_proposal_revisions.update().values(document={}))
    bad = deepcopy(document)
    bad["specifications"][0]["source_ids"] = ["invented"]
    assert (
        client.post(
            path + "/changes", headers=headers, json={**command(edited.json()), "document": bad}
        ).status_code
        == 409
    )


class Model:
    def __init__(self, bad_source: bool = False, fail: bool = False):
        self.calls = 0
        self.bad_source, self.fail = bad_source, fail

    def invoke_structured(self, invocation, output_type):
        self.calls += 1
        if self.fail:
            return GatewayResult(
                status="degraded",
                output=None,
                error_code="PROVIDER_INVALID_RESPONSE",
                structured_attempts=1,
                removed_context_paths=(),
            )
        import json

        context = json.loads(invocation.context["question"])
        document = context["document"]
        document["narrative"] = "按B方案重写的合成提案"
        document["specifications"][0].update(
            value="AI尝试改写",
            state="confirmed",
            source_ids=["invented"] if self.bad_source else ["brief"],
        )
        return GatewayResult(
            status="succeeded",
            output=ProposalAssessment.model_validate(
                dict(document=document, completed=["重写了提案草稿"], needs_answers=["销售地区？"])
            ),
            error_code=None,
            structured_attempts=1,
            removed_context_paths=(),
        )


def test_ai_candidate_replay_confirmed_protection_and_one_save(
    client: TestClient,
    isolated_test_run_database: str,
) -> None:
    Scope(client, isolated_test_run_database)
    headers = bearer_headers(client)
    sid = space(client, headers)
    row = create(client, headers, sid)
    path = f"/api/product-work/spaces/{sid}/proposals/{row['id']}"
    document = deepcopy(row["document"])
    document["specifications"][0].update(value="骑行用户", state="confirmed", source_ids=["brief"])
    row = client.post(
        path + "/changes", headers=headers, json={**command(row), "document": document}
    ).json()
    model = Model()
    app.dependency_overrides[get_application_gateway] = lambda: model
    try:
        body = {**command(row), "instruction": "按B方案重写定义"}
        generated = client.post(path + "/ai", headers=headers, json=body)
        assert generated.status_code == 200, generated.text
        result = generated.json()
        assert result["status"] == "prepared", result
        assert result["document"]["specifications"][0]["value"] == "骑行用户"
        assert client.post(path + "/ai", headers=headers, json=body).json() == result
        assert model.calls == 1
        assert client.get(path, headers=headers).json()["document"] == document
        applied = client.post(
            path + "/changes",
            headers=headers,
            json={**command(row), "document": result["document"], "ai_run_id": result["run_id"]},
        )
        assert applied.status_code == 200, applied.text
        history = client.get(path, headers=headers).json()["history"]
        assert history[0]["origin"] == "ai_assisted"
        assert history[0]["ai_run_id"] == result["run_id"]
    finally:
        app.dependency_overrides.pop(get_application_gateway, None)


@pytest.mark.parametrize("fail", [False, True])
def test_bad_ai_output_never_overwrites_and_does_not_repeat_provider_call(
    client: TestClient,
    isolated_test_run_database: str,
    fail: bool,
) -> None:
    Scope(client, isolated_test_run_database)
    headers = bearer_headers(client)
    sid = space(client, headers)
    row = create(client, headers, sid)
    path = f"/api/product-work/spaces/{sid}/proposals/{row['id']}"
    model = Model(bad_source=True, fail=fail)
    app.dependency_overrides[get_application_gateway] = lambda: model
    try:
        body = {**command(row), "instruction": "起草提案"}
        result = client.post(path + "/ai", headers=headers, json=body)
        assert result.status_code == 200, result.text
        assert result.json()["status"] == "unavailable"
        client.post(path + "/ai", headers=headers, json=body)
        assert model.calls == 1
        assert client.get(path, headers=headers).json()["document"] == row["document"]
    finally:
        app.dependency_overrides.pop(get_application_gateway, None)


@pytest.mark.parametrize("format", ["docx", "pptx"])
def test_office_extraction_preserves_text_and_locators(format: str) -> None:
    stream = BytesIO()
    if format == "docx":
        doc = Document()
        doc.add_paragraph("续航 30 分钟")
        doc.add_table(rows=1, cols=2).cell(0, 0).text = "客户卖点"
        doc.save(stream)
    else:
        deck = Presentation()
        slide = deck.slides.add_slide(deck.slide_layouts[1])
        slide.shapes.title.text = "客户卖点"
        slide.placeholders[1].text = "续航 30 分钟"
        deck.save(stream)
    media, fragments, metadata = extract_document_details(
        filename="customer." + format, content=stream.getvalue()
    )
    assert media and metadata["source_format"] == "." + format
    assert "30" in " ".join(f.text for f in fragments)
    assert any(("paragraph" if format == "docx" else "slide") in f.locator for f in fragments)
    with pytest.raises(DocumentExtractionError):
        extract_document_details(filename="broken." + format, content=b"not an Office archive")


@pytest.mark.parametrize("format", ["docx", "pptx"])
def test_file_only_proposal_and_revoked_source_review(
    client: TestClient, isolated_test_run_database: str, format: str
) -> None:
    scope = Scope(client, isolated_test_run_database)
    headers = bearer_headers(client)
    sid = space(client, headers)
    base = f"/api/product-work/spaces/{sid}"
    stream = BytesIO()
    if format == "docx":
        doc = Document()
        doc.add_paragraph("Customer: battery life 30 minutes")
        doc.save(stream)
    else:
        deck = Presentation()
        slide = deck.slides.add_slide(deck.slide_layouts[1])
        slide.shapes.title.text = "Customer: battery life 30 minutes"
        deck.save(stream)
    content = stream.getvalue()
    store = Store()
    app.dependency_overrides[get_document_object_store] = lambda: store
    try:
        registered = client.post(
            base + "/source-files",
            headers=headers,
            json=dict(
                request_id=str(uuid4()),
                filename="customer." + format,
                size_bytes=len(content),
                sha256=sha256(content).hexdigest(),
                classification="internal",
            ),
        )
        assert registered.status_code == 201, registered.text
        file_path = base + "/source-files/" + registered.json()["id"]
        assert (
            client.put(file_path + "/upload", headers=headers, content=content).status_code == 200
        )
        parsed = client.post(file_path + "/parse", headers=headers)
        assert parsed.status_code == 200 and parsed.json()["status"] == "extracted", parsed.text
        with scope.engine.connect() as c:
            snapshots = c.execute(
                select(tables.audit_log.c.after_snapshot).where(
                    tables.audit_log.c.entity_id == UUID(registered.json()["id"])
                )
            ).scalars().all()
        assert snapshots and "customer." not in str(snapshots)
        assert all("filename" not in item and "fragments" not in item for item in snapshots)
        proposal = client.post(
            base + "/proposals",
            headers=headers,
            json=dict(
                request_id=str(uuid4()),
                title="合成客户文件提案",
                entry_kind="new_product" if format == "docx" else "odm",
                product_line_id=proposal_line(client, headers, sid),
                source_file_ids=[registered.json()["id"]],
            ),
        )
        assert proposal.status_code == 201, proposal.text
        assert registered.json()["product_line_id"] is None
        category = client.get(
            base + "/categories/" + proposal.json()["product_line_id"], headers=headers
        ).json()
        assert all(p["id"] != proposal.json()["id"] for p in category["products"])
        row = proposal.json()
        path = base + "/proposals/" + row["id"]
        detail = client.get(path, headers=headers).json()
        assert detail["source_catalog"][0]["locator"].startswith(
            "paragraph:" if format == "docx" else "slide:"
        )
        document = deepcopy(row["document"])
        document["narrative"] = "依据原文件的小额验证提案"
        saved = client.post(
            path + "/changes", headers=headers, json={**command(row), "document": document}
        )
        assert saved.status_code == 200, saved.text
        submitted = client.post(
            path + "/submit",
            headers=headers,
            json={**command(saved.json()), "reviewer_user_id": str(scope.owner_id)},
        )
        assert submitted.status_code == 200, submitted.text
        row = submitted.json()
        assert client.post(file_path + "/revoke", headers=headers).status_code == 200
        refused = client.post(
            path + "/decide",
            headers=headers,
            json={
                **command(row),
                "outcome": "approved",
                "rationale": "投入验证",
                "accepted_unknowns": "规格待冻结",
            },
        )
        assert refused.status_code == 409
        returned = client.post(
            path + "/decide",
            headers=headers,
            json={**command(row), "outcome": "returned", "rationale": "原件已撤回，请核对资料"},
        )
        assert returned.status_code == 200, returned.text
        assert client.get(path, headers=headers).json()["source_error"]
    finally:
        app.dependency_overrides.pop(get_document_object_store, None)


def test_old_ai_candidate_cannot_apply_to_a_new_human_version(
    client: TestClient, isolated_test_run_database: str
) -> None:
    Scope(client, isolated_test_run_database)
    headers = bearer_headers(client)
    sid = space(client, headers)
    row = create(client, headers, sid)
    path = f"/api/product-work/spaces/{sid}/proposals/{row['id']}"
    model = Model()
    app.dependency_overrides[get_application_gateway] = lambda: model
    try:
        generated = client.post(
            path + "/ai", headers=headers, json={**command(row), "instruction": "起草定义"}
        ).json()
        assert generated["status"] == "prepared", generated
        human_document = deepcopy(row["document"])
        human_document["narrative"] = "人工已决定改为轻量定位"
        saved = client.post(
            path + "/changes", headers=headers, json={**command(row), "document": human_document}
        ).json()
        refused = client.post(
            path + "/changes",
            headers=headers,
            json={
                **command(saved),
                "document": generated["document"],
                "ai_run_id": generated["run_id"],
            },
        )
        assert refused.status_code == 409
        assert client.get(path, headers=headers).json()["document"] == human_document
    finally:
        app.dependency_overrides.pop(get_application_gateway, None)


@pytest.mark.parametrize("revoke", [False, True])
def test_budgeted_proposal_run_binds_authority_lease_and_revocation(
    client: TestClient, isolated_test_run_database: str, revoke: bool
) -> None:
    from app.ai.application_leases import ApplicationLeaseKeeper
    from app.ai.budget_adoption import approved_budget_profile

    scope = Scope(client, isolated_test_run_database)
    headers = bearer_headers(client)
    sid = space(client, headers)
    row = create(client, headers, sid)
    path = f"/api/product-work/spaces/{sid}/proposals/{row['id']}"

    class BudgetedModel(Model):
        creation_budget_profile = approved_budget_profile("short")

        def invoke_structured(self, invocation, output_type):
            with scope.engine.connect() as c:
                assert (
                    c.execute(
                        text("SELECT cehub_ai.application_authorization_is_current(:r)"),
                        {"r": invocation.run_id},
                    ).scalar_one()
                    is True
                )
            if revoke:
                with scope.engine.begin() as c:
                    c.execute(
                        tables.users.update()
                        .where(tables.users.c.id == scope.owner_id)
                        .values(auth_version=tables.users.c.auth_version + 1)
                    )
            return super().invoke_structured(invocation, output_type)

    with ApplicationLeaseKeeper(scope.engine) as keeper:
        model = BudgetedModel()
        model.application_lease_keeper = keeper
        app.dependency_overrides[get_application_gateway] = lambda: model
        try:
            response = client.post(
                path + "/ai", headers=headers, json={**command(row), "instruction": "起草定义"}
            )
            assert response.status_code == 200, response.text
            result = response.json()
            assert result["status"] == ("unavailable" if revoke else "prepared"), result
            assert model.calls == 1
            with scope.engine.connect() as c:
                assert c.execute(select(tables.budget_run_links.c.run_id)).first()
                auth = c.execute(select(tables.application_authorizations)).mappings().one()
                assert auth["body"]["purpose"] == "product_proposal"
                lease = c.execute(select(tables.application_run_leases)).mappings().one()
                assert lease["ended_at"] is not None
                assert (
                    c.execute(select(tables.product_proposals.c.document)).scalar_one()
                    == row["document"]
                )
        finally:
            app.dependency_overrides.pop(get_application_gateway, None)


def test_migration_cannot_discard_saved_proposal_history(
    client: TestClient, isolated_test_run_database: str
) -> None:
    from importlib import import_module

    scope = Scope(client, isolated_test_run_database)
    headers = bearer_headers(client)
    sid = space(client, headers)
    row = create(client, headers, sid)
    revision = import_module("migrations.versions.0424_product_proposals")
    with pytest.raises(DBAPIError), rollback_migration_operations(scope.engine):
        revision.downgrade()
    assert (
        client.get(f"/api/product-work/spaces/{sid}/proposals/{row['id']}", headers=headers).json()[
            "document"
        ]
        == row["document"]
    )


def test_customer_proposal_is_private_until_named_reviewer_is_assigned(
    client: TestClient, isolated_test_run_database: str
) -> None:
    scope = Scope(client, isolated_test_run_database)
    headers = bearer_headers(client)
    sid = space(client, headers)
    row = create(client, headers, sid)
    base = f"/api/product-work/spaces/{sid}/proposals"
    path = base + "/" + row["id"]
    reviewer = uuid4()
    with scope.engine.begin() as c:
        password = c.execute(
            select(tables.users.c.password_hash).where(tables.users.c.id == scope.owner_id)
        ).scalar_one()
        c.execute(
            tables.users.insert().values(
                id=reviewer,
                tenant_id=scope.tenant_id,
                username="proposal-reviewer",
                display_name="合成具名产品评审人",
                role="product_manager",
                password_hash=password,
                is_active=True,
            )
        )
        c.execute(
            tables.market_space_members.insert().values(
                tenant_id=scope.tenant_id,
                market_space_id=UUID(sid),
                user_id=reviewer,
                access="manager",
                added_by_user_id=scope.owner_id,
            )
        )
    login = client.post(
        "/api/auth/login",
        json=dict(tenant_slug="beepump", username="proposal-reviewer", password=PASSWORD),
    )
    assert login.status_code == 200, login.text
    other = {"Authorization": "Bearer " + login.json()["access_token"]}
    assert client.get(base, headers=other).json()["items"] == []
    assert client.get(path, headers=other).status_code == 403
    with scope.engine.connect() as c:
        audit = c.execute(
            select(tables.audit_log.c.after_snapshot).where(
                tables.audit_log.c.entity_id == UUID(row["id"])
            )
        ).scalar_one()
        assert "brief" not in audit and "document" not in audit and "title" not in audit
        assert audit["document_digest"]
    submitted = client.post(
        path + "/submit", headers=headers, json={**command(row), "reviewer_user_id": str(reviewer)}
    )
    assert submitted.status_code == 200, submitted.text
    readable = client.get(path, headers=other)
    assert readable.status_code == 200 and readable.json()["can_decide"] is True
    assert len(client.get(base, headers=other).json()["items"]) == 1
    returned = client.post(
        path + "/decide",
        headers=other,
        json={**command(submitted.json()), "outcome": "returned", "rationale": "请完善客户说明"},
    )
    assert returned.status_code == 200, returned.text
    saved = client.post(
        path + "/changes",
        headers=headers,
        json={**command(returned.json()), "document": row["document"]},
    )
    assert saved.status_code == 200, saved.text
    assert client.get(path, headers=other).status_code == 403
