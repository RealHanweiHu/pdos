"""Real human G0 setup shared by downstream project transaction fixtures."""

from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from pdos_next.models import Grant


def create_g0_project(
    setup,
    *,
    visibility="private",
    name="Synthetic development",
    purpose="Build and verify a synthetic design",
    source=None,
):
    """Create through public commands; optional source is a real Reference DTO.

    A supplied Artifact reference must already be category scoped so the derived
    product can read it. No sealed definition or provenance is rewritten here.
    The original setup product remains intact; subsequent commands use the new one.
    """
    assert visibility in {"private", "category"}
    with Session(setup.admin) as session, session.begin():
        reviewer = session.scalar(
            select(Grant).where(
                Grant.tenant_id == setup.tenant,
                Grant.category_id == setup.category,
                Grant.principal_id == setup.peer,
            )
        )
        assert reviewer is not None
        reviewer.product_manager = True

    def save(operation, payload, *, actor=None, revision=1):
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

    def read(proposal_id, *, actor=None):
        response = setup.client.get(
            f"/v1/categories/{setup.category}/proposals/{proposal_id}",
            headers={"Authorization": f"Bearer {setup.tokens[actor or setup.human]}"},
        )
        assert response.status_code == 200, response.text
        return response.json()

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
            "reviewer_id": str(setup.peer),
        },
        revision=row["revision"],
    )
    row = read(proposal_id, actor=setup.peer)
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
        actor=setup.peer,
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
