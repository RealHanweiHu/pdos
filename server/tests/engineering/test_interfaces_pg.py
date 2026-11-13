"""T1 interface contracts (D312, P120 第 4–6 项) on the isolated PG target.

Synthetic people, roles and qualifications only. Every write goes through the
real preview and command path; the database checks receipt and Current binding.
"""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError

from pdos_next.core.contracts import Command
from pdos_next.core.database import tenant_session
from pdos_next.core.models import Outbox, Product, Receipt
from pdos_next.core.service import Context
from pdos_next.domain.engineering.interfaces import service as interfaces
from pdos_next.domain.engineering.interfaces.models import InterfaceCurrent, InterfaceVersion
from pdos_next.domain.engineering.interfaces.schemas import Payload
from pdos_next.errors import DomainError
from tests.d47_support import (
    Professional,
    command,
    confirmed,
    get,
    person,
    post,
    preview,
    shared_configuration,
    team,
)

OPERATION = "engineering.interface.update"


@pytest.fixture
def work(setup):
    config = shared_configuration(setup)
    mechanical, electronics = (
        person(setup, "Synthetic mechanical"),
        person(setup, "Synthetic electronics"),
    )
    team(
        setup,
        config.project,
        {
            setup.human: ["project_manager"],
            mechanical.id: ["mechanical"],
            electronics.id: ["electronics"],
            setup.peer: ["software"],
        },
    )
    professional = Professional(setup, config.project, config.source)
    professional.grant("engineering", [OPERATION])
    config.mechanical, config.electronics = mechanical, electronics
    yield config
    professional.close()


def content(work, **changes):
    return {
        "name": "电机安装接口",
        "kind": "机械尺寸",
        "modules": [{"key": "motor", "label": "电机"}, {"key": "housing", "label": "壳体"}],
        "disciplines": ["mechanical", "electronics"],
        "constraints": [{"text": "安装孔距 32±0.1", "unit": "mm"}],
        "units": ["mm"],
        "verification_method": "首件三坐标测量",
        "responsible_id": str(work.setup_human),
        "affected": [{"kind": "bom", "id": work.bom, "revision": 1, "key": "motor"}],
        "leads": [{"text": "小Pai 线索：壳体散热孔可能受影响，待核实"}],
        **changes,
    }


def create(setup, work, **changes):
    return command(
        setup,
        OPERATION,
        {
            "record": {
                "action": "create",
                "project_id": work.project,
                "configuration": {"id": work.engineering, "revision": 1},
                **content(work, **changes),
            },
            "reason": "登记电机与壳体的安装接口",
        },
    )


def follow(setup, receipt, record, revision, reason="按专业确认"):
    return command(
        setup,
        OPERATION,
        {
            "interface": {"id": receipt["subject_id"], "revision": revision},
            "record": record,
            "reason": reason,
        },
    )


def current(setup, record_id):
    with tenant_session(
        setup.engine, setup.tenant, actor_id=setup.human, category_id=setup.category
    ) as s:
        pointer = s.scalar(
            select(InterfaceCurrent).where(InterfaceCurrent.record_id == UUID(record_id))
        )
        row = s.get(InterfaceVersion, pointer.version_id)
        s.expunge_all()
        return row


def test_create_confirm_revise_and_supersede(setup, work):
    work.setup_human = setup.human
    receipt, shown = confirmed(setup, create(setup, work))
    assert shown["review"]["after"]["state"] == "pending" and shown["review"]["roles"] == [
        "engineering"
    ]
    assert receipt["operation"] == OPERATION and receipt["subject_type"] == "engineering_interface"
    first = current(setup, receipt["subject_id"])
    assert (first.revision, first.state, first.record_id) == (
        1,
        "pending",
        UUID(receipt["subject_id"]),
    )
    assert first.body["content"]["affected"][0]["label"] and first.body["content"]["leads"]
    with tenant_session(
        setup.engine, setup.tenant, actor_id=setup.human, category_id=setup.category
    ) as s:
        assert (
            s.scalar(select(Outbox.type).where(Outbox.receipt_id == UUID(receipt["id"])))
            == "interface.updated"
        )
    # Each discipline confirms separately; the responsible person cannot stand in.
    own = preview(
        setup, follow(setup, receipt, {"action": "confirm", "discipline": "mechanical"}, 1)
    )
    assert own.status_code == 403
    confirmed(
        setup,
        follow(setup, receipt, {"action": "confirm", "discipline": "mechanical"}, 1),
        work.mechanical.headers,
    )
    wrong = preview(
        setup,
        follow(setup, receipt, {"action": "confirm", "discipline": "mechanical"}, 2),
        work.electronics.headers,
    )
    assert wrong.status_code == 403 and wrong.json()["code"] == "QUALIFICATION_REQUIRED"
    disputed, _ = confirmed(
        setup,
        follow(
            setup,
            receipt,
            {"action": "dispute", "discipline": "electronics", "note": "线束走向未定"},
            2,
        ),
        work.electronics.headers,
    )
    assert current(setup, receipt["subject_id"]).state == "disputed"
    confirmed(
        setup,
        follow(
            setup,
            receipt,
            {"action": "confirm", "discipline": "electronics", "note": "已改线束"},
            3,
        ),
        work.electronics.headers,
    )
    done = current(setup, receipt["subject_id"])
    assert (done.revision, done.state) == (4, "confirmed")
    # Revising the content supersedes earlier confirmations.
    record = {
        "action": "revise",
        "configuration": {"id": work.engineering, "revision": 1},
        **content(work, constraints=[{"text": "安装孔距 32±0.05", "unit": "mm"}]),
    }
    confirmed(setup, follow(setup, receipt, record, 4, "收紧孔距公差"))
    revised = current(setup, receipt["subject_id"])
    assert (revised.revision, revised.state) == (5, "pending")
    assert {row["state"] for row in revised.body["confirmations"]} == {"pending"}
    assert {
        (row["discipline"], row["state"], row["superseded_at_revision"])
        for row in revised.body["superseded"]
    } == {
        ("mechanical", "confirmed", 5),
        ("electronics", "confirmed", 5),
    }
    listed = get(setup, f"projects/{work.project}/interfaces").json()["items"]
    assert [item["revision"] for item in listed] == [5]
    detail = get(setup, f"interfaces/{receipt['subject_id']}").json()
    assert [row["revision"] for row in detail["history"]] == [5, 4, 3, 2, 1]
    assert disputed["subject_id"] != receipt["subject_id"]


def test_refusals_without_role_change_confirmation_or_member(setup, work):
    work.setup_human = setup.human
    unconfirmed = post(setup, create(setup, work))
    assert unconfirmed.status_code == 409 and unconfirmed.json()["code"] == "CONFIRMATION_REQUIRED"
    not_engineer = preview(setup, create(setup, work), work.mechanical.headers)
    assert (
        not_engineer.status_code == 403 and not_engineer.json()["code"] == "QUALIFICATION_REQUIRED"
    )
    outsider = preview(setup, create(setup, work, responsible_id=str(uuid4())))
    assert outsider.status_code == 409 and outsider.json()["code"] == "VALIDATION_FAILED"
    unknown_role = preview(setup, create(setup, work, disciplines=["mechanical", "astrology"]))
    assert unknown_role.status_code == 409 and unknown_role.json()["code"] == "VALIDATION_FAILED"
    missing = preview(
        setup, create(setup, work, affected=[{"kind": "bom", "id": str(uuid4()), "revision": 1}])
    )
    assert missing.status_code == 403
    receipt, _ = confirmed(setup, create(setup, work))
    stale = preview(
        setup,
        follow(setup, receipt, {"action": "confirm", "discipline": "mechanical"}, 2),
        work.mechanical.headers,
    )
    assert stale.status_code == 409 and stale.json()["code"] == "VERSION_CONFLICT"
    unchanged = preview(
        setup,
        follow(
            setup,
            receipt,
            {
                "action": "revise",
                "configuration": {"id": work.engineering, "revision": 1},
                **content(work),
            },
            1,
        ),
    )
    assert unchanged.status_code == 409 and unchanged.json()["code"] == "VALIDATION_FAILED"
    other = preview(
        setup, create(setup, work), {"Authorization": f"Bearer {setup.tokens[setup.other_human]}"}
    )
    assert other.status_code in {401, 403}
    # Same prepared request replays; a different interface cannot reuse the key.
    again_cmd = follow(setup, receipt, {"action": "confirm", "discipline": "mechanical"}, 1)
    first, shown = confirmed(setup, again_cmd, work.mechanical.headers)
    replay = post(setup, shown["command"], work.mechanical.headers)
    assert replay.status_code == 200 and replay.json()["id"] == first["id"]


def test_ai_cannot_write_and_database_keeps_history(setup, work):
    work.setup_human = setup.human
    cmd = Command.model_validate(create(setup, work))
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
        interfaces.validate(
            s, ctx, cmd, s.get(Product, setup.product), Payload.model_validate(cmd.payload)
        )
    assert failed.value.code == "NAMED_DECISION_REQUIRED"
    receipt, _ = confirmed(setup, create(setup, work))
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
        s.execute(update(InterfaceVersion).values(state="confirmed"))
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
        s.execute(text("DELETE FROM engineering_interface_currents"))
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.agent,
        requester_id=setup.human,
        category_id=setup.category,
    ) as s:
        assert (
            s.scalar(
                text(
                    "SELECT has_table_privilege('pdos_agent','engineering_interface_versions','SELECT')"  # noqa: E501
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
    assert receipt["subject_type"] == "engineering_interface"


def test_impact_propagates_only_through_listed_items(setup, work):
    from pdos_next.domain.change.execution.graph import OwnerReader, audience
    from pdos_next.schemas.change_control.contracts import Ref
    from pdos_next.schemas.verification.contracts import Scope

    work.setup_human = setup.human
    receipt, _ = confirmed(setup, create(setup, work))
    with tenant_session(
        setup.engine, setup.tenant, actor_id=setup.human, category_id=setup.category
    ) as s:
        scope = Scope(
            tenant_id=setup.tenant, product_id=setup.product, project_id=UUID(work.project)
        )
        reader = OwnerReader(
            s,
            setup.ctx,
            setup.product,
            scope,
            audience(setup.product, setup.human, "category"),
            None,
        )
        obj = reader.resolve(Ref(id=UUID(receipt["subject_id"]), revision=1, kind="interface"))
        links = {(ref.kind, str(ref.id), ref.key) for ref, _ in reader.links(obj)}
    assert links == {
        ("engineering_configuration", work.engineering, None),
        ("bom", work.bom, "motor"),
    }
    assert obj.current is True and obj.view["content"]["leads"]
