"""T2 alternate approval (D308, P96 第 5–7 项) feeding one Build's kit, on isolated PG.

The reviewed test run comes from the real results chain; the kit is recomputed
through the real supply snapshot and kit commands. All facts are synthetic.
"""

# ruff: noqa: F811, E501 - imported pytest fixtures are intentional

from datetime import timedelta
from uuid import UUID

import pytest
from projects.test_project_first_plan import accepted as accepted_cmd
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError
from verification.results.fixtures import (  # noqa: F401
    accepted_work,
    capture,
    known_configuration,
    launch_work,
    operational_work,
    ready_work,
    results_work,
)
from verification.results.fixtures import (
    command as result_command,
)

from manufacturing.test_supply_execution import kit_command, recorded
from pdos_next.core.contracts import Command
from pdos_next.core.database import tenant_session
from pdos_next.core.models import Product, Receipt, now
from pdos_next.core.service import Context
from pdos_next.domain.manufacturing.alternate_approvals import service as approvals
from pdos_next.domain.manufacturing.alternate_approvals.models import AlternateApprovalVersion
from pdos_next.domain.manufacturing.alternate_approvals.schemas import Payload
from pdos_next.domain.manufacturing.supply_execution.models import KitProjection
from pdos_next.domain.verification.launch.models import VerificationRunCurrent
from pdos_next.errors import DomainError
from tests.d47_support import Professional, command, confirmed, get, post, preview

OPERATION = "supply.alternate.approve"
ALTERNATE = "RD-MOTOR-ALT-1"


def reviewed_run(work):
    first, _ = capture(work, (0,))
    accepted_cmd(work.quality, result_command(work, "test.results.import", captured=first))
    second, _ = capture(work, (1,))
    accepted_cmd(
        work.quality, result_command(work, "test.results.import", captured=second, final=True)
    )
    computed = post(work.quality, result_command(work, "test.result.compute"))
    assert computed.status_code == 200, computed.text
    accepted_cmd(work.quality, result_command(work, "test.run.review"))
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.setup.human,
        category_id=work.setup.category,
    ) as s:
        pointer = s.scalar(
            select(VerificationRunCurrent).where(
                VerificationRunCurrent.run_id == work.binding.run_id
            )
        )
        return {"id": str(pointer.run_id), "revision": pointer.run_revision}


def build_visibility(setup, build_id):
    from pdos_next.domain.builds.models import Build

    with tenant_session(
        setup.engine, setup.tenant, actor_id=setup.human, category_id=setup.category
    ) as s:
        return s.get(Build, UUID(str(build_id))).visibility


@pytest.fixture
def alternate_work(setup, results_work):
    from manufacturing.test_supply_execution import TEXT

    run = reviewed_run(results_work)
    source = post(
        setup,
        command(
            setup,
            "evidence.artifact.register",
            {
                "title": "Synthetic unverified warehouse observation",
                "content": TEXT,
                "source_label": "Synthetic",
                "visibility": build_visibility(setup, results_work.build_id),
            },
        ),
    )
    assert source.status_code == 200, source.text
    supply = {**results_work.config, "supply_source": source.json()["subject_id"]}
    professional = Professional(
        setup, results_work.config["project"], results_work.config["source"]
    )
    professional.grant("engineering", [OPERATION])
    yield {"supply": supply, "run": run, "results": results_work}
    professional.close()


def approve(setup, work, **changes):
    payload = {
        "action": "approve",
        "scope": {
            "build_id": work["supply"]["build_id"],
            "expected_build_revision": 1,
            "item_id": "motor",
            "alternate_material_id": ALTERNATE,
            "alternate_unit": "ea",
            "alternate_quantity_per_target": "1",
        },
        "evidence_run": work["run"],
        "valid_until": (now() + timedelta(days=5)).isoformat(),
        "reason": "替代电机经复测通过，本轮试制可用",
        **changes,
    }
    return command(setup, OPERATION, payload)


def later(setup, receipt, revision, action, **changes):
    return command(
        setup,
        OPERATION,
        {
            "approval": {"id": receipt["subject_id"], "revision": revision},
            "action": action,
            "reason": f"替代料{action}",
            **changes,
        },
    )


def kit_alternates(setup, work):
    capture_value, saved, _ = recorded(setup, work["supply"])
    result = post(
        setup,
        kit_command(setup, work["supply"], saved, reads=capture_value["required_source_read_set"]),
    )
    assert result.status_code == 200, result.text
    with tenant_session(
        setup.engine, setup.tenant, actor_id=setup.human, category_id=setup.category
    ) as s:
        kit = s.get(KitProjection, UUID(result.json()["subject_id"]))
        return [row["qualification_id"] for row in kit.projection["verified_alternates"]]


def test_approval_enters_only_this_builds_kit_and_revocation_removes_it(setup, alternate_work):
    work = alternate_work
    assert kit_alternates(setup, work) == []
    receipt, shown = confirmed(setup, approve(setup, work))
    review = shown["review"]
    assert shown["write_tier"] == "T2" and review["roles"] == ["engineering"]
    assert (
        review["after"]["target_material_id"]
        and review["after"]["evidence_run"]["status"] == "reviewed"
    )
    with tenant_session(
        setup.engine, setup.tenant, actor_id=setup.human, category_id=setup.category
    ) as s:
        version = s.scalar(
            select(AlternateApprovalVersion.id).where(
                AlternateApprovalVersion.record_id == UUID(receipt["subject_id"])
            )
        )
    assert kit_alternates(setup, work) == [str(version)]
    listed = get(setup, f"builds/{work['supply']['build_id']}/alternate-approvals").json()["items"]
    assert [(row["state"], row["revision"]) for row in listed] == [("approved", 1)]
    confirmed(setup, later(setup, receipt, 1, "revoke"))
    assert kit_alternates(setup, work) == []
    again = preview(setup, later(setup, receipt, 2, "revoke"))
    assert again.status_code == 422 or again.json()["code"] == "VALIDATION_FAILED"


def test_refusals_evidence_role_scope_and_duplicates(setup, alternate_work):
    work = alternate_work
    no_evidence = preview(setup, approve(setup, work, evidence_run=None))
    assert no_evidence.status_code == 422
    stale_run = preview(
        setup,
        approve(setup, work, evidence_run={**work["run"], "revision": work["run"]["revision"] - 1}),
    )
    assert stale_run.status_code == 409 and stale_run.json()["code"] in {
        "VERSION_CONFLICT",
        "MISSING_REQUIRED_EVIDENCE",
    }
    same = preview(
        setup,
        approve(
            setup,
            work,
            scope={**approve(setup, work)["payload"]["scope"], "alternate_material_id": None},
        ),
    )
    assert same.status_code == 422
    unknown_line = preview(
        setup,
        approve(
            setup, work, scope={**approve(setup, work)["payload"]["scope"], "item_id": "housing-x"}
        ),
    )
    assert unknown_line.status_code == 403
    peer = preview(
        setup, approve(setup, work), {"Authorization": f"Bearer {setup.tokens[setup.peer]}"}
    )
    assert peer.status_code == 403
    receipt, shown = confirmed(setup, approve(setup, work))
    assert post(setup, shown["command"]).json()["id"] == receipt["id"]
    duplicate = preview(setup, approve(setup, work))
    assert duplicate.status_code == 409 and duplicate.json()["code"] == "VERSION_CONFLICT"


def test_ai_cannot_approve_and_history_is_append_only(setup, alternate_work):
    work = alternate_work
    cmd = Command.model_validate(approve(setup, work))
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
        approvals.validate(
            s, ctx, cmd, s.get(Product, setup.product), Payload.model_validate(cmd.payload)
        )
    assert failed.value.code == "NAMED_DECISION_REQUIRED"
    confirmed(setup, approve(setup, work))
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
        s.execute(update(AlternateApprovalVersion).values(state="revoked"))
    with tenant_session(
        setup.engine, setup.tenant, actor_id=setup.human, category_id=setup.category
    ) as s:
        assert (
            s.scalar(
                text(
                    "SELECT has_table_privilege('pdos_agent','alternate_approval_versions','SELECT')"
                )
            )
            is False
        )  # noqa: E501
        assert (
            s.scalar(
                select(func.count()).select_from(Receipt).where(Receipt.operation == OPERATION)
            )
            == 1
        )
