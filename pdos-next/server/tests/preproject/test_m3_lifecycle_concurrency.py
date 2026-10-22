"""Two real commands and two app connections; root runs this on isolated PG.

The rendezvous observes a real PostgreSQL wait after command_scope obtained
its locks. It neither manufactures locks nor replaces source/domain checks.
No transaction retry may hide the Category/Product lock-order regression.
"""
# ruff: noqa: F811 -- pytest injects the explicitly re-exported shared fixture

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic
from uuid import UUID

from lifecycle_fixture import item_for, lifecycle_work  # noqa: F401
from sqlalchemy import select, text

from pdos_next import service
from pdos_next.contracts import Command
from pdos_next.database import tenant_session
from pdos_next.domain.preproject.evidence_models import EvidenceLink
from pdos_next.domain.preproject.models import Proposal, ProposalItemVersion
from pdos_next.domain.products.models import DefinitionSpecRow
from pdos_next.models import Artifact, Category, Product, UploadedOriginal
from tests.preproject.test_evidence_commands_pg import claim_body
from tests.preproject.test_g0 import create, post, read, request
from tests.preproject.test_m3_lifecycle_catalog import scoped, uploaded
from tests.test_project_first_plan import cmd


def test_pg_product_evidence_and_category_patch_share_category_first_fence(
    lifecycle_work, monkeypatch
):
    setup = lifecycle_work.setup
    original_id, source_id = uploaded(lifecycle_work, True)
    native = post(
        setup,
        cmd(
            setup,
            "evidence.artifact.register",
            {
                "title": "Synthetic product definition source",
                "source_label": "Synthetic lifecycle concurrency fixture",
                "content": "Synthetic exact public source",
                "visibility": "category",
            },
        ),
    )
    assert native.status_code == 200, native.text
    native_id = UUID(native.json()["subject_id"])
    native_ref = {
        "artifact_id": str(native_id),
        "expected_revision": 1,
        "line": 1,
        "quote": "Synthetic exact public source",
    }
    defined = post(
        setup,
        cmd(
            setup,
            "product.definition.draft",
            {
                "title": "Concurrent actual evidence target",
                "purpose": "Synthetic Category/Product lifecycle fence",
                "use_cases": ["Synthetic concurrent evidence adoption"],
                "change_reason": "Synthetic initial definition",
                "sources": [native_ref],
                "specs": [
                    {
                        "key": "unknown",
                        "parameter": "Unknown",
                        "value_type": "text",
                        "availability": "unknown",
                        "reason": "Synthetic uncertainty",
                        "sources": [native_ref],
                    }
                ],
            },
            str(native_id),
        ),
    )
    assert defined.status_code == 200, defined.text
    proposal_id, _ = create(setup)
    claim = post(
        setup,
        cmd(
            setup,
            "evidence.claim.record",
            claim_body(
                source_id,
                quote="Synthetic exact M3 lifecycle source",
                proposal_id=proposal_id,
            ),
        ),
    )
    assert claim.status_code == 200, claim.text
    document = read(setup, proposal_id).json()
    item = next(row for row in document["items"] if row["kind"] == "section")
    with scoped(setup) as session:
        spec_id = session.scalar(
            select(DefinitionSpecRow.id).where(
                DefinitionSpecRow.definition_id == UUID(defined.json()["subject_id"])
            )
        )
        before_category = session.get(Category, setup.category).lifecycle_epoch
        before_product = session.get(Product, setup.product).lifecycle_epoch
    assert spec_id is not None
    link = cmd(
        setup,
        "evidence.link.create",
        {
            "evidence": {"type": "artifact", "id": str(source_id), "version": 1},
            "target": {"type": "definition_spec", "id": str(spec_id), "version": 1},
            "relation": "supports",
        },
    )
    assert link["source_read_set"] == []
    reference = {
        "type": "claim",
        "id": claim.json()["subject_id"],
        "version": 1,
        "line": 1,
        "quote": "Synthetic exact M3 lifecycle source",
    }
    patch = request(
        setup,
        "proposal.item.patch",
        {
            "proposal_id": proposal_id,
            "ops": [
                {
                    "kind": item["kind"],
                    "item_id": item["item_id"],
                    "base_version": item["version"],
                    "content": {**item["content"], "text": "Synthetic concurrent adoption"},
                    "source_refs": [reference],
                }
            ],
        },
    )
    category_locked, link_ready, observed_wait = Event(), Event(), Event()
    backend_ids = {}
    real_command_scope = service.command_scope

    def observed_scope(session, ctx, command, *, lock=False):
        scope = real_command_scope(session, ctx, command, lock=lock)
        if lock and command.command_id == UUID(patch["command_id"]):
            category_locked.set()
            assert link_ready.wait(5), "Second app connection did not start"
            deadline = monotonic() + 5
            while monotonic() < deadline:
                blockers = session.scalar(
                    text("SELECT pg_blocking_pids(:pid)"), {"pid": backend_ids["link"]}
                )
                if backend_ids["patch"] in blockers:
                    observed_wait.set()
                    break
                Event().wait(0.01)
            assert observed_wait.is_set(), "Actual evidence command never waited on Category"
        return scope

    monkeypatch.setattr(service, "command_scope", observed_scope)

    def run(name, body):
        with scoped(setup) as session:
            session.execute(text("SET LOCAL lock_timeout='8s'"))
            session.execute(text("SET LOCAL statement_timeout='12s'"))
            backend_ids[name] = session.scalar(text("SELECT pg_backend_pid()"))
            if name == "link":
                link_ready.set()
                assert category_locked.wait(5), "Category command did not obtain its scope lock"
            # Intentionally avoid category_transaction's deadlock retry wrapper.
            receipt = service.execute(session, setup.ctx, Command.model_validate(body))
        return receipt

    with ThreadPoolExecutor(max_workers=2) as pool:
        patch_future = pool.submit(run, "patch", patch)
        link_future = pool.submit(run, "link", link)
        patched = patch_future.result(timeout=20)
        linked = link_future.result(timeout=20)
    assert backend_ids["patch"] != backend_ids["link"]
    assert observed_wait.is_set()
    assert patched["subject_id"] == proposal_id
    with scoped(setup) as session:
        assert session.get(Category, setup.category).lifecycle_epoch > before_category
        assert session.get(Product, setup.product).lifecycle_epoch > before_product
        source = session.get(Artifact, source_id)
        assert source.original_id == original_id and source.product_id == setup.product
        evidence = session.get(EvidenceLink, UUID(linked["subject_id"]))
        assert evidence.evidence_id == source_id and evidence.target_id == spec_id
        version = session.scalar(
            select(ProposalItemVersion).where(
                ProposalItemVersion.item_id == UUID(item["item_id"]),
                ProposalItemVersion.version == item["version"] + 1,
            )
        )
        assert len(version.source_refs) == 1
        assert all(version.source_refs[0][key] == value for key, value in reference.items())
    original = item_for(lifecycle_work, original_id)
    assert original["can_quarantine"] is False and original["reference_count"] > 0
    assert original["formal_history"] is True and "referenced" in original["reasons"]
    # Same actual rows remain invisible across the tenant boundary after both writes.
    with tenant_session(
        setup.engine,
        setup.other_tenant,
        actor_id=setup.other_human,
        requester_id=setup.other_human,
        category_id=setup.category,
    ) as session:
        for model, identity in (
            (Artifact, source_id),
            (UploadedOriginal, original_id),
            (Proposal, UUID(proposal_id)),
            (EvidenceLink, UUID(linked["subject_id"])),
        ):
            assert session.get(model, identity) is None
