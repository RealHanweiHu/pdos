"""D274: a personal Run's pinned sources count in each source category's lifecycle graph.

P91 personal Runs have no category of their own. Like a DingTalk personal answer, the
Run joins category c's graph with only the sources whose receipt names c, so purge and
retention planning there sees its references.
"""

import base64
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from pdos_next.core.contracts import UploadInput
from pdos_next.core.database import tenant_session
from pdos_next.core.models import Artifact
from pdos_next.originals.access import upload
from pdos_next.originals.object_storage import LocalPrivateObjectStore
from pdos_next.originals.security import configure
from tests.agent.enterprise_search.test_retrieval_pg import register
from tests.agent.kernel.test_personal_run_sources_pg import (
    BODY,
    in_category,
    other_category,
    start,
)
from tests.originals.office_fixture import docx_bytes
from tests.security_fixture import secured_parse, synthetic_runtime

NODES = text(
    "SELECT node_id,links FROM public.m3_lifecycle_nodes(:tenant,:category) "
    "WHERE table_name='agent_runs' AND node_id=:run"
)
SUMMARY = text(
    "SELECT reference_count,formal_history FROM public.lifecycle_reference_summary("
    ":tenant,:category,NULL,CAST(:roots AS uuid[]))"
)


def run_nodes(setup, category, run):
    with tenant_session(setup.admin, setup.tenant, actor_id=setup.human,
                        category_id=category) as session:
        rows = session.execute(
            NODES, {"tenant": setup.tenant, "category": category, "run": run}
        ).all()
        by_identity = session.execute(
            text(
                "SELECT count(*) FROM public.m3_lifecycle_nodes(:tenant,:category,"
                "CAST(:ids AS uuid[])) WHERE table_name='agent_runs'"
            ),
            {"tenant": setup.tenant, "category": category, "ids": [run]},
        ).scalar_one()
    return [set(links) for _, links in rows], by_identity


def summary(setup, original):
    """What purge/retention planning reads (originals.lifecycle.access.References)."""
    with tenant_session(setup.engine, setup.tenant, actor_id=setup.human,
                        requester_id=setup.human, category_id=setup.category) as session:
        return session.execute(
            SUMMARY, {"tenant": setup.tenant, "category": setup.category, "roots": [original]}
        ).one()


def test_personal_run_joins_each_source_category_graph_with_only_its_sources(setup):
    first = register(setup, "本品类合成资料", BODY)
    second_category = other_category(setup, members=[setup.human, setup.agent])
    second = register(in_category(setup, second_category), "他品类合成资料", BODY)
    unrelated = other_category(setup, members=[setup.human, setup.agent])
    response = start(setup, [first, second])
    assert response.status_code == 202, response.text
    run = UUID(response.json()["run_id"])
    assert run_nodes(setup, setup.category, run) == ([{first}], 0)
    assert run_nodes(setup, second_category, run) == ([{second}], 0)
    assert run_nodes(setup, unrelated, run) == ([], 0)
    # A personal Run without sources joins no category graph.
    plain = start(setup, [])
    assert plain.status_code == 202, plain.text
    assert run_nodes(setup, setup.category, UUID(plain.json()["run_id"])) == ([], 0)


def test_purge_planning_counts_a_personal_run_that_pinned_the_original(setup, tmp_path):
    configure(setup.engine, synthetic_runtime())
    try:
        store = LocalPrivateObjectStore(tmp_path / "originals")
        data = UploadInput(
            title="合成客户规格",
            filename="合成客户规格.docx",
            visibility="private",
            source_label="D274 合成原件",
            expected_revision=1,
            idempotency_key=str(uuid4()),
            content_base64=base64.b64encode(docx_bytes()).decode("ascii"),
        )
        with tenant_session(setup.engine, setup.tenant, actor_id=setup.human,
                            requester_id=setup.human, category_id=setup.category) as session:
            original = UUID(upload(session, setup.ctx, None, data, store)["subject_id"])
        reference = {
            "category_id": str(setup.category),
            "actor_id": str(setup.human),
            "requester_id": str(setup.human),
            "tenant_id": str(setup.tenant),
            "product_id": None,
            "subject_id": str(original),
        }
        assert secured_parse(setup.engine, reference, store)["status"] == "parsed"
        with Session(setup.admin) as session:
            source = session.scalar(select(Artifact.id).where(Artifact.original_id == original))
        before = summary(setup, original)
        response = start(setup, [source])
        assert response.status_code == 202, response.text
        run = UUID(response.json()["run_id"])
        assert run_nodes(setup, setup.category, run) == ([{source}], 0)
        # Exactly the Run is new among the original's references, and it is formal history.
        after = summary(setup, original)
        assert after.reference_count == before.reference_count + 1
        assert after.formal_history is True
    finally:
        configure(setup.engine, None)
