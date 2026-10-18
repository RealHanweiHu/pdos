"""Real human G0 setup shared by downstream project transaction fixtures."""

import secrets
from copy import deepcopy
from datetime import date, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from pdos_next.models import Grant, LoginSession, Principal, now
from pdos_next.service import digest


def run_command(setup, operation, payload, *, actor=None, revision=1):
    """One real T1/T2 command through the public preview/commit pair."""
    command = {
        "category_id": str(setup.category),
        "command_id": str(uuid4()),
        "idempotency_key": str(uuid4()),
        "operation": operation,
        "product_id": None,
        "expected_revision": revision,
        "source_read_set": [],
        "payload": payload,
    }
    headers = {"Authorization": f"Bearer {setup.tokens[actor or setup.human]}"}
    route = f"/v1/categories/{setup.category}/commands"
    preview = setup.client.post(route + "/preview", headers=headers, json=command)
    assert preview.status_code == 200, preview.text
    prepared = preview.json()["command"]
    response = setup.client.post(route, headers=headers, json=prepared)
    assert response.status_code == 200, response.text
    return response.json(), prepared


def read_proposal(setup, proposal_id, *, actor=None):
    response = setup.client.get(
        f"/v1/categories/{setup.category}/proposals/{proposal_id}",
        headers={"Authorization": f"Bearer {setup.tokens[actor or setup.human]}"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def add_category_human(setup, *, name="Synthetic third human"):
    """A real third person in the same tenant, so a reviewer need not be setup.peer."""
    principal, token = uuid4(), secrets.token_urlsafe(32)
    with Session(setup.admin) as session, session.begin():
        session.add(Principal(id=principal, tenant_id=setup.tenant, name=name, kind="human"))
        session.flush()
        session.add_all(
            [
                Grant(
                    tenant_id=setup.tenant,
                    category_id=setup.category,
                    principal_id=principal,
                    can_write=True,
                    expires_at=now() + timedelta(hours=1),
                ),
                LoginSession(
                    tenant_id=setup.tenant,
                    principal_id=principal,
                    token_hash=digest(token),
                    expires_at=now() + timedelta(hours=1),
                ),
            ]
        )
    setup.tokens[principal] = token
    return principal


def _product_manager(setup, principal):
    with Session(setup.admin) as session, session.begin():
        grant = session.scalar(
            select(Grant).where(
                Grant.tenant_id == setup.tenant,
                Grant.category_id == setup.category,
                Grant.principal_id == principal,
            )
        )
        assert grant is not None
        grant.product_manager = True


def _options(purpose, source=None):
    section = {"kind": "section", "content": {"key": "worth_it", "text": purpose}}
    if source is not None:
        section["source_refs"] = [deepcopy(source)]
    return {
        "items": [
            section,
            {"kind": "option", "content": {"name": "Develop", "kind": "new"}},
            {"kind": "option", "content": {"name": "Keep current state", "kind": "do_nothing"}},
        ]
    }


def _new_option(row):
    return next(
        item["item_id"]
        for item in row["items"]
        if item["kind"] == "option" and item["content"]["kind"] == "new"
    )


def published_parent(setup, *, product_id=None, private=False):
    """A synthetic published baseline on an existing product.

    `product.definition.publish`（规格冻结, T2）has no command yet, and a stored
    definition can never be updated into `published`, so a derivative proposal
    needs the one owner-only publication fixture the derivation tests already
    cover. It records `synthetic: True`; no real publication qualification.
    """
    from tests.preproject.test_derivation_transactions import synthetic_parent

    return synthetic_parent(setup, product_id=product_id or setup.product, private=private)


def create_g0_variant(
    setup,
    *,
    product_id=None,
    name="Synthetic customer variant",
    variant_kind="customer",
    purpose="A customer variant of the fixed parent definition",
    reviewer=None,
):
    """A real variant identity from a derivative proposal approved at G0 (确认稿 P23).

    The proposal stays private, so the variant audience is exactly the owner, the
    named reviewer and the project owner. Pass a reviewer that is not setup.peer
    when the test needs setup.peer to remain outside that audience.
    """
    reviewer = reviewer if reviewer is not None else setup.peer
    _product_manager(setup, reviewer)
    parent = published_parent(setup, product_id=product_id)
    created, _ = run_command(
        setup,
        "proposal.create",
        {
            "title": name,
            "entry_kind": "derivative",
            "target_kind": "new_variant",
            "baseline_product_id": str(parent.product_id),
            "baseline_definition_id": str(parent.id),
            "baseline_definition_revision": parent.revision,
            "brief": purpose,
            "groups": _options(purpose),
        },
    )
    proposal_id = created["subject_id"]
    row = read_proposal(setup, proposal_id)
    run_command(
        setup,
        "proposal.g0.submit",
        {
            "proposal_id": proposal_id,
            "expected_revision": row["revision"],
            "reviewer_id": str(reviewer),
        },
        revision=row["revision"],
    )
    row = read_proposal(setup, proposal_id, actor=reviewer)
    # P11: every inherited unknown/conflict/待专业确认 item needs its own named
    # owner and deadline before the reviewer may approve.
    due = (date.today() + timedelta(days=8)).isoformat()
    dispositions = [
        {
            "subject_type": item["subject_type"],
            "subject_id": item["subject_id"],
            "kind": "task" if item["subject_type"] == "question" else "risk",
            "owner_id": str(setup.human),
            "due_date": due,
            "note": item["title"],
        }
        for item in row["maturity"]["required_dispositions"]
    ]
    receipt, command = run_command(
        setup,
        "proposal.g0.decide",
        {
            "proposal_id": proposal_id,
            "submission_id": row["submission"]["id"],
            "expected_revision": row["revision"],
            "outcome": "approved",
            "rationale": "Named independent review of a synthetic variant",
            "selected_option_item_id": _new_option(row),
            "dispositions": dispositions,
            "project": {"name": name, "owner_id": str(setup.human)},
            "new_identity": {"name": name, "variant_kind": variant_kind},
        },
        actor=reviewer,
        revision=row["revision"],
    )
    result = receipt["result"]
    return SimpleNamespace(
        variant_id=result["variant_id"],
        parent=parent,
        product_id=result["product_id"],
        definition_id=result["definition_id"],
        project_id=result["project_id"],
        proposal_id=proposal_id,
        reviewer_id=reviewer,
        receipt=receipt,
        command=command,
    )


def create_g0_project(
    setup,
    *,
    visibility="private",
    name="Synthetic development",
    purpose="Build and verify a synthetic design",
    source=None,
    reviewer=None,
):
    """Create through public commands; optional source is a real Reference DTO.

    A supplied Artifact reference must already be category scoped so the derived
    product can read it. No sealed definition or provenance is rewritten here.
    The original setup product remains intact; subsequent commands use the new one.
    """
    assert visibility in {"private", "category"}
    reviewer = reviewer if reviewer is not None else setup.peer
    _product_manager(setup, reviewer)

    def save(operation, payload, *, actor=None, revision=1):
        return run_command(setup, operation, payload, actor=actor, revision=revision)

    def read(proposal_id, *, actor=None):
        return read_proposal(setup, proposal_id, actor=actor)

    section = {"kind": "section", "content": {"key": "worth_it", "text": purpose}}
    if source is not None:
        section["source_refs"] = [deepcopy(source)]
    created, _ = save(
        "proposal.create",
        {
            "title": name,
            "entry_kind": "new_product",
            "brief": purpose,
            "groups": {
                "items": [
                    section,
                    {"kind": "option", "content": {"name": "Develop", "kind": "new"}},
                    {
                        "kind": "option",
                        "content": {"name": "Keep current state", "kind": "do_nothing"},
                    },
                ]
            },
        },
    )
    proposal_id = created["subject_id"]
    if visibility == "category":
        row = read(proposal_id)
        save(
            "proposal.share",
            {
                "proposal_id": proposal_id,
                "expected_revision": row["revision"],
                "visibility": "category",
                "audience_ids": [],
                "deidentified_confirmed": True,
            },
            revision=row["revision"],
        )
    row = read(proposal_id)
    save(
        "proposal.g0.submit",
        {
            "proposal_id": proposal_id,
            "expected_revision": row["revision"],
            "reviewer_id": str(reviewer),
        },
        revision=row["revision"],
    )
    row = read(proposal_id, actor=reviewer)
    receipt, command = save(
        "proposal.g0.decide",
        {
            "proposal_id": proposal_id,
            "submission_id": row["submission"]["id"],
            "expected_revision": row["revision"],
            "outcome": "approved",
            "rationale": "Named independent review of a synthetic project",
            "selected_option_item_id": next(
                item["item_id"]
                for item in row["items"]
                if item["kind"] == "option" and item["content"]["kind"] == "new"
            ),
            "dispositions": [],
            "project": {"name": name, "owner_id": str(setup.human)},
        },
        actor=reviewer,
        revision=row["revision"],
    )
    result = receipt["result"]
    setup.product = UUID(result["product_id"])
    return SimpleNamespace(
        product_id=result["product_id"],
        definition_id=result["definition_id"],
        project_id=result["project_id"],
        proposal_id=proposal_id,
        receipt=receipt,
        command=command,
    )
