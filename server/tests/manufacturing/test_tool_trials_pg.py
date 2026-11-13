"""D305 tool trial on the isolated PG (P95 第 1–4 项与两条补充确认).

The named person here is a manufacturing person: the fixture withdraws their
synthetic quality duty and grants a manufacturing duty for the tool trial only.
Everything is local and synthetic; no real qualification is implied.
"""

# ruff: noqa: F811 - pytest fixtures are imported by name

from uuid import UUID, uuid4

import pytest
from builds.test_build_execution import actual, lot, planned  # noqa: F401
from builds.test_builds import configuration, definition, project  # noqa: F401
from builds.test_builds import listed as listed_builds
from projects.test_project_first_plan import cmd
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from verification.preparation.fixtures import (
    create_command,
    current_preparation,
    front_work,  # noqa: F401 - imported pytest fixture
    import_fact,
    listed,
    send,
)
from verification.test_verification_execution import verification_work  # noqa: F401

from pdos_next.core.contracts import Command
from pdos_next.core.database import tenant_session
from pdos_next.core.models import Product, Receipt
from pdos_next.core.service import Context
from pdos_next.domain.manufacturing.tool_trials import service as trials
from pdos_next.domain.manufacturing.tool_trials.models import (
    ToolingCurrent,
    ToolingVersion,
    ToolTrialVersion,
)
from pdos_next.domain.manufacturing.tool_trials.schemas import OPERATION, Payload
from pdos_next.domain.verification.preparation.models import FormalVerificationRequest
from pdos_next.errors import DomainError
from tests.d47_support import confirmed, post, preview


@pytest.fixture
def manufacturing_work(front_work):
    work, setup = front_work, front_work.setup
    for kind in ("duty", "qualification"):
        import_fact(
            work,
            kind,
            previous=work.facts[kind],
            state="withdrawn" if kind == "duty" else "revoked",
        )
        work.facts[kind] = import_fact(
            work,
            kind,
            external_id=f"SYN-{kind}-manufacturing-{setup.human}",
            role="manufacturing",
            operations=[OPERATION],
        )
    return work


def build_ref(work):
    build_id = work.work["build"]["subject_id"]
    row = next(item for item in listed_builds(work.setup)["items"] if item["id"] == build_id)
    return {"id": build_id, "revision": row["revision"]}


def trial(work, *, tooling_new=None, tooling=None, round_label="T0"):
    prep = current_preparation(work)
    payload = {
        "build": build_ref(work),
        "trial": {
            "round": round_label,
            "purpose": "Synthetic trial: appearance and key dimensions",
            "material_lots": ["SYN-LOT-1"],
            "parameters": [{"name": "Holding pressure", "value": "60", "unit": "MPa"}],
            "cavities": [1, 2],
            "issues": ["Synthetic flash at the gate"],
            "corrective_actions": ["Synthetic tool rework before the next round"],
        },
        "verification": {
            "request_id": str(uuid4()),
            "preparation_id": prep["id"],
            "expected_preparation_revision": prep["revision"],
            "preparation_sha256": prep["sha256"],
            "reason": "Synthetic request from the tool trial",
        },
        "reason": "Synthetic tool trial, no ERP or MES change",
    }
    if tooling is None:
        payload["tooling_new"] = tooling_new or {
            "part": "SYN-HOUSING",
            "version": "A0",
            "supplier_ref": "SUP-TOOL-001",
            "cavities": 2,
        }
    else:
        payload["tooling"] = tooling
    command = cmd(work.setup, OPERATION, payload)
    command["source_read_set"] = prep["required_source_read_set"]
    return command


def trials_view(work):
    setup = work.setup
    response = setup.client.get(
        f"/v1/categories/{setup.category}/products/{setup.product}/builds/{build_ref(work)['id']}/tool-trials",
        headers=setup.headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def count(work, model, *where):
    setup = work.setup
    with tenant_session(
        setup.engine, setup.tenant, actor_id=setup.human, category_id=setup.category
    ) as s:
        return s.scalar(select(func.count()).select_from(model).where(*where))


def test_manufacturing_person_trial_creates_tooling_trial_and_request(manufacturing_work):
    work, setup = manufacturing_work, manufacturing_work.setup
    command = trial(work)
    receipt, shown = confirmed(setup, command)
    review = shown["review"]
    assert review["tooling"]["action"] == "create" and review["roles"] == ["manufacturing"]
    assert review["verification_request"]["preparation"]["id"] == work.preparation["id"]
    assert receipt["subject_type"] == "tool_trial"
    view = trials_view(work)
    assert len(view["items"]) == 1 and len(view["tooling"]) == 1
    item, tooling = view["items"][0], view["tooling"][0]
    assert item["tooling"] == {
        "id": tooling["id"],
        "revision": 1,
        "part": "SYN-HOUSING",
        "version": "A0",
    }
    assert item["request_id"] == command["payload"]["verification"]["request_id"]
    request = next(
        row for row in listed(work)["requests"] if row["request_id"] == item["request_id"]
    )
    assert request["operation"] == "verification.request.create" and request["revision"] == 1
    assert request["preparation_id"] == work.preparation["id"]
    # The same confirmed command replays to the same receipt and writes nothing new.
    replay = post(setup, shown["command"])
    assert replay.status_code == 200, replay.text
    assert replay.json()["id"] == receipt["id"]
    assert count(work, ToolTrialVersion) == 1 and count(work, ToolingVersion) == 1
    assert (
        count(
            work,
            FormalVerificationRequest,
            FormalVerificationRequest.request_id == UUID(item["request_id"]),
        )
        == 1
    )


def test_manufacturing_person_standalone_request_is_still_refused(manufacturing_work):
    work = manufacturing_work
    # verification.request.create executes directly (no preview path).
    refused = send(work, create_command(work))
    assert refused.status_code == 403, refused.text
    assert refused.json()["detail"]["reason"] == "FORBIDDEN_OPERATION", refused.text
    assert listed(work)["requests"] == []


def test_second_trial_revises_changed_tooling(manufacturing_work):
    work, setup = manufacturing_work, manufacturing_work.setup
    confirmed(setup, trial(work))
    tooling = trials_view(work)["tooling"][0]
    unchanged = trial(
        work,
        tooling={"id": tooling["id"], "revision": 1, "changes": {"version": "A0"}},
        round_label="T1",
    )
    refused = preview(setup, unchanged)
    assert refused.status_code == 409 and refused.json()["code"] == "VALIDATION_FAILED"
    stale = trial(work, tooling={"id": tooling["id"], "revision": 2}, round_label="T1")
    refused = preview(setup, stale)
    assert refused.status_code == 409 and refused.json()["code"] == "VERSION_CONFLICT"
    _, shown = confirmed(
        setup,
        trial(
            work,
            tooling={"id": tooling["id"], "revision": 1, "changes": {"version": "A1"}},
            round_label="T1",
        ),
    )
    assert shown["review"]["tooling"]["action"] == "revise"
    view = trials_view(work)
    assert [row["tooling"]["revision"] for row in view["items"]] == [2, 1]
    assert [row["tooling"]["version"] for row in view["items"]] == ["A1", "A0"]
    assert view["tooling"][0]["version"] == "A1" and view["tooling"][0]["revision"] == 2
    # Referencing the tooling without a change writes no tooling version.
    confirmed(setup, trial(work, tooling={"id": tooling["id"], "revision": 2}, round_label="T2"))
    assert count(work, ToolingVersion) == 2 and count(work, ToolTrialVersion) == 3


def test_refusals_ai_and_append_only(manufacturing_work):
    work, setup = manufacturing_work, manufacturing_work.setup
    stale_build = trial(work)
    stale_build["payload"]["build"]["revision"] += 1
    refused = preview(setup, stale_build)
    assert refused.status_code == 409 and refused.json()["code"] == "VERSION_CONFLICT"
    both = trial(work)
    both["payload"]["tooling"] = {"id": str(uuid4()), "revision": 1}
    refused = preview(setup, both)
    assert refused.status_code == 422, refused.text
    stale_prep = trial(work)
    stale_prep["payload"]["verification"]["expected_preparation_revision"] += 1
    refused = preview(setup, stale_prep)
    assert refused.status_code in {409, 422} and refused.json()["code"] != "OK"
    command = Command.model_validate(trial(work))
    ctx = Context(setup.tenant, setup.agent, setup.human, category_id=setup.category)
    with (
        pytest.raises(DomainError) as failed,
        tenant_session(
            setup.engine,
            setup.tenant,
            actor_id=ctx.actor_id,
            requester_id=ctx.requester_id,
            category_id=setup.category,
        ) as s,
    ):
        trials.validate(
            s, ctx, command, s.get(Product, setup.product), Payload.model_validate(command.payload)
        )
    assert failed.value.code == "NAMED_DECISION_REQUIRED"
    confirmed(setup, trial(work))
    for statement in (
        "UPDATE tool_trial_versions SET state=state",
        "DELETE FROM tooling_currents",
    ):
        with (
            pytest.raises(DBAPIError),
            tenant_session(
                setup.engine,
                setup.tenant,
                actor_id=setup.human,
                requester_id=setup.human,
                category_id=setup.category,
            ) as s,
        ):
            s.execute(text(statement))
    with tenant_session(
        setup.engine, setup.tenant, actor_id=setup.human, category_id=setup.category
    ) as s:
        for table in ("tooling_versions", "tool_trial_versions"):
            assert (
                s.scalar(text(f"SELECT has_table_privilege('pdos_agent','{table}','SELECT')"))
                is False
            )
        assert (
            s.scalar(
                select(func.count()).select_from(Receipt).where(Receipt.operation == OPERATION)
            )
            == 1
        )
        assert trials.trial_for_request(s, setup.ctx, setup.product, uuid4()) is None
        current = s.scalars(select(ToolingCurrent)).all()
        assert len(current) == 1 and current[0].revision == 1
