"""Real PG adoption candidate; synthetic authority only, no real qualification.

Only Root may run this test after checking its explicit isolated target and lock.
Positive material is imported through the existing actual API/trusted wrapper.
The observer records only counts of the ProfessionalFact SELECT shape, never SQL,
parameters, row identities, tokens, URLs or names, and changes no execution.
"""

import json
from collections import Counter
from contextlib import contextmanager
from uuid import UUID, uuid4

from sqlalchemy import event, func, select, update
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from pdos_next.database import tenant_session
from pdos_next.domain.professional_authority import service as authority
from pdos_next.domain.professional_authority.models import ProfessionalCurrent, ProfessionalFact
from pdos_next.models import Artifact, Grant, now
from pdos_next.service import Context
from tests.professional_authority.test_transactions import (
    OP,
    PURPOSE,
    assessment,
    imported,
    pair,
    successor,
)


@contextmanager
def fact_shape_counts(engine):
    """Passive same-Engine observer; no execution, material or authorization shim."""
    observed = {"phase": None, "calls": {}}

    def before(connection, cursor, statement, parameters, context, executemany):
        phase = observed["phase"]
        compiled = getattr(context, "compiled", None)
        query = getattr(compiled, "statement", None)
        if phase is None or not isinstance(query, Select):
            return
        if any(item.get("entity") is ProfessionalCurrent for item in query.column_descriptions):
            kind = "current"
        elif any(item.get("entity") is ProfessionalFact for item in query.column_descriptions):
            kind = (
                "full_fact"
                if any(item.get("expr") is ProfessionalFact for item in query.column_descriptions)
                else "fact_metadata"
            )
        else:
            return
        observed["calls"].setdefault(phase, Counter())[kind] += 1

    event.listen(engine, "before_cursor_execute", before)
    try:
        yield observed
    finally:
        observed["phase"] = None
        event.remove(engine, "before_cursor_execute", before)


def test_current_summary_is_read_once_and_pending_full_fact_tamper_is_rejected(
    setup, authority_work
):
    records = pair(setup, authority_work)
    expected_ids = {UUID(value["subject_id"]) for value in records}
    project_id = UUID(authority_work["project"])
    source_id = UUID(authority_work["source"])
    positive_at = now()
    with tenant_session(
        setup.engine, setup.tenant, actor_id=setup.human, category_id=setup.category
    ) as session:
        pointers = list(
            session.scalars(
                select(ProfessionalCurrent).where(
                    ProfessionalCurrent.tenant_id == setup.tenant,
                    ProfessionalCurrent.product_id == setup.product,
                    ProfessionalCurrent.project_id == project_id,
                    ProfessionalCurrent.subject_id == setup.human,
                )
            )
        )
        assert len(pointers) == 2 and {value.fact_id for value in pointers} == expected_ids
        with fact_shape_counts(setup.engine) as measured:
            measured["phase"] = "first"
            first = authority.assess(
                session, setup.ctx, setup.product, project_id, OP, PURPOSE, positive_at
            )
            measured["phase"] = "second"
            second = authority.assess(
                session, setup.ctx, setup.product, project_id, OP, PURPOSE, positive_at
            )
            measured["phase"] = None
            assert first == second
            assert first["authorized"] is True and first["qualified"] is True
            assert first["synthetic"] is True and first["roles"] == ["quality"]
            assert {UUID(value["id"]) for value in first["fact_refs"]} == expected_ids
            assert first["required_source_read_set"] == [
                {"artifact_id": str(source_id), "expected_revision": 1}
            ]
            assert measured["calls"] == {
                "first": Counter({"current": 1}),
            }
            # Preserve the old no-autoflush pending guard: no bulk refresh may
            # overwrite this invalid in-memory authority before its hash check.
            warmed = list(
                session.scalars(
                    select(ProfessionalFact).where(ProfessionalFact.id.in_(expected_ids))
                )
            )
            assert len(warmed) == 2 and all(value.nature == "synthetic" for value in warmed)
            pending = next(value for value in warmed if value.kind == "qualification")
            original_state = pending.state
            try:
                pending.state = "revoked"
                assert pending in session.dirty
                with session.no_autoflush:
                    measured["phase"] = "pending"
                    rejected = authority.assess(
                        session, setup.ctx, setup.product, project_id, OP, PURPOSE, now()
                    )
                    measured["phase"] = None
                    assert rejected["authorized"] is False
                    assert "AUTHORITY_INTEGRITY_UNKNOWN" in rejected["reason_codes"]
                    assert pending.state == "revoked"
                    assert measured["calls"].get("pending", Counter())["full_fact"] == 0
            finally:
                measured["phase"] = None
                pending.state = original_state
    # A nominated subject is metadata under the actual caller, never borrowed scope.
    with tenant_session(
        setup.engine, setup.tenant, actor_id=setup.peer, category_id=setup.category
    ) as session:
        unrelated = Context(setup.tenant, setup.peer, setup.peer, category_id=setup.category)
        peer = authority.assess(session, unrelated, setup.product, project_id, OP, PURPOSE, now())
        assert peer["authorized"] is False and peer["fact_refs"] == []
    # Real app-role RLS: a different tenant sees neither actual facts nor pointers.
    with tenant_session(setup.engine, uuid4()) as session:
        assert session.scalar(select(func.count()).select_from(ProfessionalFact)) == 0
        assert session.scalar(select(func.count()).select_from(ProfessionalCurrent)) == 0
    # Same negative technique as the existing withdrawal contract. This creates
    # no released/qualified positive material and never extends any real grant.
    with Session(setup.admin) as session, session.begin():
        session.execute(
            update(Artifact)
            .where(
                Artifact.id == source_id,
                Artifact.tenant_id == setup.tenant,
                Artifact.product_id == setup.product,
            )
            .values(status="withdrawn")
        )
    with tenant_session(
        setup.engine, setup.tenant, actor_id=setup.human, category_id=setup.category
    ) as session:
        withdrawn = authority.assess(
            session, setup.ctx, setup.product, project_id, OP, PURPOSE, now()
        )
        assert withdrawn["authorized"] is False and withdrawn["fact_refs"] == []
        assert withdrawn["reason_codes"]
    print(
        json.dumps(
            {
                "schema_version": "professional-fact-batch-adoption-count-v1",
                "material_nature": "synthetic",
                "positive_assess_calls": 2,
                "full_fact_bulk_selects": 0,
                "current_summary_selects": 1,
                "same_transaction_summary_reused": True,
                "source_withdrawal_pending_scope_rls_guards_checked": True,
                "sql_parameters_credentials_output": False,
            },
            sort_keys=True,
        )
    )


def test_frozen_signature_survives_signer_write_revocation_and_current_successor(
    setup, authority_work
):
    records = pair(setup, authority_work)
    snapshot = assessment(setup, authority_work)
    assert snapshot["authorized"] is True and snapshot["qualified"] is True
    imported(
        setup,
        authority_work,
        successor(
            setup, authority_work, records[1], state="revoked", reason="Synthetic revocation"
        ),
    )
    with Session(setup.admin) as session, session.begin():
        session.execute(
            update(Grant)
            .where(
                Grant.tenant_id == setup.tenant,
                Grant.category_id == setup.category,
                Grant.principal_id == setup.human,
            )
            .values(can_write=False)
        )
    reader = Context(setup.tenant, setup.peer, setup.peer, category_id=setup.category)
    with tenant_session(
        setup.engine, setup.tenant, actor_id=setup.peer, category_id=setup.category
    ) as session:
        checked = authority.recheck_snapshot(
            session, reader, setup.product, UUID(authority_work["project"]), snapshot, now()
        )
        assert checked["historical_valid"] is True
        assert checked["needs_review"] is True and checked["current"] is False
        assert checked["assessment"] == snapshot
        retained = authority.recheck_snapshot(
            session,
            reader,
            setup.product,
            UUID(authority_work["project"]),
            snapshot,
            now(),
            retained=True,
        )
        assert retained["current"] is True and retained["historical_valid"] is True
        assert retained["needs_review"] is True and retained["assessment"] == snapshot
    current = assessment(setup, authority_work)
    assert current["qualified"] is False
    assert "QUALIFICATION_REVOKED" in current["reason_codes"]
