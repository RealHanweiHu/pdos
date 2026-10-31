"""No provider/network/DB: real DTO, graph, official protocol and durable lookup semantics."""

from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace as NS
from uuid import UUID, uuid4

import httpx
import pytest
from pdos_next import models as native_models  # noqa: F401 -- initialize native metadata first
from pdos_next.dingtalk.accounts import credential
from pdos_next.dingtalk.official import OfficialAdapter
from pdos_next.dingtalk.ports import ChannelRuntime
from pdos_next.dingtalk.runtime import ChannelService
from pdos_next.dingtalk.summary_delivery import SummaryDeliveryService, compose, source_ids
from pdos_next.dingtalk.summary_models import SummaryDelivery
from pdos_next.dingtalk.synthetic import SyntheticKms
from pdos_next.personal_summary_schemas import Selection, Summary
from pdos_next.service import digest
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable


def actual_summary(count=1):
    owner, tenant, category, project, version = [uuid4() for _ in range(5)]
    at = datetime(2026, 10, 29, tzinfo=UTC).isoformat()
    item = dict(
        id="registered-update",
        kind="project_update",
        group="following",
        title="具名状态",
        object=dict(
            kind="project_status_update",
            id=str(project),
            version_id=str(version),
            revision=1,
            category_id=str(category),
            product_id=None,
            project_id=str(project),
        ),
        as_of=at,
        recorded_at=at,
        state_as_recorded="named_update_recorded",
        change=dict(kind="updated", text="实际具名变化"),
        relationship=dict(kind="subscriber", text="本人明确关注的项目"),
        next_step=dict(kind="unknown", text="待确认", responsible=None, recorded_by=None),
        continue_url=f"/?area=cockpit&category={category}&project={project}",
        facts={"unrendered_private_body": "RAW_ORIGINAL_NEVER_COPY", "fake_id": str(uuid4())},
        possible_impact="待确认",
        health=None,
        fingerprint="a" * 64,
    )
    items = [{**item, "id": f"registered-update-{i}"} for i in range(count)]
    value = Summary.model_validate(
        dict(
            version="personal-summary/v1",
            tenant_id=tenant,
            principal_id=owner,
            as_of=at,
            groups=[
                dict(
                    id="following",
                    title="项目变化",
                    items=items,
                    unchanged_items=[],
                    unchanged_collapsed=True,
                )
            ],
            coverage=[],
            complete=True,
            omitted_current_items=0,
            baseline=dict(tenant_id=tenant, principal_id=owner, selection_digest="a" * 64),
            model_used=False,
        )
    )
    return value, NS(owner_id=owner, external_user_id="synthetic-owner"), category


def test_default_and_explicit_null_selection_preserve_old_digest():
    expected = dict(
        followed_project_ids=[],
        category_ids=[],
        groups=["action", "waiting", "following"],
        excluded_kinds=[],
        max_items=100,
    )
    assert Selection().model_dump(mode="json") == expected
    assert Selection(dingtalk_binding_id=None).model_dump(mode="json") == expected
    assert digest(Selection().model_dump(mode="json")) == digest(expected)
    identity = uuid4()
    assert Selection(dingtalk_binding_id=identity).model_dump(mode="json")[
        "dingtalk_binding_id"
    ] == str(identity)
    with pytest.raises(ValueError):
        Selection(dingtalk_binding_id=True)


def test_fixed_summary_uses_only_registered_display_fields_and_real_object_ids():
    summary, binding, category = actual_summary()
    run = uuid4()
    value = compose(
        summary,
        binding=binding,
        public_base_url="https://pdos.synthetic.invalid",
        run_id=run,
        category_id=category,
    )
    assert value["target_kind"] == "direct" and value["target_id"] == "synthetic-owner"
    assert value["url"] == f"https://pdos.synthetic.invalid/dingtalk/runs/{run}?category={category}"
    assert "实际具名变化" in value["text"] and "责任人：未单独登记" in value["text"]
    assert "RAW_ORIGINAL_NEVER_COPY" not in str(value) and "facts" not in str(value)
    item = summary.groups[0].items[0]
    assert set(source_ids(summary)) == {item.object.id, item.object.version_id}
    with pytest.raises(Exception, match="本人绑定"):
        compose(
            summary,
            binding=NS(owner_id=uuid4()),
            public_base_url="https://pdos.invalid",
            run_id=run,
            category_id=category,
        )


def test_bounded_payload_discloses_omitted_entries_and_partial_coverage():
    summary, binding, category = actual_summary(300)
    summary = summary.model_copy(update={"complete": False})
    value = compose(
        summary,
        binding=binding,
        public_base_url="https://pdos.synthetic.invalid",
        run_id=uuid4(),
        category_id=category,
    )
    assert len(value["text"]) < 20000
    assert "请在 PDOS 查看完整摘要" in value["text"] and "部分来源仍待核对" in value["text"]


def wire():
    calls = []

    def handle(request):
        calls.append(request)
        if request.url.path == "/v1.0/oauth2/accessToken":
            return httpx.Response(200, json={"accessToken": "offline-token"})
        if request.url.path.endswith("/batchSend"):
            return httpx.Response(200, json={"processQueryKey": "offline-summary-receipt"})
        assert request.url.path.endswith("/readStatus")
        return httpx.Response(200, json={"sendStatus": "SUCCESS"})

    kms = SyntheticKms()
    arn = "acs:kms:local:0:secret/synthetic-summary"
    kms.install(arn, "1")
    app = NS(
        id=uuid4(),
        corp_id="offline-corp",
        client_id="offline-client",
        robot_code="offline-bot",
        active=True,
        secret_arn=arn,
        secret_version="1",
    )
    adapter = OfficialAdapter(
        httpx.Client(transport=httpx.MockTransport(handle)),
        "https://pdos.synthetic.invalid/callback",
    )
    return ChannelRuntime(kms, adapter, "https://pdos.synthetic.invalid"), app, calls


def test_official_pending_receipt_reconciles_after_restart_without_any_send_or_source_read():
    summary, binding, category = actual_summary()
    runtime, app, calls = wire()
    payload = compose(
        summary,
        binding=binding,
        public_base_url=runtime.public_base_url,
        run_id=uuid4(),
        category_id=category,
    )
    row = NS(
        id=uuid4(),
        run_id=uuid4(),
        application_id=app.id,
        request_key=uuid4(),
        payload_sha256=digest(payload),
        state="sending",
        attempts=1,
        error_code=None,
        provider_receipt=None,
    )
    receipt = runtime.adapter.send(app, credential(runtime, app), row.request_key, payload)
    ChannelService.accept_receipt(row, receipt)
    assert row.state == "unknown" and row.provider_receipt["status"] == "pending"

    @contextmanager
    def transaction(_meta):
        yield NS(scalar=lambda *_a, **_k: row, get=lambda *_a, **_k: app)

    restarted = SummaryDeliveryService(object(), object(), runtime=runtime)
    restarted.transaction = transaction
    restarted.snapshot = lambda *_a, **_k: pytest.fail(
        "receipt lookup must not reread source facts"
    )
    outcome = restarted.reconcile({"run_id": row.run_id}, row.id)
    assert outcome["state"] == "delivered" and outcome["attempts"] == 1
    assert sum(r.url.path.endswith("/batchSend") for r in calls) == 1
    assert sum(r.url.path.endswith("/readStatus") for r in calls) == 1
    assert restarted.reconcile({"run_id": row.run_id}, row.id) == outcome
    assert sum(r.url.path.endswith("/batchSend") for r in calls) == 1


def test_unknown_without_provider_receipt_stays_unknown_and_never_retries_send():
    runtime, app, calls = wire()
    row = NS(
        id=uuid4(),
        run_id=uuid4(),
        application_id=app.id,
        request_key=uuid4(),
        payload_sha256="a" * 64,
        state="unknown",
        attempts=1,
        error_code=None,
        provider_receipt=None,
    )

    @contextmanager
    def transaction(_meta):
        yield NS(scalar=lambda *_a, **_k: row, get=lambda *_a, **_k: app)

    service = SummaryDeliveryService(object(), object(), runtime=runtime)
    service.transaction = transaction
    assert service.reconcile({"run_id": row.run_id}, row.id)["state"] == "unknown"
    assert not any(r.url.path.endswith("/batchSend") for r in calls)


def test_new_model_has_real_scope_and_fixed_origin_columns_in_postgres_ddl():
    table = SummaryDelivery.__table__
    assert set(SummaryDelivery.__annotations__) <= set(table.columns.keys())
    assert not table.c.category_id.nullable and not table.c.source_ids.nullable
    ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
    assert "source_ids UUID[] NOT NULL" in ddl and "message_id" not in ddl
    assert "automation_service_attempts" in ddl and "agent_runs" in ddl
    for name in ("p26", "provider_receipt"):
        # The insert guard requires SQL NULL before the original wire attempt.
        dialect = postgresql.dialect()
        assert table.c[name].type.dialect_impl(dialect).bind_processor(dialect)(None) is None


def test_delivery_activity_runs_registered_deterministic_graph_with_only_fixed_ids(monkeypatch):
    from pdos_next.dingtalk.summary_delivery import SummaryReference
    from pdos_next.dingtalk.summary_workflow import SummaryActivities

    reference = {"tenant_id": str(uuid4()), "run_id": str(uuid4())}
    seen = []

    class Port:
        def __init__(self, *_args, **_kwargs):
            pass

        def deliver(self, actual):
            seen.append(actual)
            return {"state": "delivered", "delivery_id": str(uuid4()), "attempts": 1}

    monkeypatch.setattr("pdos_next.dingtalk.summary_delivery.SummaryDeliveryService", Port)
    assert (
        SummaryActivities(object(), object(), runtime=object()).deliver(reference)["state"]
        == "delivered"
    )
    assert seen == [
        {"tenant_id": UUID(reference["tenant_id"]), "run_id": UUID(reference["run_id"])}
    ]
    with pytest.raises(ValueError):
        SummaryReference.model_validate({**reference, "owner_id": str(uuid4()), "summary": "fake"})
