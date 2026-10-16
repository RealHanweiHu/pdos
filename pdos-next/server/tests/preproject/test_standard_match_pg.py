"""Read-only standard matching on the explicitly verified synthetic database."""
# ruff: noqa: F811 -- shared isolated fixture

import secrets
from copy import deepcopy
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pdos_next.domain.preproject.models import Proposal
from pdos_next.domain.projects.models import Project
from pdos_next.models import Audit, LoginSession, Outbox, Receipt, now
from pdos_next.service import digest
from tests.preproject.test_category_context_pg import publish
from tests.preproject.test_derivation_transactions import synthetic_parent
from tests.preproject.test_evidence_commands_pg import artifact, record_claim, withdraw_request
from tests.preproject.test_g0 import save
from tests.preproject.test_g0 import work as work


def fixture(work, *, status="published", private=False, **changes):
    parameter = publish(work, standard_condition="one meter")
    spec = {
        "key": "noise",
        "parameter": "噪声",
        "parameter_id": UUID(parameter["parameter_id"]),
        "parameter_version": 1,
        "value_type": "number",
        "value": 70,
        "unit": "dB",
        "test_conditions": [],
        "condition_note": "one meter",
        "exceptions": [],
        **changes,
    }
    parent = synthetic_parent(work, status=status, private=private, spec_values=[spec])
    requirement = {
        "key": "noise",
        "parameter": "客户噪声",
        "parameter_id": parameter["parameter_id"],
        "parameter_version": 1,
        "value_type": "number",
        "upper": "75",
        "unit": "dB",
        "availability": "known",
        "condition_note": "one meter",
    }
    return parent, {"product_ids": [str(work.product)], "requirements": [requirement]}


def match(work, body, *, actor=None):
    return work.client.post(
        f"/v1/categories/{work.category}/standard-match",
        json=body,
        headers={"Authorization": f"Bearer {work.tokens[actor or work.human]}"},
    )


def counts(work):
    with Session(work.admin) as session:
        return {
            model.__tablename__: session.scalar(
                select(func.count()).select_from(model).where(model.tenant_id == work.tenant)
            )
            for model in (Project, Proposal, Receipt, Audit, Outbox)
        }


def test_actual_standard_match_has_published_sources_and_creates_no_business_rows(work):
    parent, body = fixture(work)
    before = counts(work)
    result = match(work, body)
    assert result.status_code == 200, result.text
    data = result.json()
    product = data["products"][0]
    assert product["status"] == "selected_specs_meet"
    assert product["definition_id"] == str(parent.id)
    assert product["counts"] == {"meets": 1, "differs": 0, "unknown": 0}
    assert product["checks"][0]["observation"]["source_refs"]
    assert data["requirements"][0]["parameter"] == "噪声"
    assert data["next_step"] == "confirm_full_scope_then_crm"
    assert match(work, body).json()["products"] == data["products"]
    assert counts(work) == before
    assert before["projects"] == before["proposals"] == 0


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"unit": None}, "unit_missing"),
        ({"condition_note": None}, "condition_missing"),
        ({"condition_note": "three meters"}, "different_parameter_or_conditions"),
        ({"unit": "dB(A)"}, "unit_differs"),
        ({"exceptions": [{"text": "except startup"}]}, "applicability_requires_review"),
        ({"item_status": "expert_pending"}, "requirement_expert_pending"),
        ({"verification_method": "different method"}, "verification_basis_differs"),
    ],
)
def test_unknown_or_incomparable_customer_requirements_never_match(work, change, reason):
    _, body = fixture(work)
    body["requirements"][0].update(change)
    response = match(work, body)
    assert response.status_code == 200, response.text
    check = response.json()["products"][0]["checks"][0]
    assert check["status"] == "unknown" and reason in check["reasons"]


def test_draft_and_unmapped_specs_do_not_satisfy_customer_requirements(work):
    _, body = fixture(work, status="draft")
    response = match(work, body)
    assert response.status_code == 200, response.text
    assert "published_definition_required" in response.json()["products"][0]["checks"][0]["reasons"]


def test_private_product_and_nonmember_reads_use_actual_scope(work):
    _, body = fixture(work, private=True)
    # The existing fixture gives the peer a named audience; another tenant has no access.
    denied = match(work, body, actor=work.other_human)
    assert denied.status_code == 403, denied.text
    token = secrets.token_urlsafe(32)
    with Session(work.admin) as session, session.begin():
        session.add(
            LoginSession(
                tenant_id=work.tenant,
                principal_id=work.expert,
                token_hash=digest(token),
                expires_at=now() + timedelta(hours=1),
            )
        )
    work.tokens[work.expert] = token
    assert match(work, body, actor=work.expert).status_code in {403, 404}
    foreign_product = deepcopy(body)
    foreign_product["product_ids"] = [str(uuid4())]
    assert match(work, foreign_product).status_code in {403, 404}


def test_withdrawn_definition_source_invalidates_a_previous_match(work):
    source_id = artifact(work, visibility="category")
    claim = record_claim(work, source_id)
    ref = {"type": "claim", "id": claim["subject_id"], "version": 1}
    _, body = fixture(work, source_refs=[ref])
    response = match(work, body)
    assert response.status_code == 200, response.text
    assert response.json()["products"][0]["status"] == "selected_specs_meet"
    save(work, withdraw_request(work, claim["subject_id"]))
    current = match(work, body)
    assert current.status_code == 200, current.text
    assert current.json()["products"][0]["status"] == "needs_review"
