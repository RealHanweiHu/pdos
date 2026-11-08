"""M1 memory safety gates at the storage boundary (P84 第 7 项, P85, AT-71, AT-72).

No model or embedding calls. Every write here goes through the real roles and
row-level security of the isolated pdos_test database.
"""

from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pdos_next.agent.kernel.models import AgentRun
from pdos_next.agent.memory.models import MemoryEpisode
from pdos_next.core.database import tenant_session
from tests.agent.memory.support import episode, finish, start


def _insert_episode(session, setup, run_id, session_id, work_state_id):
    session.execute(text(
        "INSERT INTO memory_episodes(id,tenant_id,created_at,owner_id,session_id,run_id,"
        "work_state_id,work_state_revision,entry,status,goal,body,projection_version) "
        "VALUES (:id,:tenant,now(),:owner,:session,:run,:state,1,'web','completed',"
        "'伪造的记忆',CAST('{}' AS jsonb),'memory-episode/v1')"
    ), {"id": uuid4(), "tenant": setup.tenant, "owner": setup.human, "session": session_id,
        "run": run_id, "state": work_state_id})


def test_finish_projects_one_deterministic_episode_in_the_same_transaction(setup):
    run_id, started = start(setup)
    assert episode(setup, run_id) is None
    finish(setup, run_id)
    row = episode(setup, run_id)
    assert row is not None
    assert row.owner_id == setup.human and str(row.session_id) == started["session_id"]
    assert row.goal == "比较三家气泵供应商的报价和交期"
    assert row.status == "completed" and row.entry == "web"
    assert row.category_id == setup.category and row.project_id is None
    assert row.projection_version == "memory-episode/v1"
    assert row.body["model_notes"] == {"unfinished": ["核对交期单位"], "questions": []}
    assert row.body["retrieval"]["enterprise"] == "none"
    assert {"focus_objects", "receipts", "candidates", "skills", "citations", "usage"} <= set(
        row.body
    )
    # No answer body is copied into memory (P85 第 1 项).
    assert "合成结果" not in str(row.body)
    with Session(setup.admin) as session:
        assert session.scalar(select(func.count()).where(MemoryEpisode.run_id == run_id)) == 1
        assert session.get(AgentRun, run_id).state == "completed"


@pytest.mark.parametrize("actor", ["agent", "human"])
def test_no_runtime_identity_can_write_or_change_an_episode(setup, actor):
    run_id, started = start(setup)
    finish(setup, run_id)
    row = episode(setup, run_id)
    other_run, other = start(setup)
    actor_id = setup.agent if actor == "agent" else setup.human
    with pytest.raises(DBAPIError, match="permission denied"):
        with tenant_session(setup.engine, setup.tenant, actor_id=actor_id,
                            requester_id=setup.human, category_id=setup.category) as session:
            _insert_episode(session, setup, other_run, other["session_id"], row.work_state_id)
    for statement in ("UPDATE memory_episodes SET goal='改写' WHERE id=:id",
                      "DELETE FROM memory_episodes WHERE id=:id"):
        with pytest.raises(DBAPIError, match="permission denied"):
            with tenant_session(setup.engine, setup.tenant, actor_id=actor_id,
                                requester_id=setup.human, category_id=setup.category) as session:
                session.execute(text(statement), {"id": row.id})
    assert episode(setup, run_id).goal == "比较三家气泵供应商的报价和交期"
    assert episode(setup, other_run) is None


def _mark(session, setup, row, kind="pin"):
    session.execute(text(
        "INSERT INTO memory_episode_marks(id,tenant_id,created_at,owner_id,session_id,episode_id,"
        "kind,body,request_key,request_sha256) VALUES (:id,:tenant,now(),:owner,:session,:episode,"
        ":kind,CAST('{}' AS jsonb),:key,repeat('a',64))"
    ), {"id": uuid4(), "tenant": setup.tenant, "owner": row.owner_id, "session": row.session_id,
        "episode": row.id, "kind": kind, "key": uuid4()})


def _index(session, setup, row):
    session.execute(text(
        "INSERT INTO memory_index(id,tenant_id,created_at,owner_id,session_id,episode_id,"
        "source_kind,source_version,profile_version,idempotency_key,terms,term_counts,codes,"
        "token_count,tokenizer_version,code_rule_version) VALUES (:id,:tenant,now(),:owner,"
        ":session,:episode,'episode',1,'none',:key,to_tsvector('simple','供应商'),"
        "CAST('{}' AS jsonb),ARRAY[]::text[],1,'t','c')"
    ), {"id": uuid4(), "tenant": setup.tenant, "owner": row.owner_id, "session": row.session_id,
        "episode": row.id, "key": uuid4().hex + uuid4().hex})


@pytest.mark.parametrize("write", [_mark, _index])
def test_marks_and_index_accept_only_the_human_owner_for_themself(setup, write):
    run_id, _ = start(setup)
    finish(setup, run_id)
    row = episode(setup, run_id)
    # AI writer identity acting for the owner: refused by the database (AT-72).
    with pytest.raises(DBAPIError, match="row-level security"):
        with tenant_session(setup.engine, setup.tenant, actor_id=setup.agent,
                            requester_id=setup.human, category_id=setup.category) as session:
            write(session, setup, row)
    # Another person cannot write into the owner's memory.
    with pytest.raises(DBAPIError, match="row-level security"):
        with tenant_session(setup.engine, setup.tenant, actor_id=setup.peer,
                            category_id=setup.category) as session:
            write(session, setup, row)
    with tenant_session(setup.engine, setup.tenant, actor_id=setup.human,
                        category_id=setup.category) as session:
        write(session, setup, row)


def test_other_people_and_the_ai_without_the_owner_never_read_episodes(setup):
    run_id, _ = start(setup)
    finish(setup, run_id)
    for actor, requester in ((setup.peer, setup.peer), (setup.agent, setup.peer),
                             (setup.agent, setup.agent)):
        with tenant_session(setup.engine, setup.tenant, actor_id=actor, requester_id=requester,
                            category_id=setup.category) as session:
            assert session.scalar(select(func.count()).select_from(MemoryEpisode)) == 0
    with tenant_session(setup.engine, setup.tenant, actor_id=setup.agent,
                        requester_id=setup.human, category_id=setup.category) as session:
        assert session.scalar(select(func.count()).select_from(MemoryEpisode)) == 1


def test_memory_off_session_records_no_episode(setup):
    run_id, started = start(setup, memory_off=True)
    finish(setup, run_id)
    assert episode(setup, run_id) is None
    follow, _ = start(setup, continue_from_run_id=str(run_id), goal="继续比较交期")
    finish(setup, follow)
    assert episode(setup, follow) is None
    with Session(setup.admin) as session:
        assert session.get(AgentRun, run_id).versions["memory_mode"] == {"off": True}
