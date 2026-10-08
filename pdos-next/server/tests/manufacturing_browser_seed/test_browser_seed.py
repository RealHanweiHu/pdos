"""Root-only finite synthetic seed, using actual API saves and original fixture tokens."""

import json
import os
import stat
from pathlib import Path
from uuid import UUID

import pytest
from manufacturing_preparation_transactions.fixtures import (
    bootstrap_authority,
    history,
    inputs,
    parents,
    payload,
)
from manufacturing_preparation_transactions.test_transactions import (
    STANDARD_GAPS,
    gap_codes,
    reference,
    save,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from pdos_next.database import tenant_session
from pdos_next.domain.manufacturing_baseline.models import BaselineDocumentLink
from pdos_next.domain.professional_authority.models import ProfessionalCurrent, ProfessionalFact
from pdos_next.models import Artifact, Grant, LoginSession, Product, now
from pdos_next.object_storage import LocalPrivateObjectStore
from pdos_next.safety import verify_test_target
from pdos_next.service import digest


def _write_private_new(path: Path, value):
    encoded = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as output:
            assert stat.S_IMODE(os.fstat(output.fileno()).st_mode) == 0o600
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.skipif(
    os.environ.get("PDOS_MANUFACTURING_BROWSER_SEED") != "1",
    reason="Explicit browser seed invocation only; ordinary test runs create no login export",
)
def test_create_finite_synthetic_manufacturing_browser_seed(
    manufacturing_case, browser_seed_authorization
):
    work, setup = manufacturing_case, manufacturing_case.setup
    verify_test_target(setup.admin)
    verify_test_target(setup.engine)
    # The actual setup has already verified admin/app markers. Auth target identity
    # was checked before setup; no extra marker SELECT is demanded of the auth role.
    original_parents = parents(work)
    bootstrap_authority(work)
    materials = {
        kind: inputs(work, kind, payload(work, kind))
        for kind in ("work_instruction", "control_plan")
    }
    commands, receipts, documents = {}, {}, {}
    for kind in ("work_instruction", "control_plan"):
        commands[kind], receipts[kind], documents[kind] = save(work, materials[kind])
        assert documents[kind]["revision"] == 1
        assert documents[kind]["is_current"] is True
        assert documents[kind]["source_status"] == "current"
    baseline_payload = payload(
        work,
        "manufacturing_baseline",
        documents={kind: reference(value) for kind, value in documents.items()},
    )
    assert [row["operation_key"] for row in baseline_payload["operations"]] == list(
        work.operation_keys
    )
    materials["manufacturing_baseline"] = inputs(work, "manufacturing_baseline", baseline_payload)
    (
        commands["manufacturing_baseline"],
        receipts["manufacturing_baseline"],
        documents["manufacturing_baseline"],
    ) = save(work, materials["manufacturing_baseline"])
    baseline = documents["manufacturing_baseline"]
    assert baseline["revision"] == 1 and baseline["is_current"] is True
    assert baseline["source_status"] == "current"
    assert STANDARD_GAPS <= gap_codes(baseline["body"])
    assert len(baseline["body"]["document_bindings"]) == 2
    assert parents(work) == original_parents
    listed = history(work)
    assert len(listed["versions"]) == 3
    assert all(row["is_current"] is True for row in listed["versions"])
    assert listed["has_more"] is False and listed["unavailable_count"] == 0
    assert all(row["qualification"] == "unknown" for row in listed["versions"])
    assert all(row["manufacturing_release"] is None for row in listed["versions"])
    assert all(row["negative_enumeration_complete"] is False for row in listed["versions"])

    captured = now()
    # Read the original new fixture login and Grant; do not renew or rewrite either.
    token = setup.tokens[setup.human]
    with Session(setup.admin) as session:
        product = session.get(Product, setup.product)
        assert product is not None and product.tenant_id == setup.tenant
        assert product.owner_id == setup.human
        product_revision, product_name = product.revision, product.name
        login = session.get(LoginSession, digest(token))
        grant = session.scalar(
            select(Grant).where(
                Grant.tenant_id == setup.tenant,
                Grant.product_id == setup.product,
                Grant.principal_id == setup.human,
            )
        )
        assert login is not None and login.revoked is False and login.expires_at > captured
        assert (login.tenant_id, login.principal_id) == (setup.tenant, setup.human)
        assert grant is not None and grant.can_write is True and grant.expires_at > captured
        login_until, grant_until = login.expires_at, grant.expires_at
        grant_id, grant_epoch = str(grant.id), grant.access_epoch
    facts, fact_deadlines = [], []
    with tenant_session(setup.engine, setup.tenant) as session:
        stored = list(
            session.scalars(
                select(ProfessionalFact).where(
                    ProfessionalFact.product_id == setup.product,
                    ProfessionalFact.project_id == work.project_id,
                    ProfessionalFact.subject_id == setup.human,
                )
            )
        )
        assert len(stored) == 2 and {row.kind for row in stored} == {"duty", "qualification"}
        for row in stored:
            current = session.scalar(
                select(ProfessionalCurrent).where(
                    ProfessionalCurrent.product_id == setup.product,
                    ProfessionalCurrent.project_id == work.project_id,
                    ProfessionalCurrent.subject_id == setup.human,
                    ProfessionalCurrent.kind == row.kind,
                    ProfessionalCurrent.series_id == row.series_id,
                )
            )
            assert current is not None and (current.fact_id, current.fact_revision) == (
                row.id,
                row.revision,
            )
            assert row.nature == "synthetic" and row.state == "active"
            assert row.role == "manufacturing" and row.valid_from <= captured < row.valid_until
            assert (row.issuer_key, row.issuer_version) == (work.issuer.key, work.issuer.version)
            assert set(row.operations) == {command["operation"] for command in commands.values()}
            assert row.purposes == [work.purpose]
            fact_deadlines.append(row.valid_until)
            facts.append(
                {
                    "id": str(row.id),
                    "revision": row.revision,
                    "kind": row.kind,
                    "series_id": str(row.series_id),
                    "role": row.role,
                    "nature": row.nature,
                    "state": row.state,
                    "valid_from": row.valid_from.isoformat(),
                    "valid_until": row.valid_until.isoformat(),
                    "issuer_key": row.issuer_key,
                    "issuer_version": row.issuer_version,
                    "operations": list(row.operations),
                    "purposes": list(row.purposes),
                    "fact_sha256": row.fact_sha256,
                    "current_pointer_id": str(current.id),
                    "current_epoch": current.epoch,
                }
            )
        source_ids = {
            UUID(ref["artifact_id"])
            for command in commands.values()
            for ref in command["source_read_set"]
        }
        assert 1 <= len(source_ids) <= 20
        sources = list(session.scalars(select(Artifact).where(Artifact.id.in_(source_ids))))
        assert {row.id for row in sources} == source_ids
        assert all(row.original_id is None and row.status == "active" for row in sources)
        links = list(
            session.scalars(
                select(BaselineDocumentLink).where(
                    BaselineDocumentLink.baseline_id == UUID(baseline["id"])
                )
            )
        )
        assert len(links) == 2
        source_rows = [
            {
                "id": str(row.id),
                "revision": row.revision,
                "title": row.title,
                "source_origin": "registered_native_text",
                "original_id": None,
                "status": row.status,
                "visibility": row.visibility,
                "content_hash": row.content_hash,
            }
            for row in sources
        ]
    store = getattr(setup.engine, "_pdos_change_store", None)
    assert isinstance(store, LocalPrivateObjectStore)
    assert store.root.is_dir() and stat.S_IMODE(store.root.stat().st_mode) & 0o077 == 0
    profile = {
        "tenant_id": str(work.issuer.tenant_id),
        "product_id": str(work.issuer.product_id),
        "project_id": str(work.issuer.project_id),
        "key": work.issuer.key,
        "version": work.issuer.version,
    }
    assert work.issuer.nature == "synthetic"
    value = {
        "schema_version": "pdos-manufacturing-browser-seed-v1",
        "synthetic": True,
        "created_at": captured.isoformat(),
        "tenant_id": str(setup.tenant),
        "principal_id": str(setup.human),
        "product_id": str(setup.product),
        "product_revision": product_revision,
        "product_name": product_name,
        "project_id": str(work.project_id),
        "purpose": work.purpose,
        "process": work.process_ref,
        "operation_keys": list(work.operation_keys),
        "login_token": token,
        "login_expires_at": login_until.isoformat(),
        "grant": {
            "id": grant_id,
            "can_write": True,
            "access_epoch": grant_epoch,
            "expires_at": grant_until.isoformat(),
        },
        "professional_profiles": [profile],
        "issuer_epoch_at_seed": work.issuer.epoch,
        "professional_facts": sorted(facts, key=lambda row: row["kind"]),
        "effective_until": min(login_until, grant_until, *fact_deadlines).isoformat(),
        "object_store_root": str(store.root),
        "object_store_kind": "LocalPrivateObjectStore",
        "asgi_object_store_environment": "PDOS_OBJECT_ROOT",
        "asgi_profiles_environment": "PDOS_PROFESSIONAL_SYNTHETIC_PROFILES",
        "sources": source_rows,
        "source_count": len(source_rows),
        "uploaded_original_count": 0,
        "original_source_note": "All seed sources are actual API-registered native Artifacts; "
        "no uploaded originals or upload/security path is claimed.",
        "documents": documents,
        "prepared_commands": commands,
        "receipts": receipts,
        "draft_payloads": {
            kind: material["review"]["after"]["body"]["input"]
            for kind, material in materials.items()
        },
        "boundary": "Finite isolated synthetic actor/login/Grant/facts only; no release, "
        "real qualification or production activation. Never extend these expiries.",
    }
    _write_private_new(browser_seed_authorization, value)
    # Output neither token nor seed JSON. Root reads the new private path directly.
    assert browser_seed_authorization.is_file()
