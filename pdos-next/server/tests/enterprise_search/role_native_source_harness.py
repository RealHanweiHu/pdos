"""Real native commands reused by role-source and full-catalog recovery cases."""

from contextlib import contextmanager
from hashlib import sha256
from types import SimpleNamespace
from uuid import UUID

from pdos_next.domain.change_execution.service import configure_store
from sqlalchemy import func, literal, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session
from tests.manufacturing_preparation_transactions import fixtures as manufacturing
from tests.manufacturing_preparation_transactions.test_transactions import save
from tests.work_management_pg import test_workflow as status

TEXT = "Synthetic named project status basis; current gaps remain explicitly unknown."


def assert_native_proof_ports(person, row, *, parents=()):
    """Exercise installed visibility and the one existing typed lifecycle resolver."""
    from pdos_next.enterprise_search.sources import prepare_read
    from tests.enterprise_search.test_business_sources_pg import native_session

    proof = [
        {
            "source_type": row["source_type"],
            "source_id": str(row["source_id"]),
            "source_revision": row["source_revision"],
            "content_hash": row["content_hash"],
            "category_id": str(row["category_id"]),
        }
    ]
    with native_session(person) as session:
        prepare_read(session, [row["source_type"]])
        assert (
            session.scalar(
                select(
                    func.public.knowledge_answer_sources_visible(
                        person.tenant,
                        row["category_id"],
                        literal(proof, JSONB),
                    )
                )
            )
            is True
        )
        assert not session.scalar(
            select(func.has_function_privilege(
                "assistant_source_lifecycle_links(uuid,uuid,jsonb)", "EXECUTE",
            ))
        )
    # The lifecycle resolver is called only from internal retention functions.
    # Its output is not a Human authority check; the ordinary check stays above.
    with Session(person.admin) as session:
        links = session.scalar(
            select(
                func.public.assistant_source_lifecycle_links(
                    person.tenant,
                    row["category_id"],
                    literal(proof, JSONB),
                )
            )
        )
    assert {row["source_id"], *(UUID(str(value)) for value in parents)} <= set(links)


def seed_status(person, project_id, *, summary="Synthetic named status, no inferred health"):
    from test_project_first_plan import cmd, post

    registered = post(
        person,
        cmd(
            person,
            "evidence.artifact.register",
            {
                "title": "Synthetic named project status evidence",
                "content": TEXT,
                "source_label": "Explicit synthetic native role source",
                "visibility": "category",
            },
        ),
    )
    assert registered.status_code == 200, registered.text
    work = SimpleNamespace(
        setup=person,
        project_id=UUID(str(project_id)),
        source={
            "kind": "artifact",
            "id": registered.json()["subject_id"],
            "revision": 1,
            "position": "line:1;quote_sha256:" + sha256(TEXT.encode()).hexdigest(),
        },
    )
    _command, receipt = status.execute(
        work,
        status.STATUS,
        status.payload(
            work,
            fact_summary=summary,
            next_steps="Obtain missing materials before further assessment",
            task_refs=[],
        ),
    )
    return work, receipt


@contextmanager
def seed_manufacturing(person, configuration, tmp_path):
    # Reuse the original fixture's controlled issuer and original COMMON writes.
    # Calling its generator is deliberate composition, not invented domain rows.
    prior_store = getattr(person.engine, "_pdos_change_store", None)
    fixture = manufacturing.manufacturing_case.__wrapped__(person, configuration, tmp_path)
    work = next(fixture)
    try:
        manufacturing.bootstrap_authority(work)
        rows = {}
        for kind in ("work_instruction", "control_plan"):
            rows[kind] = save(
                work,
                manufacturing.inputs(
                    work,
                    kind,
                    manufacturing.payload(work, kind),
                ),
            )
        # The registered manufacturing text is already persisted. Keep its
        # issuer alive, but restore the outer report-byte reader for consumers.
        configure_store(person.engine, prior_store)
        yield rows
    finally:
        fixture.close()
