"""Actual retention closure/clock and immutable native metadata; root runs PG.

No model, tool receipt or binding is fabricated. Existing native commands create
the project/status and original; the privileged connection only inspects closure
and attempts a rejected metadata fault update.
"""

# ruff: noqa: F401, F811 -- pytest needs the existing native fixture tree

import json
from copy import deepcopy
from hashlib import sha256
from types import SimpleNamespace
from uuid import UUID

import pytest
from g0_fixture import create_g0_project
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_original_security import parsed, uploaded

from pdos_next.agent_kernel.bootstrap import Bootstrap
from pdos_next.agent_kernel.conversation import memory
from pdos_next.agent_kernel.host import BoundHost
from pdos_next.agent_kernel.models import AgentRun
from pdos_next.agent_kernel.project_current_context import KEY
from pdos_next.database import tenant_session
from pdos_next.domain.projects.models import Project
from pdos_next.domain.work_management.constants import STATUS
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Category, ObjectAudience, Product, UploadedOriginal
from pdos_next.service import Context, source_for
from tests.agent_kernel.test_project_current_context_pg import (
    original_security_work,
    prepare,
    project_work,
    start,
)
from tests.agent_kernel.test_run_continuation import scope as api_scope
from tests.agent_kernel.test_run_continuation import start as api_start
from tests.work_management_pg import test_workflow as flow


def test_actual_native_project_footprint_retains_original_without_explicit_binding(project_work):
    work, setup = project_work, project_work.setup
    prepare(work)
    with tenant_session(setup.engine, setup.tenant, actor_id=setup.human,
                        category_id=setup.category) as session:
        before = session.get(Category, setup.category).lifecycle_epoch
    store, scope = start(work)
    with store.transaction(scope) as (_, run):
        assert run.read_sources == []
        payload = {"id": str(run.id), "tenant_id": str(run.tenant_id),
                   "category_id": str(run.category_id), "product_id": str(run.product_id),
                   "read_sources": [], "versions": {KEY: deepcopy(run.versions[KEY])}}
    with tenant_session(setup.admin, setup.tenant, actor_id=setup.human,
                        category_id=setup.category) as session:
        assert session.get(Category, setup.category).lifecycle_epoch > before
        params = {"tenant": setup.tenant, "category": setup.category,
                  "payload": json.dumps(payload), "run": scope.run_id}
        links = session.scalar(text(
            "SELECT public.m3_lifecycle_source_links(:tenant,:category,'agent_runs',"
            "CAST(:payload AS jsonb))"
        ), params)
        assert work.source["id"] in {str(identity) for identity in links}
        roots = session.scalar(text(
            "SELECT public.m3_lifecycle_roots(:tenant,:category,'agent_runs',"
            "CAST(:payload AS jsonb))"
        ), params)
        assert str(work.original_id) in {str(identity) for identity in roots}
        node = session.scalar(text(
            "SELECT links FROM public.m3_lifecycle_nodes(:tenant,:category,NULL::uuid[]) "
            "WHERE table_name='agent_runs' AND node_id=:run"
        ), params)
        assert work.source["id"] in {str(identity) for identity in node}
    with pytest.raises(DBAPIError) as immutable:
        with Session(setup.admin) as session, session.begin():
            row = session.get(AgentRun, scope.run_id)
            changed = deepcopy(row.versions)
            del changed[KEY]
            row.versions = changed
    assert immutable.value.orig.sqlstate == "23514"
    with store.transaction(scope) as (_, run):
        assert run.versions[KEY] == payload["versions"][KEY] and run.read_sources == []


def test_native_history_keeps_old_revision_but_hides_after_source_only_recipient_revoke(
    project_work,
):
    """Same category/project remain readable; only the source recipient is revoked."""
    setup = project_work.setup
    private = create_g0_project(setup, visibility="private", name="Native footprint privacy",
                                purpose="Actual same-category source-only permission boundary")
    content = "Synthetic native source: named project condition remains individually traceable."
    with Session(setup.admin) as session, session.begin():
        product = session.get(Product, setup.product)
        assert product.visibility == "private" and product.owner_id == setup.human
        peer_access = session.scalar(select(ObjectAudience).where(
            ObjectAudience.tenant_id == setup.tenant, ObjectAudience.category_id == setup.category,
            ObjectAudience.object_type == "products", ObjectAudience.subject_id == product.id,
            ObjectAudience.owner_id == product.owner_id, ObjectAudience.principal_id == setup.peer,
        ))
        if peer_access is None:
            session.add(ObjectAudience(
                tenant_id=setup.tenant, category_id=setup.category, object_type="products",
                subject_id=product.id, owner_id=product.owner_id, principal_id=setup.peer,
            ))
    peer = SimpleNamespace(**{
        **vars(setup), "human": setup.peer,
        "headers": {"Authorization": "Bearer " + setup.tokens[setup.peer]},
        "ctx": Context(setup.tenant, setup.peer, setup.peer, category_id=setup.category),
    })
    security = SimpleNamespace(**{**vars(project_work.security), "setup": peer})
    original_id = uploaded(security, content=(content + "\n").encode(), visibility="private")
    source_id = parsed(security, original_id)
    with Session(setup.admin) as session, session.begin():
        source = session.get(Artifact, source_id)
        original = session.get(UploadedOriginal, original_id)
        assert source.owner_id == setup.peer and source.visibility == "private"
        assert source.original_id == original.id and source.product_id == setup.product
        assert original.owner_id == setup.peer and original.visibility == "private"
        assert original.product_id == setup.product and original.status == "parsed"
        audience = ObjectAudience(
            tenant_id=setup.tenant, category_id=setup.category, object_type="uploaded_originals",
            subject_id=original.id, owner_id=original.owner_id, principal_id=setup.human,
        )
        session.add(audience)
        session.add(ObjectAudience(
            tenant_id=setup.tenant, category_id=setup.category, object_type="artifact_versions",
            subject_id=source.id, owner_id=source.owner_id, principal_id=setup.human,
        ))
        session.flush()
        audience_id = audience.id
    with tenant_session(setup.engine, setup.tenant, actor_id=setup.human,
                        category_id=setup.category) as session:
        source = source_for(session, setup.ctx, setup.product, source_id, 1)
        assert source.original_id == original_id
    work = SimpleNamespace(**{**vars(project_work), "project_id": UUID(private.project_id),
                              "source": {"kind": "artifact", "id": str(source_id),
                                         "revision": 1, "position": "line:1;quote_sha256:" +
                                         sha256(content.encode()).hexdigest()}})
    flow.execute(work, STATUS, flow.payload(
        work, fact_summary="SYNTHETIC_NATIVE_PRIVATE_STATUS", next_steps="保留具名状态原版本。",
        task_refs=[],
    ))
    store, scope = start(work)
    owner = Bootstrap(setup.engine)
    BoundHost(store, owner.adapters()).skill_context(scope, "核对具名状态", bindings=())
    output = owner.verify_result(scope, {
        "status": "completed", "summary": "SYNTHETIC_NATIVE_PRIVATE_STATUS",
        "result": {}, "questions": [], "unfinished": [],
    }, [])
    store.finish(scope, output)
    with Session(setup.admin) as session, session.begin():
        source = session.get(Artifact, source_id)
        source.revision = 2  # The original guard permits actual current-version changes.
    with tenant_session(setup.engine, setup.tenant, actor_id=setup.human,
                        category_id=setup.category) as session:
        old = session.get(AgentRun, scope.run_id)
        assert old is not None and old.read_sources == []
        assert any(ref["artifact_id"] == str(source_id) and ref["expected_revision"] == 1
                   for ref in old.versions[KEY]["source_proof"])
    path = f"/v1/categories/{setup.category}/agent-runs/{scope.run_id}"
    preserved = setup.client.get(path, headers=setup.headers)
    assert preserved.status_code == 200, preserved.text
    original_goal = preserved.json()["goal"]
    result = preserved.json()["result"]
    assert result["summary"] == output["summary"]
    assert result["result"]["assistant"]["project_basis"]["currentness"] == "updated"
    child, _ = api_start(setup, continue_from_run_id=str(scope.run_id), goal="继续核对当前项目。")
    child_scope = api_scope(setup, child)
    with Session(setup.admin) as session, session.begin():
        session.delete(session.get(ObjectAudience, audience_id))
    with tenant_session(setup.engine, setup.tenant, actor_id=setup.human,
                        category_id=setup.category) as session:
        assert session.get(Category, setup.category) is not None
        assert session.get(Project, work.project_id) is not None
        assert session.get(UploadedOriginal, original_id) is None
        with pytest.raises(DomainError) as source_denied:
            source_for(session, setup.ctx, setup.product, source_id)
        assert source_denied.value.code in {"FORBIDDEN_SCOPE", "SOURCE_UNAVAILABLE"}
        assert session.get(AgentRun, scope.run_id) is None
    with tenant_session(setup.engine, setup.tenant, actor_id=peer.human,
                        category_id=setup.category) as session:
        assert source_for(session, peer.ctx, setup.product, source_id, 2).original_id == original_id
    with tenant_session(setup.engine, setup.tenant, actor_id=setup.human,
                        category_id=setup.category, read_snapshot=True) as session:
        actual_child = session.get(AgentRun, child_scope.run_id)
        assert actual_child is not None
        with pytest.raises(DomainError) as hidden_history:
            memory(session, actual_child, readers={})
        assert hidden_history.value.code == "FORBIDDEN_SCOPE"
    denied = setup.client.get(path, headers=setup.headers)
    # The owner-goal projection keeps only the requester's recorded words when
    # native source RLS hides the Run; it never restores the historical answer.
    assert denied.status_code == 200, denied.text
    hidden = denied.json()
    assert hidden["goal"] == original_goal and hidden["status"] == "hidden"
    assert hidden["history_hidden"] is True and hidden["result"] is None
    assert hidden["versions"] == {} and hidden["process"] is None
    assert hidden["conversation"] == {
        "previous_run_id": None, "next_run_id": None, "links_unavailable": True,
    }
    assert all(value not in denied.text for value in (
        output["summary"], str(source_id), str(original_id),
    ))
