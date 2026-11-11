"""Browser walk seed for D37 ⑥ (run explicitly; never collected as a test).

Same fixtures as the PG tests: a private G0 project whose team is the synthetic
owner + peer, a task assigned to the peer, and four @小Pai requests in their states:
a public reply, a private reply (the source is the peer's own private note), one
still running, and a task-comment run waiting for information (P105). Runs are
ended by the test-only stand-in (no model is called); delivery is the real host.
Tokens go to ``$D37_SEED_OUT`` (0600, outside the repository), never printed.

    TEST_DATABASE_URL=... D37_SEED_OUT=/path/seed.json \\
      python -m pytest tests/projects/discussions_pg/browser_seed_d37_6.py -q
"""

# ruff: noqa: F811

import asyncio
import json
import os
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from sqlalchemy.orm import Session

from pdos_next.core.models import Artifact
from pdos_next.domain.projects.discussions import agent_delivery
from pdos_next.domain.projects.work.constants import ACCEPT, ASSIGN
from projects.discussions_pg import helpers as h
from projects.discussions_pg.test_agent_thread import (
    XIAOPAI,
    _Client,
    _wait,
    deliver,
    finish,
    post,
    post_topic,
    requests,
)
from projects.discussions_pg.test_handover_and_tasks import (  # noqa: F401
    _send,
    _task,
    private_work,
)
from projects.test_project_first_plan import cmd
from projects.test_project_first_plan import post as command
from projects.work_pg import test_workflow as flow
from projects.work_pg.test_workflow import original_security_work  # noqa: F401


def _note(setup, project, owner, title, *, visibility):
    identity = uuid4()
    with Session(setup.admin) as s, s.begin():
        s.add(
            Artifact(
                id=identity,
                tenant_id=setup.tenant,
                category_id=setup.category,
                product_id=project.product_id,
                owner_id=owner,
                title=title,
                source_label="本地合成样例",
                content=title,
                content_hash="0" * 64,
                visibility=visibility,
                revision=1,
                status="active",
            )
        )
    return {"artifact_id": str(identity), "expected_revision": 1, "product_id": project.product_id}


def test_seed_browser_walk(private_work):
    work, setup = private_work, private_work.setup
    owner, peer = setup.human, setup.peer
    line = "合成图纸要求：结构图纸须标注第 3 页公差。"
    registered = command(
        setup,
        cmd(
            setup,
            "evidence.artifact.register",
            {
                "title": "合成图纸要求",
                "content": line,
                "source_label": "本地合成样例",
                "visibility": "category",
            },
        ),
    )
    assert registered.status_code == 200, registered.text
    work.source = {
        "kind": "artifact",
        "id": registered.json()["subject_id"],
        "revision": 1,
        "position": "line:1;quote_sha256:" + sha256(line.encode()).hexdigest(),
    }
    task_id = _task(work, "样机结构图纸 v2")
    _send(
        work,
        ASSIGN,
        flow.payload(
            work, task=flow.task(work, "proposed"), assignee_id=str(peer), recipient_id=str(owner)
        ),
        actor=owner,
    )
    _send(work, ACCEPT, flow.payload(work, task=flow.task(work, "assigned")), actor=peer)
    project = work.g0
    shared = _note(setup, project, owner, "EVT 评审资料清单", visibility="category")
    private = _note(setup, project, peer, "供应商报价（本人笔记）", visibility="private")

    topic = post_topic(
        setup,
        project,
        owner,
        f"{h.mention(peer, 'Synthetic peer')} 周五前确认样机数量和送样时间",
        title="EVT 样机评审安排",
    )["thread"]["id"]
    post(setup, project, owner, topic, f"{XIAOPAI} 帮我整理评审前还缺哪些资料")
    public = requests(setup, topic)[-1]
    finish(
        setup,
        public.run_id,
        "评审前还缺 3 项：\n1. 结构图纸 v2 的公差标注（第 3 页）；\n"
        "2. 样机数量确认；\n3. 送样时间。",
        read_sources=[shared],
    )
    deliver(setup, public.id)
    post(setup, project, peer, topic, f"{XIAOPAI} 我的报价笔记里单价合理吗")
    hidden = requests(setup, topic)[-1]
    finish(
        setup,
        hidden.run_id,
        "按你的笔记，单价比上一轮低 4%，在目标区间内。",
        read_sources=[private],
    )
    deliver(setup, hidden.id)
    post(setup, project, owner, topic, f"{XIAOPAI} 再列一下评审风险")  # stays running

    h.comment(setup, project, owner, "work_task", task_id, f"{XIAOPAI} 这张图纸还缺什么")
    waiting = [row for row in requests_by_task(setup, task_id)][-1]
    _wait(setup, waiting.run_id, 2)
    client = _Client()
    asyncio.run(
        agent_delivery.dispatch_pending(setup.dispatch, setup.tenant, client, task_queue="seed")
    )
    for reference, _ in client.started:
        agent_delivery.execute(setup.engine, setup.dispatch, reference)

    out = Path(os.environ["D37_SEED_OUT"])
    out.write_text(
        json.dumps(
            {
                "tokens": {"owner": setup.tokens[owner], "peer": setup.tokens[peer]},
                "category": str(setup.category),
                "product": project.product_id,
                "project": project.project_id,
                "task": str(task_id),
                "topic": topic,
            }
        )
    )
    out.chmod(0o600)


def requests_by_task(setup, task_id):
    from sqlalchemy import select

    from pdos_next.domain.projects.discussions.models import (
        DiscussionAgentRequest,
        DiscussionThread,
    )

    with Session(setup.admin) as s:
        return list(
            s.scalars(
                select(DiscussionAgentRequest)
                .join(DiscussionThread, DiscussionThread.id == DiscussionAgentRequest.thread_id)
                .where(DiscussionThread.subject_id == task_id)
            )
        )
