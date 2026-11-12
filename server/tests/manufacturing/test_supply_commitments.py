"""T0 supplier commitment (D47, F25, AT-20) through the common command path.

Root alone runs this file against its verified isolated PostgreSQL candidate.
Every fact below is synthetic: no supplier, ERP, model or external send exists.
"""

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from builds.test_build_demand import demand_work  # noqa: F401 - imported fixture
from builds.test_builds import (  # noqa: F401 - fixture dependencies
    build_command,
    configuration,
    definition,
    project,
)
from projects.test_project_first_plan import cmd, post
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from manufacturing.test_supply_execution import supply_work  # noqa: F401 - imported fixture
from pdos_next.core.contracts import Command
from pdos_next.core.database import tenant_session
from pdos_next.core.models import Audit, Confirmation, Outbox, Receipt, RequestKey
from pdos_next.core.service import Context, execute
from pdos_next.domain.manufacturing.supply_commitments.models import (
    SupplyCommitmentCurrent,
    SupplyCommitmentVersion,
)
from pdos_next.domain.manufacturing.supply_execution.models import KitProjection, SupplySnapshot
from pdos_next.errors import DomainError

OP = "supply.commitment.record"
LINE = "Synthetic supplier ACME-01 says 30 motors arrive by 2026-11-20"
PROMISED = "2026-11-20T09:00:00+08:00"


@pytest.fixture
def commitment_work(setup, supply_work):  # noqa: F811 - imported fixture
    source = post(
        setup,
        cmd(
            setup,
            "evidence.artifact.register",
            {
                "title": "Synthetic supplier reply",
                "content": LINE,
                "source_label": "Synthetic isolated supplier fixture",
                "visibility": "private",
            },
        ),
    )
    assert source.status_code == 200, source.text
    motor = next(row for row in supply_work["result"]["demands"] if row["item_id"] == "motor")
    return {
        **supply_work,
        "commitment_source": source.json()["subject_id"],
        "motor": motor["material_id"],
    }


def source_ref(work, line=LINE):
    return {
        "kind": "artifact",
        "id": work["commitment_source"],
        "revision": 1,
        "position": "line:1;quote_sha256:" + sha256(line.encode()).hexdigest(),
    }


def create(work, **overrides):
    record = {
        "action": "create",
        "build_id": work["build_id"],
        "expected_build_revision": 1,
        "material_id": work["motor"],
        "supplier_ref": "ACME-01",
        "quantity": "30",
        "unit": "ea",
        "promised_at": PROMISED,
        "original_timezone": "Asia/Shanghai",
        "text": "供方说 11 月 20 日前交 30 台电机",
    }
    record.update(overrides.pop("record", {}))
    return {"statement": "我在电话里与供方确认了交期", "record": record, **overrides}


def command(setup, payload, *, reads=None):
    value = cmd(setup, OP, payload)
    value["source_read_set"] = reads or []
    return value


def sent(setup, value, *, headers=None, expected=200):
    response = setup.client.post(
        f"/v1/categories/{setup.category}/commands", headers=headers or setup.headers, json=value
    )
    assert response.status_code == expected, response.text
    return response.json()


def view(setup, work, *, headers=None, expected=200):
    response = setup.client.get(
        f"/v1/categories/{setup.category}/products/{setup.product}/builds/"
        f"{work['build_id']}/supply-commitments",
        headers=headers or setup.headers,
    )
    assert response.status_code == expected, response.text
    return response.json()


def counts(setup):
    with Session(setup.admin) as session:
        return {
            model.__tablename__: session.scalar(
                select(func.count()).select_from(model).where(model.tenant_id == setup.tenant)
            )
            for model in (
                SupplyCommitmentVersion,
                SupplyCommitmentCurrent,
                Receipt,
                Outbox,
                SupplySnapshot,
                KitProjection,
            )
        }


def scoped(setup, actor=None):
    actor = actor or setup.human
    return tenant_session(
        setup.engine, setup.tenant, actor_id=actor, requester_id=actor, category_id=setup.category
    )


def at(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def ref(receipt):
    return {"id": receipt["result"]["commitment_id"], "revision": receipt["subject_revision"]}


def test_named_statement_records_a_commitment_that_is_not_stock(setup, commitment_work):
    work = commitment_work
    before = counts(setup)
    value = command(setup, create(work))
    receipt = sent(setup, value)
    assert receipt["operation"] == OP and receipt["subject_type"] == "supply_commitment"
    assert receipt["result"]["state"] == "open"
    promised = datetime.fromisoformat(PROMISED).astimezone(UTC)
    assert at(receipt["result"]["check_at"]) == promised + timedelta(days=1)
    after = counts(setup)
    assert after["supply_commitment_versions"] == before["supply_commitment_versions"] + 1
    assert after["supply_commitment_currents"] == before["supply_commitment_currents"] + 1
    # A commitment never becomes a supply snapshot, a pool balance or a kit result (AT-20).
    assert after["supply_snapshots"] == before["supply_snapshots"]
    assert after["supply_kit_projections"] == before["supply_kit_projections"]
    with scoped(setup) as session:
        row = session.get(SupplyCommitmentVersion, UUID(receipt["subject_id"]))
        saved = session.get(Receipt, UUID(receipt["id"]))
        assert row.receipt_id == saved.id and saved.confirmation_id is None
        assert row.actor_id == row.writer_id == row.requester_id == setup.human
        assert row.body["time_basis"] == "human_recorded" and row.sources == []
        assert row.body["statement"] and row.body["responsible_id"] == str(setup.human)
        assert row.owner_id == setup.human and row.visibility == "private"
        for model in (Audit, Outbox, RequestKey):
            rows = list(session.scalars(select(model).where(model.receipt_id == saved.id)))
            assert len(rows) == 1
        assert rows[0].actor_id == setup.human
        event = session.scalar(select(Outbox).where(Outbox.receipt_id == saved.id))
        assert event.type == "supply.commitment_recorded"
    listed = view(setup, work)
    motor = next(line for line in listed["lines"] if line["material_id"] == work["motor"])
    assert motor["open_commitments"] == 1 and motor["commitments"] == [
        receipt["result"]["commitment_id"]
    ]
    assert motor["actual"] == {"on_hand": {}, "received": {}}
    assert "不计入库存与齐套" in listed["kit_rule"]
    commitment = listed["commitments"][0]
    assert commitment["follow_up"]["status"] in {"pending", "check_due"}
    assert commitment["ai_written"] is False and len(commitment["history"]) == 1
    # T0: no human preview is opened for it.
    preview = setup.client.post(
        f"/v1/categories/{setup.category}/commands/preview",
        headers=setup.headers,
        json=command(setup, create(work, record={"supplier_ref": "ACME-02"})),
    )
    assert preview.status_code == 403 and preview.json()["code"] == "FORBIDDEN_SCOPE"


def test_replay_returns_the_receipt_and_a_changed_payload_conflicts(setup, commitment_work):
    value = command(setup, create(commitment_work))
    first = sent(setup, value)
    stable = counts(setup)
    assert sent(setup, value) == first
    # The same intent under a new client key is the same receipt, not a second commitment.
    again = dict(value, command_id=str(uuid4()), idempotency_key=str(uuid4()))
    assert sent(setup, again)["id"] == first["id"]
    assert counts(setup) == stable
    changed = command(setup, create(commitment_work, record={"quantity": "31"}))
    changed["idempotency_key"] = value["idempotency_key"]
    conflict = sent(setup, changed, expected=409)
    assert conflict["code"] == "DUPLICATE_INTENT_CONFLICT"
    assert counts(setup) == stable


def test_revise_close_and_reopen_keep_the_whole_history(setup, commitment_work):
    work = commitment_work
    reads = [{"artifact_id": work["commitment_source"], "expected_revision": 1}]
    created = sent(
        setup,
        command(setup, create(work, statement=None, sources=[source_ref(work)]), reads=reads),
    )
    with scoped(setup) as session:
        row = session.get(SupplyCommitmentVersion, UUID(created["subject_id"]))
        assert row.body["time_basis"] == "human_recorded" and len(row.sources) == 1
        assert row.reads == reads
    revise = {
        "action": "revise",
        "quantity": "20",
        "unit": "ea",
        "promised_at": "2026-11-25T09:00:00+08:00",
        "original_timezone": "Asia/Shanghai",
        "text": "供方改期到 11 月 25 日，先交 20 台",
    }
    stale = {"id": ref(created)["id"], "revision": 2}
    refused = sent(
        setup,
        command(setup, {"commitment": stale, "statement": "供方来电改期", "record": revise}),
        expected=409,
    )
    assert refused["code"] == "VERSION_CONFLICT"
    revised = sent(
        setup,
        command(setup, {"commitment": ref(created), "statement": "供方来电改期", "record": revise}),
    )
    assert revised["subject_revision"] == 2
    assert at(revised["result"]["check_at"]) == at("2026-11-26T01:00:00+00:00")
    closed = sent(
        setup,
        command(
            setup,
            {
                "commitment": ref(revised),
                "statement": "供给快照已登记到货",
                "record": {"action": "close", "result": "已收到 20 台，余量另行跟进"},
            },
        ),
    )
    assert closed["result"]["state"] == "closed"
    after_close = sent(
        setup,
        command(setup, {"commitment": ref(closed), "statement": "再改", "record": revise}),
        expected=409,
    )
    assert after_close["code"] == "VALIDATION_FAILED"
    no_reason = setup.client.post(
        f"/v1/categories/{setup.category}/commands",
        headers=setup.headers,
        json=command(
            setup, {"commitment": ref(closed), "statement": "重开", "record": {"action": "reopen"}}
        ),
    )
    assert no_reason.status_code == 422, no_reason.text
    reopened = sent(
        setup,
        command(
            setup,
            {
                "commitment": ref(closed),
                "statement": "余量仍需跟进",
                "reason": "余下 10 台未到，重开跟进",
                "record": {"action": "reopen"},
            },
        ),
    )
    assert reopened["result"]["state"] == "open" and reopened["subject_revision"] == 4
    listed = view(setup, work)
    item = next(row for row in listed["commitments"] if row["commitment_id"] == ref(created)["id"])
    assert [row["action"] for row in item["history"]] == ["create", "revise", "close", "reopen"]
    assert [at(row["promised_at"]) for row in item["history"][:2]] == [
        at(PROMISED),
        at("2026-11-25T09:00:00+08:00"),
    ]
    with scoped(setup) as session:
        pointer = session.scalar(
            select(SupplyCommitmentCurrent).where(
                SupplyCommitmentCurrent.commitment_id == UUID(ref(created)["id"])
            )
        )
        assert pointer.revision == 4 and pointer.state == "open"
        versions = session.scalars(
            select(SupplyCommitmentVersion)
            .where(SupplyCommitmentVersion.commitment_id == UUID(ref(created)["id"]))
            .order_by(SupplyCommitmentVersion.revision)
        ).all()
        assert [row.previous_revision for row in versions] == [None, 1, 2, 3]


def test_due_commitment_enters_my_work_as_an_internal_check(setup, commitment_work):
    past = (datetime.now(UTC) - timedelta(days=3)).isoformat()
    receipt = sent(setup, command(setup, create(commitment_work, record={"promised_at": past})))
    response = setup.client.get(
        "/v1/personal/attention", params={"queue": "external"}, headers=setup.headers
    )
    assert response.status_code == 200, response.text
    items = [
        row
        for row in response.json()["items"]
        if row["id"] == "supply_commitment_check:" + receipt["result"]["commitment_id"]
    ]
    assert len(items) == 1
    assert items[0]["kind"] == "supply_commitment_check" and items[0]["due_at"]
    assert "不表示违约" in items[0]["reason"]
    listed = view(setup, commitment_work)
    assert listed["commitments"][0]["follow_up"]["status"] == "check_due"
    peer = setup.client.get(
        "/v1/personal/attention",
        params={"queue": "external"},
        headers={"Authorization": f"Bearer {setup.tokens[setup.peer]}"},
    )
    assert peer.status_code == 200
    assert not [row for row in peer.json()["items"] if row["kind"] == "supply_commitment_check"]


def test_scope_evidence_and_identity_are_refused_without_writes(setup, commitment_work):
    work = commitment_work
    stable = counts(setup)
    outside = sent(
        setup,
        command(setup, create(work, record={"material_id": str(uuid4())})),
        expected=403,
    )
    assert outside["code"] == "FORBIDDEN_SCOPE"
    stale_build = sent(
        setup, command(setup, create(work, record={"expected_build_revision": 2})), expected=409
    )
    assert stale_build["code"] == "VERSION_CONFLICT"
    # The private Build is invisible to another category writer and to another tenant.
    for token in (setup.tokens[setup.peer], setup.tokens[setup.other_human]):
        response = setup.client.post(
            f"/v1/categories/{setup.category}/commands",
            headers={"Authorization": f"Bearer {token}"},
            json=command(setup, create(work)),
        )
        assert response.status_code in {401, 403}, response.text
    view(setup, work, headers={"Authorization": f"Bearer {setup.tokens[setup.peer]}"}, expected=403)
    unread = sent(
        setup,
        command(setup, create(work, statement=None, sources=[source_ref(work)])),
        expected=422,
    )
    assert unread["code"] == "MISSING_REQUIRED_EVIDENCE"
    wrong_line = sent(
        setup,
        command(
            setup,
            create(work, statement=None, sources=[source_ref(work, "not the original line")]),
            reads=[{"artifact_id": work["commitment_source"], "expected_revision": 1}],
        ),
        expected=422,
    )
    assert wrong_line["code"] == "MISSING_REQUIRED_EVIDENCE"
    # An AI identity without a server-bound run cannot write, with or without sources.
    agent = Context(setup.tenant, setup.agent, setup.human, category_id=setup.category)
    with pytest.raises(DomainError) as failure:
        with tenant_session(
            setup.engine,
            setup.tenant,
            actor_id=setup.agent,
            requester_id=setup.human,
            category_id=setup.category,
        ) as session:
            execute(session, agent, Command.model_validate(command(setup, create(work))))
    assert failure.value.code == "FORBIDDEN_SCOPE"
    assert counts(setup) == stable


def test_database_keeps_versions_append_only_and_bound_to_receipts(setup, commitment_work):
    receipt = sent(setup, command(setup, create(commitment_work)))
    with Session(setup.admin) as session:
        assert not session.scalar(
            text("SELECT has_table_privilege('pdos_agent','supply_commitment_versions','SELECT')")
        )
        assert not session.scalar(
            text("SELECT has_table_privilege('pdos_agent','supply_commitment_currents','INSERT')")
        )
    with pytest.raises(DBAPIError):
        with scoped(setup) as session:
            session.execute(
                text("UPDATE supply_commitment_versions SET state='closed' WHERE id=:id"),
                {"id": receipt["subject_id"]},
            )
    with pytest.raises(DBAPIError):
        with scoped(setup) as session:
            row = session.get(SupplyCommitmentVersion, UUID(receipt["subject_id"]))
            forged = SupplyCommitmentVersion(
                **{
                    column.name: getattr(row, column.name)
                    for column in SupplyCommitmentVersion.__table__.columns
                    if column.name not in {"id", "receipt_id", "command_id", "commitment_id"}
                },
                id=(identity := uuid4()),
                commitment_id=identity,
                receipt_id=uuid4(),
                command_id=uuid4(),
            )
            forged.body = {**row.body, "commitment_id": str(identity)}
            session.add(forged)
            session.flush()
    assert counts(setup)["supply_commitment_versions"] == 1
    with Session(setup.admin) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(Confirmation)
                .where(Confirmation.tenant_id == setup.tenant, Confirmation.operation == OP)
            )
            == 0
        )
