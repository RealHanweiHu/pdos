"""Platform T1 writes and audience-filtered reads in the marked pdos_test only."""

from concurrent.futures import ThreadPoolExecutor
from copy import copy, deepcopy
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pdos_next.database import tenant_session
from pdos_next.domain.products.platform_models import Platform, PlatformLink, PlatformLinkCurrent
from pdos_next.models import Audit, Confirmation, Grant, Outbox, Product, Receipt
from tests.products.test_definition_item_commands_pg import confirmed
from tests.products.test_definition_transactions import command, post


def payload(setup, **changes):
    return {
        "product_id": str(setup.product),
        "new_platform": {
            "code": "SYNTHETIC-PLATFORM",
            "name": "合成便携平台",
            "description": "通用组件范围",
        },
        "action": "attach",
        "compatibility": None,
        "platform_version": None,
        "reason": "人工确认合成平台关联",
        "expected_link_version": 0,
        **changes,
    }


def request(setup, **changes):
    return command(setup, "platform.link.create", payload(setup, **changes))


def read(setup, suffix="platforms", query="", actor=None):
    return setup.client.get(
        f"/v1/categories/{setup.category}/{suffix}{query}",
        headers={"Authorization": f"Bearer {setup.tokens[actor or setup.human]}"},
    )


def counts(setup):
    with Session(setup.admin) as s:
        return {
            model.__tablename__: s.scalar(
                select(func.count()).select_from(model).where(model.tenant_id == setup.tenant)
            )
            for model in (Platform, PlatformLink, PlatformLinkCurrent, Receipt, Audit, Outbox)
        }


def test_t1_preview_no_business_write_atomic_create_and_exact_replay(setup):
    cmd = request(setup)
    before = counts(setup)
    denied = post(setup, cmd)
    assert denied.status_code == 409 and denied.json()["code"] == "CONFIRMATION_REQUIRED"
    preview = setup.client.post(
        f"/v1/categories/{setup.category}/commands/preview",
        headers=setup.headers,
        json=cmd,
    )
    assert preview.status_code == 200, preview.text
    assert counts(setup) == before
    assert preview.json()["review"]["platform"]["code"] == "SYNTHETIC-PLATFORM"
    prepared = preview.json()["command"]
    saved = post(setup, prepared)
    assert saved.status_code == 200, saved.text
    receipt = saved.json()
    assert receipt["subject_type"] == "platform_link"
    assert receipt["result"]["platform_created"]
    assert all(counts(setup)[key] == value + 1 for key, value in before.items())
    assert post(setup, prepared).json()["id"] == receipt["id"]
    recovered = deepcopy(prepared)
    recovered["idempotency_key"] = str(uuid4())
    assert post(setup, recovered).json()["id"] == receipt["id"]
    assert all(counts(setup)[key] == value + 1 for key, value in before.items())
    with Session(setup.admin) as s:
        link = s.get(PlatformLink, UUID(receipt["subject_id"]))
        stored = s.get(Receipt, UUID(receipt["id"]))
        assert link.receipt_id == stored.id and link.confirmation_id == stored.confirmation_id
        assert s.get(Confirmation, stored.confirmation_id).consumed
        assert link.origin == "human" and link.writer_id == setup.human
        assert s.get(Product, setup.product).revision == 1
    listed = read(setup).json()["items"][0]
    assert listed["links"][0]["compatibility"] is None
    assert listed["links"][0]["platform_version"] is None
    assert "run_id" not in listed["provenance"]


def test_append_detach_reattach_stale_versions_and_baseline(setup):
    first, _ = confirmed(setup, request(setup))
    platform_id = first["result"]["platform_id"]
    update = {"new_platform": None, "platform_id": platform_id, "expected_link_version": 1}
    second, _ = confirmed(
        setup, request(setup, **update, compatibility="仅限合成配置A", platform_version="P2")
    )
    assert second["subject_revision"] == 2
    stale = setup.client.post(
        f"/v1/categories/{setup.category}/commands/preview",
        headers=setup.headers,
        json=request(setup, **update),
    )
    assert stale.status_code == 409 and stale.json()["code"] == "VERSION_CONFLICT"
    detached, original = confirmed(
        setup,
        request(
            setup,
            new_platform=None,
            platform_id=platform_id,
            expected_link_version=2,
            action="detach",
        ),
    )
    assert detached["subject_revision"] == 3
    assert post(setup, original).json()["id"] == detached["id"]
    history = read(
        setup, f"products/{setup.product}/platform-links", "?include_history=true"
    ).json()
    assert [x["version"] for x in history["items"][0]["links"]] == [1, 2, 3]
    assert all(not x["attached"] for x in history["items"][0]["links"])
    confirmed(
        setup, request(setup, new_platform=None, platform_id=platform_id, expected_link_version=3)
    )
    baseline = read(setup, f"products/{setup.product}/baseline")
    assert baseline.status_code == 200, baseline.text
    block = baseline.json()["blocks"]["platform"]
    assert block["status"] == "available" and block["basis"] == "current_product_links"
    assert block["items"][0]["links"][0]["version"] == 4
    with tenant_session(
        setup.engine, setup.tenant, actor_id=setup.human, category_id=setup.category
    ) as s:
        with pytest.raises(DBAPIError):
            s.execute(
                text("UPDATE platform_product_links SET reason='rewrite' WHERE tenant_id=:t"),
                {"t": setup.tenant},
            )


def test_permission_tenant_duplicate_code_and_preview_drift(setup):
    saved, _ = confirmed(setup, request(setup))
    duplicate = setup.client.post(
        f"/v1/categories/{setup.category}/commands/preview",
        headers=setup.headers,
        json=request(setup),
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["reason"] == "platform_code_taken"
    assert read(setup, actor=setup.other_human).status_code == 403
    with Session(setup.admin) as s, s.begin():
        s.scalar(select(Grant).where(Grant.principal_id == setup.peer)).can_write = False
    unauthorized = setup.client.post(
        f"/v1/categories/{setup.category}/commands/preview",
        headers={"Authorization": f"Bearer {setup.tokens[setup.peer]}"},
        json=request(setup),
    )
    assert unauthorized.status_code == 403
    assert len(read(setup, actor=setup.peer).json()["items"]) == 1
    assert (
        read(setup, query="?name_query=合成").json()["items"][0]["id"]
        == saved["result"]["platform_id"]
    )
    assert read(setup, query=f"?variant_id={uuid4()}").status_code == 422


def test_failure_after_new_platform_rolls_back_every_business_member(setup, monkeypatch):
    from pdos_next import service

    cmd = request(setup)
    preview = setup.client.post(
        f"/v1/categories/{setup.category}/commands/preview",
        headers=setup.headers,
        json=cmd,
    )
    assert preview.status_code == 200, preview.text
    before = counts(setup)
    original = service.append_receipt

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("synthetic commit interruption")

    monkeypatch.setattr(service, "append_receipt", fail)
    with pytest.raises(RuntimeError, match="synthetic commit interruption"):
        post(setup, preview.json()["command"])
    assert counts(setup) == before
    monkeypatch.setattr(service, "append_receipt", original)
    recovered = post(setup, preview.json()["command"])
    assert recovered.status_code == 200, recovered.text


def test_private_variant_link_hidden_but_shared_platform_metadata_readable(setup):
    # 确认稿 P23: only a G0 approved variant identity may be bound, so the link
    # target comes from a derivative proposal. The named reviewer is a third human
    # and setup.peer stays outside the private proposal audience.
    from g0_fixture import add_category_human, create_g0_variant

    reviewer = add_category_human(setup, name="Synthetic variant reviewer")
    variant = create_g0_variant(setup, reviewer=reviewer)
    saved, _ = confirmed(
        setup,
        request(
            setup,
            variant_id=variant.variant_id,
            compatibility="合成客户专属配置",
            platform_version="C1",
        ),
    )
    visible = read(setup, actor=setup.peer)
    assert visible.status_code == 200, visible.text
    assert len(visible.json()["items"]) == 1
    shared = visible.json()["items"][0]
    assert shared["id"] == saved["result"]["platform_id"] and shared["links"] == []
    assert "合成客户专属配置" not in visible.text and variant.variant_id not in visible.text
    assert "receipt_id" not in shared["provenance"] and "run_id" not in shared["provenance"]
    assert (
        read(
            setup,
            f"products/{setup.product}/platform-links",
            f"?variant_id={variant.variant_id}",
            actor=setup.peer,
        ).status_code
        == 404
    )
    own = read(
        setup, f"products/{setup.product}/platform-links", f"?variant_id={variant.variant_id}"
    ).json()
    assert own["items"][0]["links"][0]["compatibility"] == "合成客户专属配置"
    assert read(setup, f"products/{setup.product}/platform-links").json()["items"] == []
    with tenant_session(
        setup.engine, setup.tenant, actor_id=setup.peer, category_id=setup.category
    ) as s:
        assert s.get(Receipt, UUID(saved["id"])) is None


def test_agent_candidate_confirmation_preserves_writer_and_cancel_guard(setup):
    from pdos_next.agent_kernel.models import AgentRun
    from pdos_next.domain.preproject.provenance import prepare_candidate
    from tests.products.test_definition_item_revert_pg import agent_fixture

    args = payload(setup)
    fixture = agent_fixture(
        setup, args, operation="platform.link.create", skill_key="derivative_diff"
    )
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.agent,
        requester_id=setup.human,
        category_id=setup.category,
    ) as s:
        prepared = prepare_candidate(
            s,
            fixture.scope,
            "platform.link.create",
            args,
            fixture.source,
            catalog=fixture.catalog,
            registry=fixture.registry,
            route=fixture.route,
        )
    saved, original = confirmed(setup, command(setup, "platform.link.create", prepared))
    with Session(setup.admin) as s:
        link = s.get(PlatformLink, UUID(saved["subject_id"]))
        assert link.origin == "ai_draft" and link.writer_id == setup.agent
        assert link.confirmed_by == setup.human and link.run_id == fixture.scope.run_id
        assert link.prepared_candidate_id and saved["agent_run_id"] == str(fixture.scope.run_id)
    assert post(setup, original).json()["id"] == saved["id"]
    cancelled_args = payload(
        setup, new_platform={"code": "CANCELLED", "name": "待取消", "description": ""}
    )
    cancelled = agent_fixture(
        setup, cancelled_args, operation="platform.link.create", skill_key="derivative_diff"
    )
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.agent,
        requester_id=setup.human,
        category_id=setup.category,
    ) as s:
        prepared = prepare_candidate(
            s,
            cancelled.scope,
            "platform.link.create",
            cancelled_args,
            cancelled.source,
            catalog=cancelled.catalog,
            registry=cancelled.registry,
            route=cancelled.route,
        )
    preview = setup.client.post(
        f"/v1/categories/{setup.category}/commands/preview",
        headers=setup.headers,
        json=command(setup, "platform.link.create", prepared),
    )
    assert preview.status_code == 200, preview.text
    before = counts(setup)
    with Session(setup.admin) as s, s.begin():
        run = s.get(AgentRun, cancelled.scope.run_id)
        run.state, run.cancel_epoch = "cancelled", run.cancel_epoch + 1
    denied = post(setup, preview.json()["command"])
    assert denied.status_code == 403 and denied.json()["code"] == "FORBIDDEN_SCOPE"
    assert counts(setup) == before


def test_database_rejects_unreceipted_platform_and_current_tamper(setup):
    saved, _ = confirmed(setup, request(setup))
    with pytest.raises(DBAPIError):
        with tenant_session(
            setup.engine, setup.tenant, actor_id=setup.human, category_id=setup.category
        ) as s:
            original = s.get(Platform, UUID(saved["result"]["platform_id"]))
            s.add(
                Platform(
                    tenant_id=setup.tenant,
                    code="ORPHAN",
                    name="无原子关联",
                    description="",
                    origin=original.origin,
                    writer_id=original.writer_id,
                    confirmed_by=original.confirmed_by,
                    receipt_id=original.receipt_id,
                    confirmation_id=original.confirmation_id,
                )
            )
    with pytest.raises(DBAPIError):
        with tenant_session(
            setup.engine, setup.tenant, actor_id=setup.human, category_id=setup.category
        ) as s:
            s.execute(
                text("UPDATE platform_link_current SET attached=false WHERE tenant_id=:t"),
                {"t": setup.tenant},
            )
    with setup.admin.connect() as c:
        for table in ("platforms", "platform_product_links", "platform_link_current"):
            assert c.scalar(
                text("SELECT has_table_privilege('pdos_agent',:table,'SELECT')"), {"table": table}
            )
            assert not c.scalar(
                text("SELECT has_table_privilege('pdos_agent',:table,'INSERT,UPDATE,DELETE')"),
                {"table": table},
            )


def test_parallel_new_platform_code_creates_one_whole_transaction(setup):
    other = copy(setup)
    other.product = uuid4()
    with Session(setup.admin) as s, s.begin():
        s.add(
            Product(
                id=other.product,
                tenant_id=setup.tenant,
                category_id=setup.category,
                owner_id=setup.human,
                name="第二合成型号",
                purpose="同平台编号并发核对",
            )
        )
    prepared = []
    for target in (setup, other):
        preview = target.client.post(
            f"/v1/categories/{target.category}/commands/preview",
            headers=target.headers,
            json=request(target),
        )
        assert preview.status_code == 200, preview.text
        prepared.append((target, preview.json()["command"]))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda args: post(*args), prepared))
    assert sorted(row.status_code for row in results) == [200, 409], [row.text for row in results]
    assert (
        next(row for row in results if row.status_code == 409).json()["detail"]["reason"]
        == "platform_code_taken"
    )
    assert all(value == 1 for value in counts(setup).values())


def test_platform_migration_refuses_to_remove_committed_history(setup):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    from migrations.versions.s0_0759_platform_links import downgrade

    saved, _ = confirmed(setup, request(setup))
    # The point is that a refused downgrade leaves the stamp alone, whatever
    # revision this environment is on; pinning one revision only ages.
    with setup.admin.connect() as probe:
        before = probe.scalar(text("SELECT version_num FROM alembic_version"))
    with setup.admin.connect() as connection:
        transaction = connection.begin()
        try:
            with Operations.context(MigrationContext.configure(connection)):
                with pytest.raises(DBAPIError, match="platform history must be preserved"):
                    downgrade()
        finally:
            transaction.rollback()
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == before
    assert read(setup).json()["items"][0]["id"] == saved["result"]["platform_id"]


def test_platform_link_refuses_a_variant_draft_without_a_g0_decision(setup):
    """确认稿 P23: a direct derivation is preparation only; nothing may reference it."""
    from tests.products.test_variants_transactions import definition, derive, source

    artifact = source(setup)
    parent = definition(setup, artifact)
    draft, _, _ = derive(setup, parent, artifact, kind="customer", visibility="private")
    before = counts(setup)
    blocked = setup.client.post(
        f"/v1/categories/{setup.category}/commands/preview",
        headers=setup.headers,
        json=request(setup, variant_id=draft["id"]),
    )
    assert blocked.status_code == 403, blocked.text
    assert blocked.json()["code"] == "FORBIDDEN_SCOPE"
    assert blocked.json()["detail"]["reason"] == "variant_without_g0_decision"
    committed = post(setup, request(setup, variant_id=draft["id"]))
    assert committed.status_code == 403, committed.text
    assert committed.json()["detail"]["reason"] == "variant_without_g0_decision"
    assert counts(setup) == before
