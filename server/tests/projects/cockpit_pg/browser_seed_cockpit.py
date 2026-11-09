"""Browser walk seed for D37 ⑦ (run explicitly; never collected as a test).

Builds, through the same public commands the PG tests use, two category-shared G0
projects in one category:

- 便携充气泵 P1: standard@1 adopted and the 概念 review submitted (待批准, a stage
  decision for the owner), one task assigned to the peer (待接收), one task the peer
  accepted with a promise to the owner due in three days (关键承诺 / 未来 7 天到期),
  a named status update, and membership in the project set 便携充气产品线;
- 气垫泵 S2: no stage template (待核对), with its G0 risks and to-dos.

Tokens go to ``$D37_SEED_OUT`` (0600, outside the repository), never printed.

    TEST_DATABASE_URL=... D37_SEED_OUT=/path/seed.json \\
      python -m pytest tests/projects/cockpit_pg/browser_seed_cockpit.py -q
"""

# ruff: noqa: F811

import json
import os
from datetime import timedelta
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

from g0_fixture import create_g0_project

from pdos_next.core.models import now
from pdos_next.domain.projects.work.constants import ACCEPT, ASSIGN, COMMIT, STATUS
from projects.discussions_pg.test_handover_and_tasks import _send, _task
from projects.test_project_first_plan import accepted, cmd, post
from projects.work_pg import test_workflow as flow
from projects.work_pg.test_workflow import original_security_work, work  # noqa: F401


def _register(setup, title, line, visibility="category"):
    registered = post(
        setup,
        cmd(
            setup,
            "evidence.artifact.register",
            {
                "title": title,
                "content": line,
                "source_label": "本地合成样例",
                "visibility": visibility,
            },
        ),
    )
    assert registered.status_code == 200, registered.text
    return registered.json()["subject_id"]


def _governance(setup, project, operation, revision, source, **fields):
    return cmd(
        setup,
        operation,
        {
            "project_id": str(project),
            "expected_project_revision": 1,
            "expected_governance_revision": revision,
            "reason": "核对合成项目实际资料后办理",
            **fields,
        },
        source,
    )


def test_seed_cockpit_walk(work):
    setup, owner, peer = work.setup, work.setup.human, work.setup.peer
    line = "合成图纸要求：结构图纸须标注第 3 页公差。"
    artifact = _register(setup, "合成图纸要求", line)
    work.source = {
        "kind": "artifact",
        "id": artifact,
        "revision": 1,
        "position": "line:1;quote_sha256:" + sha256(line.encode()).hexdigest(),
    }
    first_product = setup.product

    drawing = _task(work, "样机结构图纸 v2")
    _send(
        work,
        ASSIGN,
        flow.payload(
            work, task=flow.task(work, "proposed"), assignee_id=str(peer), recipient_id=str(owner)
        ),
        actor=owner,
    )
    noise = _task(work, "噪声复测方案")
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
        COMMIT,
        flow.payload(
            work,
            task=flow.task(work, "accepted"),
            recipient_id=str(owner),
            outcome_keys=["drawing"],
            promised_at=(now() + timedelta(days=3)).isoformat(),
            original_timezone=flow.TIMEZONE,
            calendar_id=None,
            replaces=None,
        ),
        actor=peer,
    )
    _send(
        work,
        STATUS,
        flow.payload(
            work,
            fact_summary="样机结构图纸已分派，噪声复测方案已承接并承诺三天内交付。概念评审已提交。",
            next_steps="负责人完成概念阶段具名决定；同事承接结构图纸。",
            task_refs=[flow.task(work, "accepted")],
        ),
        actor=owner,
    )

    source = _register(setup, "合成阶段依据", "合成概念评审依据，未经核实。", "private")
    accepted(
        setup,
        _governance(setup, work.project_id, "work.stage.adopt", 0, source, template="standard@1"),
    )
    governance = setup.client.get(
        f"/v1/categories/{setup.category}/products/{first_product}/projects/{work.project_id}/governance",
        headers=setup.headers,
    ).json()
    accepted(
        setup,
        _governance(
            setup,
            work.project_id,
            "work.stage.review.submit",
            1,
            source,
            stage_id=governance["current_stage"]["id"],
        ),
    )

    saved = setup.client.post(
        "/v1/project-sets",
        headers=setup.headers,
        json={
            "name": "便携充气产品线",
            "description": "车载与便携充气泵的在研项目",
            "expected_revision": 0,
            "request_key": str(uuid4()),
        },
    )
    assert saved.status_code == 200, saved.text
    moved = setup.client.post(
        "/v1/project-sets/move",
        headers=setup.headers,
        json={
            "set_id": saved.json()["id"],
            "projects": [{"project_id": str(work.project_id), "expected_revision": 0}],
            "request_key": str(uuid4()),
        },
    )
    assert moved.status_code == 200, moved.text
    second = create_g0_project(
        setup, visibility="category", name="气垫泵 S2", purpose="派生气垫泵的结构与接口验证"
    )

    out = Path(os.environ["D37_SEED_OUT"])
    out.write_text(
        json.dumps(
            {
                "tokens": {"owner": setup.tokens[owner], "peer": setup.tokens[peer]},
                "tenant": str(setup.tenant),
                "category": str(setup.category),
                "first": {"product": str(first_product), "project": str(work.project_id)},
                "second": {"product": second.product_id, "project": second.project_id},
                "tasks": [str(UUID(str(drawing))), str(UUID(str(noise)))],
                "set": saved.json()["id"],
            }
        )
    )
    out.chmod(0o600)
