"""T2 fixture acceptance (D306, P95 第 5 项) feeding Build readiness, on isolated PG.

Synthetic people, imported fixture and qualifications only. Every write goes
through the real T2 preview and named approval; readiness is read back through
the existing operational bundle.
"""

# ruff: noqa: F811 - imported pytest fixtures are intentional

from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from builds.operational_facts.fixtures import (  # noqa: F401
    bundle,
    configuration,
    definition,
    fact_payload,
    imported,
    known_configuration,
    operational_work,
    project,
)
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError

from pdos_next.core.contracts import Command
from pdos_next.core.database import tenant_session
from pdos_next.core.models import Outbox, Product, Receipt, now
from pdos_next.core.service import Context
from pdos_next.domain.builds.operational_facts.schemas import FactInput
from pdos_next.domain.manufacturing.fixture_acceptance import service as acceptance
from pdos_next.domain.manufacturing.fixture_acceptance.models import FixtureAcceptanceVersion
from pdos_next.domain.manufacturing.fixture_acceptance.schemas import Payload
from pdos_next.errors import DomainError
from tests.d47_support import Professional, command, confirmed, get, headers_for, post, preview

OPERATION = "npi.fixture.accept"


@pytest.fixture
def fixture_work(operational_work):
    work = operational_work
    raw = fact_payload(work).model_dump(mode="json")
    raw["resources"][0]["resource"]["kind"] = "fixture"
    raw["resources"][0]["facts"] = []
    raw["requirements"][0]["uses"][0]["resource"]["kind"] = "fixture"
    imported(work, FactInput.model_validate(raw))
    work.professional = Professional(work.setup, work.config["project"], work.config["source"])
    work.professional.grant("manufacturing", [OPERATION], purpose=work.scope.purpose)
    yield work
    work.professional.close()


def scope(work, **changes):
    return {
        "build_id": work.build_id,
        "resource": {"id": str(work.resource_id), "revision": 1},
        "purpose": work.scope.purpose,
        "operation_id": "assembly",
        **changes,
    }


def accept(work, **changes):
    payload = {
        "action": "accept",
        "scope": scope(work),
        "valid_from": (work.at - timedelta(days=1)).isoformat(),
        "valid_until": (work.at + timedelta(days=2)).isoformat(),
        "conditions": ["首件确认后批量使用"],
        "reason": "治具首件尺寸合格",
        **changes,
    }
    return command(work.setup, OPERATION, payload)


def later(work, receipt, revision, action, **changes):
    return command(
        work.setup,
        OPERATION,
        {
            "acceptance": {"id": receipt["subject_id"], "revision": revision},
            "action": action,
            "reason": f"治具{action}",
            **changes,
        },
    )


def fixture_checks(work):
    report = bundle(work).resources
    return {
        check.code: check.status
        for check in report.checks
        if check.resource and check.resource.id == work.resource_id
    }


def test_accept_reject_revoke_flow_through_readiness(fixture_work):
    work, setup = fixture_work, fixture_work.setup
    assert fixture_checks(work).get("acceptance_missing") == "UNKNOWN"
    receipt, shown = confirmed(setup, accept(work))
    assert (
        shown["write_tier"] == "T2"
        and shown["named_decision"] is True
        and shown["review"]["roles"] == ["manufacturing"]
    )
    assert receipt["subject_type"] == "fixture_acceptance"
    checks = fixture_checks(work)
    assert "acceptance_missing" not in checks and "acceptance_invalid" not in checks
    with tenant_session(
        setup.engine, setup.tenant, actor_id=setup.human, category_id=setup.category
    ) as s:
        assert (
            s.scalar(select(Outbox.type).where(Outbox.receipt_id == UUID(receipt["id"])))
            == "fixture.accepted"
        )
    confirmed(setup, later(work, receipt, 1, "revoke"))
    assert fixture_checks(work).get("acceptance_invalid") == "BLOCKED"
    refused = preview(setup, later(work, receipt, 2, "revoke"))
    assert refused.status_code == 409 and refused.json()["code"] == "VALIDATION_FAILED"
    confirmed(
        setup,
        later(work, receipt, 2, "accept", valid_until=(work.at + timedelta(days=3)).isoformat()),
    )
    confirmed(setup, later(work, receipt, 3, "reject"))
    assert fixture_checks(work).get("acceptance_invalid") == "BLOCKED"
    listed = get(setup, f"projects/{work.config['project']}/fixture-acceptances").json()["items"]
    assert [(row["state"], row["revision"]) for row in listed] == [("rejected", 4)]
    assert [row["action"] for row in listed[0]["history"]] == [
        "reject",
        "accept",
        "revoke",
        "accept",
    ]


def test_validity_window_blocks_outside_its_range(fixture_work):
    work, setup = fixture_work, fixture_work.setup
    confirmed(setup, accept(work, valid_until=(work.at + timedelta(minutes=10)).isoformat()))
    assert any(
        code.startswith("acceptance_") and status == "BLOCKED"
        for code, status in fixture_checks(work).items()
    )


def test_refusals_role_scope_token_and_duplicates(fixture_work):
    work, setup = fixture_work, fixture_work.setup
    missing_token = post(setup, accept(work))
    assert missing_token.status_code in {403, 409} and missing_token.json()["code"] in {
        "NAMED_DECISION_REQUIRED",
        "CONFIRMATION_REQUIRED",
    }
    peer = preview(setup, accept(work), headers_for(setup, setup.peer))
    assert peer.status_code == 403  # the Build is private to its owner
    other_operation = preview(setup, accept(work, scope=scope(work, operation_id="painting")))
    assert (
        other_operation.status_code == 409 and other_operation.json()["code"] == "VALIDATION_FAILED"
    )
    unknown = preview(
        setup, accept(work, scope=scope(work, resource={"id": str(uuid4()), "revision": 1}))
    )
    assert unknown.status_code == 403
    stale = preview(
        setup,
        accept(work, scope=scope(work, resource={"id": str(work.resource_id), "revision": 2})),
    )
    assert stale.status_code == 409 and stale.json()["code"] == "VERSION_CONFLICT"
    receipt, shown = confirmed(setup, accept(work))
    replay = post(setup, shown["command"])
    assert replay.status_code == 200 and replay.json()["id"] == receipt["id"]
    duplicate = preview(setup, accept(work))
    assert duplicate.status_code == 409 and duplicate.json()["code"] == "VERSION_CONFLICT"
    other = preview(
        setup, accept(work), {"Authorization": f"Bearer {setup.tokens[setup.other_human]}"}
    )
    assert other.status_code in {401, 403}


def test_named_manufacturing_role_is_required(operational_work):
    work, setup = operational_work, operational_work.setup
    raw = fact_payload(work).model_dump(mode="json")
    raw["resources"][0]["resource"]["kind"] = "fixture"
    raw["resources"][0]["facts"] = []
    raw["requirements"][0]["uses"][0]["resource"]["kind"] = "fixture"
    imported(work, FactInput.model_validate(raw))
    professional = Professional(setup, work.config["project"], work.config["source"])
    try:
        refused = preview(setup, accept(work))
        assert refused.status_code == 403 and refused.json()["code"] == "QUALIFICATION_REQUIRED"
    finally:
        professional.close()


def test_equipment_is_not_accepted_here(operational_work):
    work, setup = operational_work, operational_work.setup
    imported(work)
    professional = Professional(setup, work.config["project"], work.config["source"])
    professional.grant("manufacturing", [OPERATION], purpose=work.scope.purpose)
    try:
        refused = preview(setup, accept(work))
        assert refused.status_code == 409 and refused.json()["code"] == "VALIDATION_FAILED"
    finally:
        professional.close()


def test_ai_cannot_decide_and_history_is_append_only(fixture_work):
    work, setup = fixture_work, fixture_work.setup
    cmd = Command.model_validate(accept(work))
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
        acceptance.validate(
            s, ctx, cmd, s.get(Product, setup.product), Payload.model_validate(cmd.payload)
        )
    assert failed.value.code == "NAMED_DECISION_REQUIRED"
    confirmed(setup, accept(work))
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
        s.execute(update(FixtureAcceptanceVersion).values(state="revoked"))
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
        s.execute(text("DELETE FROM fixture_acceptance_currents"))
    with tenant_session(
        setup.engine, setup.tenant, actor_id=setup.human, category_id=setup.category
    ) as s:
        assert (
            s.scalar(
                text(
                    "SELECT has_table_privilege('pdos_agent','fixture_acceptance_versions','SELECT')"  # noqa: E501
                )
            )
            is False
        )
        assert (
            s.scalar(
                select(func.count()).select_from(Receipt).where(Receipt.operation == OPERATION)
            )
            == 1
        )
    assert now()
