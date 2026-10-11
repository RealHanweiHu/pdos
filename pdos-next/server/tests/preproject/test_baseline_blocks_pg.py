"""Actual baseline/BOM outbound reads under ordinary application RLS.

The positive configuration chain uses real preview/confirm domain commands; only
its publication is the shared explicitly synthetic owner fixture. Negative cases
insert owner-only synthetic fixed snapshots to isolate private descendants that
normal configuration commands would refuse to broaden. Those fixture insertions
are not evidence of a successful business write. All tested reads use the app role.
Root executes this module only against its verified independent pdos_test.
"""
# ruff: noqa: F811 -- pytest injects the explicitly re-exported shared fixture

from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text

from pdos_next.agent_kernel.domain_reads import _public_baseline_bom, _public_definition
from pdos_next.domain.configurations.models import (
    BomLine,
    BomRevision,
    EngineeringConfiguration,
    PartIdentity,
)
from pdos_next.domain.preproject.baseline import read_baseline
from pdos_next.errors import DomainError
from pdos_next.service import Context
from tests.preproject.test_derivation_transactions import synthetic_owner, synthetic_parent
from tests.preproject.test_derivation_transactions import work as work
from tests.preproject.test_material_proofs_pg import human_session
from tests.test_configurations import accepted, bom_payload, command, post

QUOTE = "Synthetic baseline BOM source; no customer or production data."


def registered_source(work, *, visibility="category"):
    response = post(
        work,
        command(
            work,
            "evidence.artifact.register",
            {
                "title": "Synthetic baseline BOM source",
                "content": QUOTE,
                "source_label": "Isolated synthetic outbound-boundary test",
                "visibility": visibility,
            },
            [],
        ),
    )
    assert response.status_code == 200, response.text
    identity = response.json()["subject_id"]
    return (
        {"artifact_id": identity, "expected_revision": 1, "line": 1, "quote": QUOTE},
        [{"artifact_id": identity, "expected_revision": 1}],
    )


def public_command_chain(work):
    parent = synthetic_parent(work)
    ref, reads = registered_source(work)
    payload = bom_payload(ref)
    payload["visibility"] = "category"
    payload["lines"][0].update(quantity="2", unit="piece")
    saved_bom, _, _ = accepted(work, command(work, "engineering.bom.revise", payload, reads))
    saved_config, _, _ = accepted(
        work,
        command(
            work,
            "engineering.configuration.create",
            {
                "name": "Synthetic public baseline configuration",
                "reason": "Bind the exact synthetic publication and real BOM",
                "visibility": "category",
                "sources": [ref],
                "definition_id": str(parent.id),
                "expected_definition_revision": parent.revision,
                "bom_id": saved_bom["subject_id"],
                "expected_bom_revision": 1,
            },
            reads,
        ),
    )
    with human_session(work) as session:
        line = session.scalar(
            select(BomLine).where(BomLine.bom_id == UUID(saved_bom["subject_id"]))
        )
        assert line is not None
        part_id = line.part_id
    return SimpleNamespace(
        parent=parent,
        bom_id=UUID(saved_bom["subject_id"]),
        config_id=UUID(saved_config["subject_id"]),
        part_id=part_id,
    )


def owner_fixture_chain(work, private_node):
    """Build adversarial real rows without presenting owner inserts as business success."""
    parent = synthetic_parent(work)
    public_ref, public_reads = registered_source(work)
    part_ref, part_reads = (
        registered_source(work, visibility="private")
        if private_node == "source"
        else (public_ref, public_reads)
    )
    part_id, bom_id, config_id = uuid4(), uuid4(), uuid4()
    common = {
        "tenant_id": work.tenant,
        "category_id": work.category,
        "product_id": work.product,
        "owner_id": work.human,
        "status": "draft",
        "revision": 1,
    }
    fixed = {
        "previous_id": None,
        "expected_previous_revision": None,
        "reason": "Owner-only synthetic fixture; not a business command positive",
        "sources": [public_ref],
        "required_source_read_set": public_reads,
    }
    with synthetic_owner(work) as session:
        session.add(
            PartIdentity(
                **common,
                id=part_id,
                name="Synthetic guarded part",
                visibility="private" if private_node == "part" else "category",
                internal_number=f"M3-SYNTHETIC-{part_id}",
                external_design_refs=[],
                sources=[part_ref],
                required_source_read_set=part_reads,
            )
        )
        session.add(
            BomRevision(
                **common,
                **fixed,
                id=bom_id,
                series_id=bom_id,
                name="Synthetic guarded BOM",
                visibility="private" if private_node == "bom" else "category",
            )
        )
        session.flush()
        session.add(
            BomLine(
                tenant_id=work.tenant,
                category_id=work.category,
                product_id=work.product,
                bom_id=bom_id,
                key="guarded_part",
                part_id=part_id,
                part_revision=1,
                quantity=Decimal("2"),
                unit="piece",
                critical=False,
            )
        )
        session.add(
            EngineeringConfiguration(
                **common,
                **fixed,
                id=config_id,
                series_id=config_id,
                name="Synthetic guarded configuration",
                visibility="private" if private_node == "config" else "category",
                definition_id=parent.id,
                definition_revision=parent.revision,
                bom_id=bom_id,
                bom_revision=1,
                design_versions={"mechanical": None, "electronic": None, "firmware": None},
            )
        )
    return SimpleNamespace(
        parent=parent,
        bom_id=bom_id,
        config_id=config_id,
        part_id=part_id,
        private_source_id=UUID(part_ref["artifact_id"]) if private_node == "source" else None,
    )


def actual_baseline(session, work, chain):
    assert session.scalar(text("SELECT current_user")) == "pdos_next_app"
    ctx = Context(work.tenant, work.human, work.human, category_id=work.category)
    result = read_baseline(session, ctx, work.product, definition_revision=chain.parent.revision)
    assert result["baseline_kind"] == "published"
    assert result["definition"]["id"] == str(chain.parent.id)
    _public_definition(session, ctx, result["definition"])
    block = result["blocks"]["bom"]
    assert block["status"] == "available" and len(block["items"]) == 1
    item = block["items"][0]
    assert item["configuration"]["id"] == str(chain.config_id)
    assert (item["bom_id"], item["bom_revision"]) == (str(chain.bom_id), 1)
    assert item["definition_id"] == str(chain.parent.id)
    assert item["definition_revision"] == chain.parent.revision
    assert item["bom"]["lines"][0]["part_id"] == str(chain.part_id)
    assert item["bom"]["lines"][0]["quantity"] == "2"
    return ctx, result, item


def test_actual_public_command_chain_is_eligible_for_model_baseline_read(work):
    chain = public_command_chain(work)
    with human_session(work) as session:
        ctx, result, item = actual_baseline(session, work, chain)
        for row in (
            item["configuration"],
            item["bom"],
            item["bom"]["lines"][0]["part"],
        ):
            assert row["visibility"] == "category"
        assert _public_baseline_bom(session, ctx, work.product, result) is None


@pytest.mark.parametrize("private_node", ["config", "bom", "part", "source"])
def test_actual_locally_readable_private_bom_closure_cannot_enter_model(work, private_node):
    chain = owner_fixture_chain(work, private_node)
    with human_session(work) as session:
        ctx, result, item = actual_baseline(session, work, chain)
        if private_node == "source":
            # Configuration and BOM direct sources remain public; only the real
            # nested part's source points to the private artifact. No JSON mock.
            assert item["configuration"]["visibility"] == item["bom"]["visibility"] == "category"
            part = item["bom"]["lines"][0]["part"]
            assert part["visibility"] == "category"
            assert part["sources"][0]["artifact_id"] == str(chain.private_source_id)
            assert part["sources"][0]["quote"] == QUOTE
        with pytest.raises(DomainError) as error:
            _public_baseline_bom(session, ctx, work.product, result)
        assert error.value.code == "FORBIDDEN_SCOPE"
        assert error.value.detail["reason"] == "private_material_context_binding_required"
