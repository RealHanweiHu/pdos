"""Offline regression against the actual Link and professional authority functions.

Uses existing fake-session fixtures for owner/source I/O, never PostgreSQL.
This does not establish actual source provenance, qualification or a saved Link.
"""

from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from capa_verification import test_pure as link_fixtures
from pdos_next.domain.capa_verification import service as links
from pdos_next.domain.capa_verification.schemas import FixedRef, ResolvedOutputs
from pdos_next.domain.professional_authority import service as authority
from pdos_next.errors import DomainError
from pdos_next.schemas.verification.contracts import Scope
from professional_authority import test_assessment as authority_fixtures
from sqlalchemy.engine import Engine

AT = authority_fixtures.AT
OP = "quality.capa.followup.link"
OTHER = "quality.capa.verification.candidate.record"


def add_series(session, *, operations, state="active"):
    for original in tuple(session.rows.values())[:2]:
        row = deepcopy(original)
        row.id = row.series_id = uuid4()
        row.external_id = str(row.id)
        row.operations, row.state = list(operations), state
        row.sources = [
            {
                "artifact_id": str(uuid4()),
                "expected_revision": 1,
                "line": 1,
                "quote": "Offline explicit authority source substitute",
            }
        ]
        row.required_source_read_set = authority._reads(row.sources)
        row.fact_sha256 = authority.digest(authority._material(row))
        pointer = deepcopy(session.pointers[0])
        pointer.id, pointer.fact_id, pointer.series_id = uuid4(), row.id, row.series_id
        pointer.kind, pointer.external_id = row.kind, row.external_id
        session.rows[row.id] = row
        session.pointers.append(pointer)


@pytest.fixture
def work(monkeypatch):
    def forbidden_connect(*args, **kwargs):
        raise AssertionError(
            "Database connections are forbidden in this offline regression"
        )

    monkeypatch.setattr(Engine, "connect", forbidden_connect)
    session = authority_fixtures.FakeSession()
    state = SimpleNamespace(
        session=session, at=AT + timedelta(minutes=1), source_epoch=1
    )
    for row in session.rows.values():
        row.operations = [OP]
        row.fact_sha256 = authority.digest(authority._material(row))
    monkeypatch.setattr(authority, "_project", lambda *args, **kwargs: (None, None))
    monkeypatch.setattr(
        authority,
        "_evidence",
        lambda s, ctx, pid, refs: (
            authority._reads(refs),
            False,
            {"security": [{"epoch": state.source_epoch}]},
        ),
    )
    monkeypatch.setattr(authority, "now", lambda: state.at)
    monkeypatch.setattr(links, "now", lambda: state.at)
    return state


def saved_link(work, monkeypatch):
    session = work.session
    snapshot = authority.assess(
        session,
        session.ctx,
        session.product,
        session.project,
        OP,
        authority_fixtures.PURPOSE,
        AT,
    )
    assert snapshot["authorized"] is True and snapshot["qualified"] is True
    basis = link_fixtures.basis.__wrapped__().model_copy(
        update={
            "scope": Scope(
                tenant_id=session.tenant,
                product_id=session.product,
                project_id=session.project,
            ),
            "owner_id": session.subject,
            "purpose": authority_fixtures.PURPOSE,
        }
    )
    basis = basis.model_copy(update={"basis_sha256": links._basis_digest(basis)})
    selected = link_fixtures.output(basis)
    evidence = [{"offline_fixed_output_source": "unchanged"}]
    resolution = ResolvedOutputs(
        basis=basis,
        action_id=basis.actions[0].action_id,
        outputs=(selected,),
        visibility="product",
        owner_id=session.subject,
        required_source_read_set=basis.required_source_read_set,
        source_basis_sha256=links.digest(evidence),
        resolution_sha256="0" * 64,
    )
    resolution = resolution.model_copy(
        update={
            "resolution_sha256": links.digest(
                resolution.model_dump(mode="json", exclude={"resolution_sha256"})
            )
        }
    )
    row = SimpleNamespace(
        id=uuid4(),
        basis_snapshot=basis.model_dump(mode="json"),
        basis_sha256=basis.basis_sha256,
        output_snapshot=resolution.model_dump(mode="json"),
        action_id=resolution.action_id,
        resolution_sha256=resolution.resolution_sha256,
        required_source_read_set=[
            r.model_dump(mode="json") for r in basis.required_source_read_set
        ],
        source_basis={"artifact_sources": evidence},
        authority_snapshot=snapshot,
        visibility="product",
    )
    monkeypatch.setattr(links, "_fixed_row", lambda *args: row)
    monkeypatch.setattr(links, "recheck_followup_basis", lambda *args, **kwargs: basis)
    monkeypatch.setattr(
        links, "resolve_followup_outputs", lambda *args, **kwargs: resolution
    )
    monkeypatch.setattr(links, "source_basis", lambda *args: (evidence, False))
    work.basis, work.row, work.snapshot = basis, row, snapshot
    return row


def read_link(work):
    session = work.session
    return links._link(
        session,
        session.ctx,
        session.product,
        work.basis,
        FixedRef(id=work.row.id, revision=1),
    )


def test_unrelated_new_series_retains_original_refs_and_current_time(work, monkeypatch):
    saved_link(work, monkeypatch)
    add_series(work.session, operations=[OTHER])
    session = work.session
    ordinary = authority.recheck_snapshot(
        session, session.ctx, session.product, session.project, work.snapshot, work.at
    )
    assert ordinary["current"] is False
    assert ordinary["assessment"]["authorized"] is True
    assert ordinary["assessment"]["qualified"] is True
    actual_assess, calls = authority.assess, []

    def observed_assess(*args, **kwargs):
        calls.append((args[6], kwargs.copy()))
        return actual_assess(*args, **kwargs)

    monkeypatch.setattr(authority, "assess", observed_assess)
    result = read_link(work)
    assert result.outputs
    assert calls == [
        (work.at, {"write": False, "retained_fact_refs": work.snapshot["fact_refs"]})
    ]


@pytest.mark.parametrize(
    "change",
    ["related_addition", "original_negative", "source", "issuer_aba", "current_aba"],
)
def test_retained_link_still_rejects_material_authority_changes(
    work, monkeypatch, change
):
    if change == "original_negative":
        add_series(work.session, operations=[OTHER], state="revoked")
    saved_link(work, monkeypatch)
    assert read_link(work).outputs
    session = work.session
    if change == "related_addition":
        add_series(session, operations=[OP])
    elif change == "original_negative":
        session.pointers[-1].epoch += 1
    elif change == "source":
        work.source_epoch += 1
    elif change == "issuer_aba":
        authority.disable_issuer(session.engine, "issuer")
        authority.configure_issuer(
            session.engine,
            key="issuer",
            version="v1",
            tenant_id=session.tenant,
            product_id=session.product,
        )
    elif change == "current_aba":
        session.pointers[0].epoch += 2
    with pytest.raises(DomainError) as raised:
        read_link(work)
    assert raised.value.code == "RECHECK_REQUIRED"


def test_retained_link_does_not_evaluate_at_historical_signature_clock(
    work, monkeypatch
):
    saved_link(work, monkeypatch)
    work.at = AT + timedelta(hours=1, seconds=1)
    with pytest.raises(DomainError) as raised:
        read_link(work)
    assert raised.value.code == "RECHECK_REQUIRED"
