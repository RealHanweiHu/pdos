"""Real subscription receipts, evidence capture and failure recovery; no sockets/models."""

# ruff: noqa: F811
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.ai import reach
from app.ai.reach import ReachFetchError, ReachPolicy, ReachResponse
from app.db.schema import tables
from app.domain import research_collection, research_subscriptions
from app.domain.evidence import EvidenceService
from app.domain.research_subscriptions import ResearchCollectionWorker
from tests.test_product_discovery_findings_api import seed_discovery
from tests.test_product_manager_loop_api import command
from tests.test_product_planning_findings_api import post
from tests.test_test_runs_api import Scope
from tests.test_test_runs_api import client as client
from tests.test_test_runs_api import isolated_test_run_database as isolated_test_run_database


def test_subscription_evidence_backoff_pause_expiry_and_account_revocation(
    client: TestClient,
    isolated_test_run_database: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = Scope(client, isolated_test_run_database)
    try:
        seed = seed_discovery(client, scope)
        base, headers = seed["base"], seed["headers"]

        def policy():
            return ReachPolicy(resolver=lambda hostname: ["93.184.216.34"])

        monkeypatch.setattr(research_subscriptions, "ReachPolicy", policy)
        monkeypatch.setattr(reach, "ReachPolicy", policy)
        source = EvidenceService(scope.engine).create_source(
            tenant_id=scope.tenant_id,
            actor_user_id=scope.owner_id,
            name="合成订阅源",
            source_type="web",
            base_url="https://example.com",
            allowed_use="internal_analysis",
            collection_frequency="daily",
            retention_policy="standard",
            trust_tier="unknown",
        )
        body = dict(
            request_id=str(uuid4()),
            source_id=str(source.id),
            product_line_id=seed["line"]["id"],
            url="https://example.com/pm-proof",
            frequency="daily",
            freshness_days=3,
        )
        subscription = post(client, base, headers, "/subscriptions", body, 201)
        assert post(client, base, headers, "/subscriptions", body, 201)["id"] == subscription["id"]
        identity = UUID(subscription["id"])
        state = dict(content="合成订阅原文", version="v1", mode="success", calls=0)
        table = tables.research_subscriptions

        def current():
            response = client.get(base + "/subscriptions", headers=headers)
            assert response.status_code == 200, response.text
            return response.json()

        def act(name):
            row = current()["items"][0]
            return post(
                client,
                base,
                headers,
                f"/subscriptions/{identity}/actions",
                {**command(row), "action": name, "reason": "合成恢复核对"},
            )

        def due():
            with scope.engine.begin() as c:
                c.execute(
                    table.update()
                    .where(table.c.id == identity)
                    .values(
                        next_due_at=datetime.now(UTC) - timedelta(seconds=1),
                        version=table.c.version + 1,
                        updated_at=datetime.now(UTC),
                    )
                )

        class Transport:
            def __init__(self, **kwargs):
                pass

            def get(self, url):
                assert url == body["url"]
                state["calls"] += 1
                if state["mode"] == "fail":
                    raise ReachFetchError("合成上游不可用")
                if state["mode"] == "pause":
                    act("pause")  # Network boundary holds no domain transaction locks.
                if state["mode"] == "interrupt":
                    raise SystemExit("合成进程中断，保留原租约以验证接管")
                return ReachResponse(
                    status_code=200,
                    content=state["content"],
                    content_type="text/plain",
                    byte_size=len(state["content"].encode()),
                    source_version=state["version"],
                )

        monkeypatch.setattr(research_collection, "PublicReachTransport", Transport)
        worker = ResearchCollectionWorker(scope.engine, enabled=True)
        assert ResearchCollectionWorker(scope.engine).run_once() == {"status": "disabled"}
        assert state["calls"] == 0
        assert worker.run_once()["status"] == "completed"
        first = current()["runs"][0]
        assert first["content_changed"]
        due()
        assert worker.run_once()["status"] == "completed"
        repeated = current()["runs"][0]
        assert repeated["snapshot_id"] == first["snapshot_id"] and not repeated["content_changed"]
        state["version"] = "v2"
        due()
        assert worker.run_once()["status"] == "completed"
        versioned = current()["runs"][0]
        assert versioned["snapshot_id"] != first["snapshot_id"] and not versioned["content_changed"]
        state["content"] = "合成变化后的原文"
        due()
        assert worker.run_once()["status"] == "completed"
        assert current()["runs"][0]["content_changed"]

        state["mode"] = "fail"
        for n in range(1, 6):
            due()
            before = datetime.now(UTC)
            assert worker.run_once()["status"] == ("quarantined" if n == 5 else "retry_scheduled")
            row = current()["items"][0]
            assert row["consecutive_failures"] == n and row["lease_token"] is None
            if n < 5:
                retry_at = datetime.fromisoformat(row["next_due_at"])
                assert before + timedelta(minutes=5 * 2 ** (n - 1)) <= retry_at
                assert retry_at <= datetime.now(UTC) + timedelta(minutes=5 * 2 ** (n - 1))
            else:
                assert row["next_due_at"] is None
        calls = state["calls"]
        assert worker.run_once()["status"] == "idle" and state["calls"] == calls
        assert act("resume")["consecutive_failures"] == 0

        state["mode"] = "pause"
        assert worker.run_once()["status"] == "discarded"
        paused = current()
        assert paused["items"][0]["status"] == "paused"
        assert paused["runs"][0]["status"] == "cancelled"
        assert paused["runs"][0]["snapshot_id"] is None
        assert act("resume")["status"] == "active"
        state["mode"] = "interrupt"
        with pytest.raises(SystemExit, match="合成进程中断"):
            worker.run_once()
        pending = current()["runs"][0]
        assert pending["status"] == "running"
        with scope.engine.begin() as c:
            c.execute(
                table.update()
                .where(table.c.id == identity)
                .values(
                    lease_expires_at=datetime.now(UTC) - timedelta(seconds=1),
                    version=table.c.version + 1,
                    updated_at=datetime.now(UTC),
                )
            )
        assert worker.run_once()["status"] == "recovered"
        recovered = current()
        assert recovered["runs"][0]["id"] == pending["id"]
        assert recovered["runs"][0]["status"] == "timed_out"
        assert recovered["items"][0]["consecutive_failures"] == 1

        due()
        with scope.engine.begin() as c:
            c.execute(
                tables.users.update()
                .where(tables.users.c.id == scope.owner_id)
                .values(is_active=False)
            )
        assert worker.run_once()["status"] == "quarantined"
        assert state["calls"] == calls + 2  # Pause and interrupted attempts only; no revoked read.
        with scope.engine.connect() as c:
            row = c.execute(select(table).where(table.c.id == identity)).mappings().one()
            assert row["last_error_code"] == "COLLECTION_AUTHORIZATION_CHANGED"
            assert (
                c.execute(select(func.count()).select_from(tables.evidence_snapshots)).scalar_one()
                == 3
            )
            assert (
                c.execute(select(func.count()).select_from(tables.model_invocations)).scalar_one()
                == 0
            )
            audits = (
                c.execute(
                    select(tables.audit_log).where(
                        tables.audit_log.c.tenant_id == scope.tenant_id,
                        tables.audit_log.c.action.like("research_subscription.%"),
                    )
                )
                .mappings()
                .all()
            )
            assert audits and any(a["after_snapshot"]["collection_in_progress"] for a in audits)
            for audit in audits:
                for snapshot in (audit["before_snapshot"], audit["after_snapshot"]):
                    assert snapshot is None or "lease_token" not in snapshot

        # Named ownership transfer uses the same safe audit, pauses collection and retries exactly.
        successor = uuid4()
        with scope.engine.begin() as c:
            password = c.execute(
                select(tables.users.c.password_hash).where(tables.users.c.id == scope.owner_id)
            ).scalar_one()
            c.execute(
                tables.users.update()
                .where(tables.users.c.id == scope.owner_id)
                .values(is_active=True)
            )
            c.execute(
                tables.users.insert().values(
                    id=successor,
                    tenant_id=scope.tenant_id,
                    username="subscription-successor",
                    display_name="合成订阅接收人",
                    role="engineer",
                    password_hash=password,
                    is_active=True,
                )
            )
            grants = dict(
                tenant_id=scope.tenant_id,
                market_space_id=UUID(base.rsplit("/", 1)[1]),
                user_id=successor,
                access="contributor",
                added_by_user_id=scope.owner_id,
            )
            c.execute(tables.market_space_members.insert().values(**grants))
            c.execute(
                tables.product_line_members.insert().values(
                    **grants, product_line_id=UUID(seed["line"]["id"])
                )
            )
        path = f"/responsibilities/subscription/{identity}"
        read = client.get(base + path, headers=headers)
        assert read.status_code == 200, read.text
        reassignment = dict(
            request_id=str(uuid4()),
            expected_digest=read.json()["digest"],
            role="owner",
            user_id=str(successor),
            reason="合成具名转交并暂停原订阅",
        )
        receipt = post(client, base, headers, path, reassignment)
        assert receipt["record"]["status"] == "paused"
        assert receipt["record"]["owner_user_id"] == str(successor)
        assert "lease_token" not in receipt["record"]
        assert post(client, base, headers, path, reassignment) == receipt
    finally:
        scope.dispose()
