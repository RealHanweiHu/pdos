"""Browser walk seed for D37 ⑤ (run explicitly; never collected as a test).

Creates, through the same public commands the PG tests use, one private G0
project whose team is the synthetic owner + peer, a task assigned to the peer
that they accepted and started, a category member 王岚 outside the project, and
one topic in which the owner mentions the peer. Logins and grants keep the
fixture's one-hour window (changing people or grants re-checks original scans).
Tokens go to ``$D37_SEED_OUT`` (0600, outside the repository), never printed.

    TEST_DATABASE_URL=... D37_SEED_OUT=/path/seed.json \\
      python -m pytest tests/projects/discussions_pg/browser_seed_d37.py -q
"""

# ruff: noqa: F811

import json
import os
from hashlib import sha256
from pathlib import Path

from g0_fixture import add_category_human

from pdos_next.domain.projects.work.constants import ACCEPT, ASSIGN, START
from projects.discussions_pg import helpers as h
from projects.discussions_pg.test_handover_and_tasks import (  # noqa: F401
    _send,
    _task,
    private_work,
)
from projects.test_project_first_plan import cmd, post
from projects.work_pg import test_workflow as flow
from projects.work_pg.test_workflow import original_security_work  # noqa: F401


def test_seed_browser_walk(private_work):
    work, setup = private_work, private_work.setup
    owner, peer = setup.human, setup.peer
    third = add_category_human(setup, name="王岚")
    # A registered synthetic note (no uploaded original) as the task source, so the
    # browser's API process does not depend on the fixture scanner's configuration.
    line = "合成图纸要求：结构图纸须标注第 3 页公差。"
    registered = post(
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
    _send(
        work,
        START,
        flow.payload(work, task=flow.task(work, "accepted"), **flow.clock_fields()),
        actor=peer,
    )
    h.start_topic(
        setup,
        work.g0,
        owner,
        "EVT 样机评审安排",
        f"{h.mention(peer, 'Synthetic peer')} 周五前确认样机数量和送样时间",
    )
    out = Path(os.environ["D37_SEED_OUT"])
    out.write_text(
        json.dumps(
            {
                "tokens": {
                    "owner": setup.tokens[owner],
                    "peer": setup.tokens[peer],
                    "third": setup.tokens[third],
                },
                "tenant": str(setup.tenant),
                "category": str(setup.category),
                "product": work.g0.product_id,
                "project": work.g0.project_id,
                "task": str(task_id),
                "owner": str(owner),
                "peer": str(peer),
            }
        )
    )
    out.chmod(0o600)
