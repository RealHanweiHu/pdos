"""Three proposal entries → named G0 → actual readable project handoff."""
# ruff: noqa: F811 -- explicitly imported marked database fixtures

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pdos_next.domain.preproject.models import ProjectOpenItem
from pdos_next.domain.products.models import DefinitionRevision
from pdos_next.domain.products.variant_models import Variant
from pdos_next.domain.projects.models import Project
from pdos_next.models import Audit, Grant, Outbox, Product, Receipt
from tests.agent_kernel.test_m3_original_binding_pg import QUOTE, uploaded
from tests.preproject.test_derivation_transactions import derivative_payload, synthetic_parent
from tests.preproject.test_g0 import create, decide_request, payload, post, save, submit
from tests.preproject.test_g0 import work as work
from tests.test_original_security import security_work as security_work


def counts(work):
    with Session(work.admin) as session:
        return {
            model.__tablename__: session.scalar(
                select(func.count()).select_from(model).where(model.tenant_id == work.tenant)
            )
            for model in (
                Product,
                Variant,
                DefinitionRevision,
                Project,
                ProjectOpenItem,
                Receipt,
                Audit,
                Outbox,
            )
        }


def get(work, identity, actor=None):
    return work.client.get(
        f"/v1/categories/{work.category}/proposals/{identity}/handoff",
        headers={"Authorization": f"Bearer {work.tokens[actor or work.human]}"},
    )


@pytest.mark.parametrize("entry", ["customer_request", "new_product", "derivative"])
def test_actual_three_entry_handoff_retains_identity_v1_and_dispositions(
    work, security_work, entry
):
    arguments = payload(work)
    if entry == "derivative":
        arguments = derivative_payload(work, synthetic_parent(work), "new_variant")
    elif entry == "customer_request":
        _, version = uploaded(work, security_work)
        arguments.update(
            entry_kind=entry,
            customer_identities=["Synthetic customer"],
            source_refs=[
                {
                    "type": "original",
                    "id": str(version),
                    "version": 1,
                    "line": 1,
                    "quote": QUOTE,
                }
            ],
        )
    identity, _ = create(work, arguments)
    assert get(work, identity).status_code == 409
    submit(work, identity)
    request = decide_request(work, identity)
    request["payload"]["new_identity"] = {
        "name": "合成具名变体" if entry == "derivative" else "合成具名型号",
        "variant_kind": "customer",
    }
    preview = post(work, request, actor=work.peer, preview=True)
    assert preview.status_code == 200, preview.text
    review = preview.json()["review"]
    assert review["target_kind"] == ("new_variant" if entry == "derivative" else "new_product")
    assert review["identity_name"] == request["payload"]["new_identity"]["name"]
    command = preview.json()["command"]
    approved = post(work, command, actor=work.peer)
    assert approved.status_code == 200, approved.text
    assert post(work, command, actor=work.peer).json()["id"] == approved.json()["id"]
    before = counts(work)
    response = get(work, identity)
    assert response.status_code == 200, response.text
    data, result = response.json(), approved.json()["result"]
    assert data["category_id"] == str(work.category) and data["proposal_id"] == identity
    assert data["decision"]["id"] == result["decision_id"]
    assert data["decision"]["receipt_id"] == approved.json()["id"]
    assert data["decision"]["signer"]["id"] == str(work.peer)
    assert data["definition"]["id"] == result["definition_id"]
    assert data["definition"]["revision"] == 1 and data["definition"]["sealed"] is True
    assert data["definition"]["status"] == "draft"
    assert data["project"]["id"] == result["project_id"]
    assert data["project"]["definition_id"] == data["definition"]["id"]
    assert data["project"]["owner"]["id"] == str(work.expert)
    assert len(data["open_items"]) == len(request["payload"]["dispositions"])
    assert {item["kind"] for item in data["open_items"]} == {"task", "risk"}
    assert all(
        item["g0_decision_id"] == result["decision_id"]
        and item["project_id"] == result["project_id"]
        for item in data["open_items"]
    )
    if entry == "derivative":
        assert data["identity"]["product"]["id"] == str(work.product)
        assert data["identity"]["variant"]["id"] == result["variant_id"]
        assert data["identity"]["variant"]["name"] == "合成具名变体"
        assert data["identity"]["variant"]["kind"] == "customer"
    else:
        assert data["identity"]["variant"] is None
        assert data["identity"]["product"]["name"] == "合成具名型号"
    assert get(work, identity, work.peer).json() == data
    assert get(work, identity).json() == data and counts(work) == before
    assert get(work, identity, work.other_human).status_code == 403
    # Historical signing eligibility is not re-evaluated when reading a decision.
    with Session(work.admin) as session, session.begin():
        grant = session.scalar(
            select(Grant).where(Grant.category_id == work.category, Grant.principal_id == work.peer)
        )
        grant.product_manager = False
    assert get(work, identity).json() == data


@pytest.mark.parametrize("outcome", ["returned", "rejected"])
def test_nonapproved_decision_has_no_project_handoff(work, outcome):
    identity, _ = create(work)
    submit(work, identity)
    result, _ = save(work, decide_request(work, identity, outcome), actor=work.peer)
    assert result["result"]["project_id"] is None
    before = counts(work)
    assert get(work, identity).status_code == 409 and counts(work) == before
