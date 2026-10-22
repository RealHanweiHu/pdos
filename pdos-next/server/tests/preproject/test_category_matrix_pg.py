"""Real G0 → fixed segment/price → read-only category matrix HTTP projection.

The root runs this file against its explicitly verified isolated PostgreSQL.
Only ordinary synthetic login/audience setup and one adversarial target-price
mutation use the fixture admin; G0 and knowledge facts use public commands.
"""
# ruff: noqa: F811 -- pytest injects the imported real G0 fixture.

import json
import os
import secrets
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pdos_next.domain.preproject.category_models import (
    KnowledgeCurrent,
    KnowledgeEntry,
    ProductTargetSegment,
)
from pdos_next.domain.preproject.models import (
    ProjectOpenItem,
    Proposal,
    ProposalDecision,
    ProposalItemVersion,
    ProposalSubmission,
)
from pdos_next.domain.products.models import DefinitionRevision, DefinitionSpecRow
from pdos_next.domain.projects.models import Project
from pdos_next.models import (
    Audit,
    Confirmation,
    Grant,
    LoginSession,
    ObjectAudience,
    Outbox,
    Principal,
    Product,
    Receipt,
    now,
)
from pdos_next.service import digest
from tests.preproject.test_category_context_pg import add_knowledge
from tests.preproject.test_g0 import create, decide_request, payload, read, request, save, submit
from tests.preproject.test_g0 import work as work
from tests.preproject.test_proposal_views_pg import named_source, other_category


def matrix(work, *, actor=None, category=None, breaks=("150", "300")):
    return work.client.get(
        f"/v1/categories/{category or work.category}/category-matrix",
        params=[("price_breaks", value) for value in breaks],
        headers={"Authorization": f"Bearer {work.tokens[actor or work.human]}"},
    )


def segment(work, label="合成汽车应急细分"):
    return add_knowledge(work, kind="segment", content={"segment": label})


def approved_product(
    work,
    fixed_segment,
    *,
    amount="199.50",
    currency="CNY",
    basis="retail",
    includes_tax=True,
    as_of="2026-10-17",
    sourced=True,
    label="合成矩阵型号",
    statement="Synthetic named matrix target price",
):
    body = payload(work)
    body["title"] = label
    body["context_refs"] = [{"type": "knowledge", "id": fixed_segment["entry_id"], "version": 1}]
    target = {
        "amount": amount,
        "currency": currency,
        "basis": basis,
        "includes_tax": includes_tax,
        "as_of": as_of,
    }
    if sourced:
        target["source"] = {**named_source(work), "statement": statement}
    body["groups"]["items"].append(
        {"kind": "commercial_target", "content": {"target_price": target}}
    )
    identity, _ = create(work, body)
    submit(work, identity)
    command = decide_request(work, identity)
    command["payload"]["new_identity"] = {"name": label}
    receipt, _ = save(work, command, actor=work.peer)
    return {**receipt["result"], "proposal_id": identity}


def placements(data, identity=None):
    return [
        (group, row, cell, point)
        for group in data["groups"]
        for row in group["rows"]
        for cell in row["cells"]
        for point in cell["products"]
        if identity is None or point["subject"]["id"] == identity
    ]


def unplaced(data, identity):
    return [row for row in data["unplaced"] if row["subject"]["id"] == identity]


def counts(work):
    with Session(work.admin) as session:
        return {
            model.__tablename__: session.scalar(
                select(func.count()).select_from(model).where(model.tenant_id == work.tenant)
            )
            for model in (
                Product,
                ProductTargetSegment,
                KnowledgeEntry,
                KnowledgeCurrent,
                Proposal,
                ProposalItemVersion,
                ProposalSubmission,
                ProposalDecision,
                DefinitionRevision,
                DefinitionSpecRow,
                Project,
                ProjectOpenItem,
                Confirmation,
                Receipt,
                Audit,
                Outbox,
            )
        }


def unrelated_member(work):
    """A read-only category member, outside the real G0's named audience."""
    actor, token = uuid4(), secrets.token_urlsafe(32)
    with Session(work.admin) as session, session.begin():
        session.add(Principal(id=actor, tenant_id=work.tenant, name="合成无关成员", kind="human"))
        session.flush()
        session.add_all(
            [
                Grant(
                    tenant_id=work.tenant,
                    category_id=work.category,
                    principal_id=actor,
                    can_write=False,
                    expires_at=now() + timedelta(hours=1),
                ),
                LoginSession(
                    tenant_id=work.tenant,
                    principal_id=actor,
                    token_hash=digest(token),
                    expires_at=now() + timedelta(hours=1),
                ),
            ]
        )
    work.tokens[actor] = token
    return actor


def test_http_matrix_places_real_named_g0_and_does_not_write_business_facts(work):
    fixed = segment(work)
    result = approved_product(work, fixed, amount="150.00")
    before = counts(work)
    response = matrix(work)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["category_id"] == str(work.category)
    assert data["version"] == "category-matrix/v1"
    assert data["display"]["breaks"] == ["150", "300"]
    [(group, row, cell, point)] = placements(data, result["product_id"])
    assert row["segment"]["lineage_id"] == fixed["lineage_id"]
    assert row["segment"]["entry_id"] == fixed["entry_id"]
    assert row["segment"]["version"] == 1
    assert row["segment"]["label"] == "合成汽车应急细分"
    assert cell["band_id"] == "band:1" and cell["status"] == "observed"
    assert Decimal(point["price"]["amount"]) == Decimal("150")
    assert group["basis"]["currency"] == "CNY"
    assert group["basis"]["as_of"] == "2026-10-17"
    assert group["basis"]["basis"] == "retail" and group["basis"]["includes_tax"] is True
    proof = point["price"]["g0_source"]
    assert proof["proposal_id"] == result["proposal_id"]
    assert proof["decision_id"] == result["decision_id"]
    assert proof["submission_id"] and proof["document_digest"]
    [source] = point["source_refs"]
    assert {key: source[key] for key in ("type", "id", "version", "statement")} == {
        **named_source(work),
        "statement": "Synthetic named matrix target price",
    }
    assert not unplaced(data, result["product_id"])
    assert matrix(work).status_code == 200
    assert counts(work) == before

    # Explicit test-runner opt-in only: the browser can consume this exact PG projection.
    if destination := os.environ.get("PDOS_MATRIX_QA_RESPONSE_PATH"):
        output = Path(destination)
        assert output.is_absolute(), "QA response destination must be an explicit absolute path"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_http_matrix_uses_exact_decimal_edges_and_separates_price_bases(work):
    fixed = segment(work)
    below = approved_product(work, fixed, amount="150.000000000000", label="合成分界前")
    edge = approved_product(work, fixed, amount="150.000000000001", label="合成精确下界")
    upper = approved_product(work, fixed, amount="300", label="合成第二分界")
    usd = approved_product(work, fixed, amount="150.000000000001", currency="USD", label="合成美元")
    promo = approved_product(
        work, fixed, amount="150.000000000001", basis="promo", label="合成促销"
    )
    response = matrix(work, breaks=("150.000000000001", "300"))
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["display"]["breaks"] == ["150.000000000001", "300"]
    assert len(data["groups"]) == 3
    located = {
        point["subject"]["id"]: (group, cell, point) for group, _, cell, point in placements(data)
    }
    assert located[below["product_id"]][1]["band_id"] == "band:0"
    assert located[edge["product_id"]][1]["band_id"] == "band:1"
    assert located[upper["product_id"]][1]["band_id"] == "band:2"
    assert Decimal(located[edge["product_id"]][2]["price"]["amount"]) == Decimal("150.000000000001")
    assert located[usd["product_id"]][0]["id"] != located[edge["product_id"]][0]["id"]
    assert located[promo["product_id"]][0]["id"] != located[edge["product_id"]][0]["id"]
    assert data["coverage"]["placed_subjects"] == 5


def test_http_matrix_unplaces_missing_source_and_target_mismatch_without_rewriting_g0(work):
    fixed = segment(work)
    missing = approved_product(work, fixed, sourced=False, label="合成无来源目标价")
    mismatch = approved_product(work, fixed, label="合成错配目标价")
    original = read(work, mismatch["proposal_id"], work.peer).json()["submission"]
    # Adversarial synthetic head drift; the actual immutable G0 decision is left intact.
    with Session(work.admin) as session, session.begin():
        product = session.get(Product, UUID(mismatch["product_id"]))
        product.target_price = Decimal("200.50")
    response = matrix(work)
    assert response.status_code == 200, response.text
    data = response.json()
    assert not placements(data, missing["product_id"])
    assert not placements(data, mismatch["product_id"])
    assert all(
        "price_source_unavailable" in row["reasons"]
        for row in unplaced(data, missing["product_id"])
    )
    assert unplaced(data, missing["product_id"])
    assert any(
        "target_price_g0_mismatch" in row["reasons"]
        for row in unplaced(data, mismatch["product_id"])
    )
    assert read(work, mismatch["proposal_id"], work.peer).json()["submission"] == original


def test_http_matrix_keeps_fixed_segment_name_and_unplaces_withdrawn_lineage(work):
    fixed = segment(work, "合成固定旧细分名")
    result = approved_product(work, fixed)
    add_knowledge(
        work,
        kind="segment",
        content={"segment": "合成Current新细分名"},
        supersedes={"lineage_id": fixed["lineage_id"], "expected_version": 1},
    )
    response = matrix(work)
    assert response.status_code == 200, response.text
    [(_, row, _, _)] = placements(response.json(), result["product_id"])
    assert row["segment"]["entry_id"] == fixed["entry_id"]
    assert row["segment"]["version"] == 1
    assert row["segment"]["label"] == "合成固定旧细分名"
    assert "合成Current新细分名" not in response.text
    save(
        work,
        request(
            work,
            "category.knowledge.withdraw",
            {
                "lineage_id": fixed["lineage_id"],
                "expected_version": 2,
                "reason": "合成细分研究撤回",
            },
        ),
    )
    withdrawn = matrix(work)
    assert withdrawn.status_code == 200, withdrawn.text
    assert not placements(withdrawn.json(), result["product_id"])
    rows = unplaced(withdrawn.json(), result["product_id"])
    assert rows and all("segment_withdrawn" in row["reasons"] for row in rows)
    assert all(row["fixed_segment"]["version"] == 1 for row in rows)


def test_http_matrix_hides_private_products_from_unrelated_category_member(work):
    actor = unrelated_member(work)
    result = approved_product(
        work,
        segment(work),
        label="SYNTHETIC_PRIVATE_MATRIX_PRODUCT",
        statement="SYNTHETIC_PRIVATE_MATRIX_CITATION",
    )
    own = matrix(work)
    assert own.status_code == 200, own.text
    assert placements(own.json(), result["product_id"])
    denied = matrix(work, actor=actor)
    assert denied.status_code == 200, denied.text
    assert denied.json()["coverage"]["visible_products"] == 1  # Only the shared fixture product.
    for value in (
        result["product_id"],
        result["proposal_id"],
        result["decision_id"],
        "SYNTHETIC_PRIVATE_MATRIX_PRODUCT",
        "SYNTHETIC_PRIVATE_MATRIX_CITATION",
    ):
        assert value not in denied.text


def test_http_matrix_product_audience_does_not_grant_private_g0_provenance(work):
    actor = unrelated_member(work)
    result = approved_product(
        work,
        segment(work),
        label="合成已授权型号",
        statement="SYNTHETIC_G0_ONLY_PRICE_SOURCE",
    )
    with Session(work.admin) as session, session.begin():
        session.add(
            ObjectAudience(
                tenant_id=work.tenant,
                category_id=work.category,
                object_type="products",
                subject_id=UUID(result["product_id"]),
                owner_id=work.human,
                principal_id=actor,
            )
        )
    assert read(work, result["proposal_id"], actor).status_code == 404
    response = matrix(work, actor=actor)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["coverage"]["visible_products"] == 2
    assert not placements(data, result["product_id"])
    rows = unplaced(data, result["product_id"])
    assert rows and all("g0_price_source_unavailable" in row["reasons"] for row in rows)
    assert all("g0_source" not in row["price"] for row in rows)
    for value in (result["proposal_id"], result["decision_id"], "SYNTHETIC_G0_ONLY_PRICE_SOURCE"):
        assert value not in response.text


def test_http_matrix_rejects_foreign_tenant_and_keeps_other_category_empty(work):
    result = approved_product(work, segment(work), label="SYNTHETIC_CATEGORY_A_MATRIX_PRODUCT")
    category_b = other_category(work)
    other = matrix(work, category=category_b)
    assert other.status_code == 200, other.text
    assert other.json()["category_id"] == category_b
    assert other.json()["coverage"]["visible_products"] == 0
    assert other.json()["groups"] == [] and other.json()["unplaced"] == []
    assert result["product_id"] not in other.text
    assert result["proposal_id"] not in other.text
    assert matrix(work, category=category_b, actor=work.peer).status_code == 403
    assert matrix(work, actor=work.other_human).status_code == 403
