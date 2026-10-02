"""Queued PostgreSQL/API D22 candidates; synthetic data, no real handoff qualification."""

from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from queue import Queue
from time import monotonic, sleep
from typing import Any, Literal
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, func, select, text

from app.auth.passwords import PasswordService
from app.db.schema import tables
from app.domain import product_master_references
from app.domain.product_workspace import _emit
from tests.product_master_reference_fixtures import MasterCandidate, seed_master_candidate
from tests.product_master_reference_fixtures import (
    master_reference_database_guard as master_reference_database_guard,
)
from tests.test_product_manager_loop_api import command
from tests.test_product_planning_findings_api import post, release_definition
from tests.test_product_work_preparation_api import space
from tests.test_test_runs_api import PASSWORD, Scope
from tests.test_test_runs_api import client as client
from tests.test_test_runs_api import isolated_test_run_database as isolated_test_run_database


@pytest.fixture
def candidate(
    client: TestClient,
    isolated_test_run_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[MasterCandidate]:
    # Existing isolated fixture owns tenant cleanup; dispose only releases this engine.
    scope = Scope(client, isolated_test_run_database)
    try:
        yield seed_master_candidate(client, scope, tmp_path, monkeypatch)
    finally:
        scope.dispose()


def catalog(candidate: MasterCandidate) -> list[dict[str, Any]]:
    response = candidate.client.get(candidate.base + "/products", headers=candidate.headers)
    assert response.status_code == 200, response.text
    return list(response.json()["nodes"])


def member(candidate: MasterCandidate, access: str, role: str) -> tuple[UUID, dict[str, str]]:
    username = "master-" + uuid4().hex[:12]
    identity = candidate.scope._insert(
        tables.users,
        dict(
            username=username,
            display_name="合成引用核对人",
            role=role,
            password_hash=PasswordService().hash(PASSWORD),
            is_active=True,
        ),
    )
    response = candidate.client.put(
        candidate.base + f"/members/{identity}", headers=candidate.headers, json={"access": access}
    )
    assert response.status_code == 204, response.text
    line = next(row for row in catalog(candidate) if row["level"] == "line")
    post(
        candidate.client,
        candidate.base,
        candidate.headers,
        f"/products/{line['id']}/members",
        {**command(line), "user_id": str(identity), "access": access},
    )
    response = candidate.client.post(
        "/api/auth/login", json=dict(tenant_slug="beepump", username=username, password=PASSWORD)
    )
    assert response.status_code == 200, response.text
    return identity, {"Authorization": "Bearer " + response.json()["access_token"]}


def head(response: dict[str, Any], previous_id: str | None = None) -> dict[str, Any]:
    return next(
        row
        for row in response["items"]
        if row["is_head"]
        and row["action"] != "withdraw"
        and (previous_id is None or row["previous_id"] == previous_id)
    )


def test_three_master_kinds_append_history_and_original_requests_once(
    candidate: MasterCandidate,
) -> None:
    for system, kind in (
        ("erp", "material"),
        ("erp", "product"),
        ("plm", "product"),
        ("plm", "cad_revision"),
    ):
        body = candidate.request(
            system_kind=system,
            master_kind=kind,
            source_system=f"SYNTHETIC_{system}",
            external_id=f"TEST-{kind}",
        )
        before = candidate.state()
        registered = candidate.save(body)
        first = head(registered)
        saved = candidate.state()
        assert len(saved[0]) == len(before[0]) + 1
        assert saved[1:] == (before[1] + 1, before[2] + 1)
        assert candidate.save(body) == registered
        assert candidate.state() == saved
        candidate.save({**body, "reason": "相同请求改变用途"}, 409)
        assert candidate.state() == saved
        corrected = candidate.save(
            candidate.request(
                action="correct",
                previous_id=first["id"],
                system_kind=system,
                master_kind=kind,
                source_system=f"SYNTHETIC_{system}",
                external_id=f"TEST-{kind}",
                external_revision="B",
            )
        )
        second = head(corrected, first["id"])
        candidate.save(
            candidate.request(
                action="withdraw",
                previous_id=second["id"],
                system_kind=system,
                master_kind=kind,
                source_system=f"SYNTHETIC_{system}",
                external_id=f"TEST-{kind}",
                external_revision="B",
            )
        )
        final = candidate.state()
        assert final[0][: len(saved[0])] == saved[0]
        third = next(row for row in final[0] if str(row["previous_id"]) == second["id"])
        second_raw = next(row for row in final[0] if str(row["id"]) == second["id"])
        for key in (
            *product_master_references.FROZEN_FIELDS,
            "definition_ref",
            "product_snapshot",
            "context_digest",
        ):
            assert third[key] == second_raw[key]
    with candidate.scope.engine.connect() as c:
        assert (
            c.execute(
                select(func.count())
                .select_from(tables.model_invocations)
                .where(tables.model_invocations.c.tenant_id == candidate.scope.tenant_id)
            ).scalar_one()
            == 0
        )


def test_definition_replacement_withdrawal_and_product_retirement_preserve_old_reference(
    candidate: MasterCandidate,
) -> None:
    original = candidate.request()
    first = head(candidate.save(original))
    frozen = deepcopy(candidate.state()[0])
    content = deepcopy(candidate.definition["content"])
    content["items"][0]["target_value"] = "111"
    content["change_reason"] = "合成替代后引用核对"
    replacement = post(
        candidate.client,
        candidate.base,
        candidate.headers,
        "/definitions",
        dict(
            request_id=str(uuid4()),
            product_id=str(candidate.product_id),
            strategy_id=candidate.definition["strategy_id"],
            supersedes_id=candidate.definition["id"],
            content=content,
        ),
        201,
    )
    replacement = release_definition(
        candidate.client, candidate.base, candidate.headers, replacement
    )
    assert candidate.read()["items"][0]["context_status"] == "stale"
    candidate.save({**original, "request_id": str(uuid4())}, 409)
    replay_before = candidate.state()
    candidate.save(original)
    assert candidate.state() == replay_before
    post(
        candidate.client,
        candidate.base,
        candidate.headers,
        f"/definitions/{replacement['id']}/actions",
        {
            **command(replacement),
            "action": "withdraw",
            "reason": "合成撤回",
            "expected_release_id": replacement["current_release"]["id"],
        },
    )
    product = next(row for row in catalog(candidate) if row["id"] == str(candidate.product_id))
    post(
        candidate.client,
        candidate.base,
        candidate.headers,
        f"/products/{candidate.product_id}/changes",
        {
            **command(product),
            **{key: product[key] for key in ("name", "owner_user_id", "regions", "channels")},
            "lifecycle": "retired",
            "reason": "合成退役",
        },
    )
    candidate.save(candidate.request(external_id="NEW-RETIRED"), 409)
    result = candidate.save(candidate.request(action="withdraw", previous_id=first["id"]))
    assert result["items"][-1]["context_status"] == "no_current_release"
    assert candidate.state()[0][:1] == frozen


def test_viewer_read_manager_write_actor_conflict_and_current_revocation(
    candidate: MasterCandidate,
) -> None:
    other_space = space(candidate.client, candidate.headers)
    wrong_url = (
        f"/api/product-work/spaces/{other_space}/products/{candidate.product_id}/master-references"
    )
    scoped_body = candidate.request()
    before_scope = candidate.state()
    assert candidate.client.get(wrong_url, headers=candidate.headers).status_code == 403
    assert (
        candidate.client.post(wrong_url, headers=candidate.headers, json=scoped_body).status_code
        == 403
    )
    assert candidate.state() == before_scope
    _, viewer_headers = member(candidate, "viewer", "engineer")
    assert candidate.read(viewer_headers)["items"] == []
    before = candidate.state()
    candidate.save(candidate.request(), 403, viewer_headers)
    assert candidate.state() == before
    manager, manager_headers = member(candidate, "manager", "project_manager")
    body = candidate.request()
    candidate.save(body, headers=manager_headers)
    saved = candidate.state()
    candidate.save(body, 403)  # Owner is currently allowed, but is not original actor.
    assert candidate.state() == saved
    response = candidate.client.put(
        candidate.base + f"/members/{manager}", headers=candidate.headers, json={"access": None}
    )
    assert response.status_code == 204, response.text
    revoked = candidate.state()
    assert candidate.client.get(candidate.url, headers=manager_headers).status_code == 403
    candidate.save(body, 403, manager_headers)
    assert candidate.state() == revoked


def test_metadata_and_whitespace_sources_reject_before_receipt_event_audit(
    candidate: MasterCandidate,
) -> None:
    variants: tuple[Literal["metadata", "blank"], ...] = ("metadata", "blank")
    for variant in variants:
        ref = candidate.evidence(variant)
        body = candidate.request(sources=[ref])
        before = candidate.state()
        rejected = candidate.save(body, 409)
        assert "正文" in str(rejected)
        assert candidate.state() == before
    original_request = candidate.request()
    registered = candidate.save(original_request)
    assert len(registered["items"]) == 1
    source_id: UUID
    with candidate.scope.engine.connect() as c:
        source_id = c.execute(
            select(tables.evidence_snapshots.c.source_id).where(
                tables.evidence_snapshots.c.id == UUID(candidate.reference["ref_id"])
            )
        ).scalar_one()
    # Source lifecycle is mutable; captured content and snapshots stay untouched.
    with candidate.scope.engine.begin() as c:
        c.execute(
            tables.research_sources.update()
            .where(tables.research_sources.c.id == source_id)
            .values(status="disabled")
        )
    before = candidate.state()
    response = candidate.client.get(candidate.url, headers=candidate.headers)
    assert response.status_code == 409 and candidate.reference["ref_id"] not in response.text
    candidate.save(original_request, 409)
    assert candidate.state() == before


def race(
    candidate: MasterCandidate,
    bodies: tuple[dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    record_property: Callable[[str, object], None],
) -> list[int]:
    """Observe two actual API transactions blocked on the same real space row."""
    pids: Queue[int] = Queue()
    actual_context = product_master_references._context

    def observed_context(
        connection: Connection,
        context: Any,
        space_id: UUID,
        product_id: UUID,
        *,
        write: bool = False,
    ) -> dict[str, Any]:
        if write:
            # Session-local limits bound a failed observation without replacing any
            # authorization, transaction, or business SQL in the actual context.
            connection.execute(text("SET LOCAL lock_timeout = '15s'"))
            connection.execute(text("SET LOCAL statement_timeout = '20s'"))
            pids.put(int(connection.execute(select(func.pg_backend_pid())).scalar_one()))
        return actual_context(connection, context, space_id, product_id, write=write)

    def invoke(body: dict[str, Any]) -> int:
        return candidate.client.post(
            candidate.url, headers=candidate.headers, json=body, timeout=30
        ).status_code

    observations: list[dict[str, Any]] = []
    with monkeypatch.context() as patch:
        patch.setattr(product_master_references, "_context", observed_context)
        with candidate.scope.engine.connect() as blocker:
            transaction = blocker.begin()
            # Fail promptly if an unrelated test holds the observation target.
            blocker.execute(text("SET LOCAL lock_timeout = '5s'"))
            blocker.execute(text("SET LOCAL statement_timeout = '10s'"))
            space_id = UUID(candidate.base.rsplit("/", 1)[-1])
            locked_id = blocker.execute(
                select(tables.market_spaces.c.id)
                .where(
                    tables.market_spaces.c.tenant_id == candidate.scope.tenant_id,
                    tables.market_spaces.c.id == space_id,
                )
                .with_for_update()
            ).scalar_one()
            blocker_pid = int(blocker.execute(select(func.pg_backend_pid())).scalar_one())
            executor = ThreadPoolExecutor(max_workers=2)
            futures = [executor.submit(invoke, body) for body in bodies]
            backend_pids: list[int] = []
            try:
                for _ in range(2):
                    backend_pids.append(pids.get(timeout=8))
                assert len(set(backend_pids)) == 2 and blocker_pid not in backend_pids
                deadline = monotonic() + 8
                with candidate.scope.engine.connect().execution_options(
                    isolation_level="AUTOCOMMIT"
                ) as monitor:
                    monitor.execute(text("SET statement_timeout = '3s'"))
                    try:
                        while monotonic() < deadline:
                            observations = [
                                dict(row)
                                for row in monitor.execute(
                                    text(
                                        "SELECT pid, state, wait_event_type, wait_event, query, "
                                        "pg_blocking_pids(pid) AS blocking_pids "
                                        "FROM pg_stat_activity WHERE pid=ANY(:pids)"
                                    ),
                                    {"pids": backend_pids},
                                ).mappings()
                            ]
                            if len(observations) == 2 and all(
                                row["wait_event_type"] == "Lock" for row in observations
                            ):
                                break
                            sleep(0.02)
                    finally:
                        monitor.execute(text("RESET statement_timeout"))
                assert len(observations) == 2 and all(
                    row["wait_event_type"] == "Lock" for row in observations
                ), f"Both API transactions must simultaneously wait on locks: {observations!r}"
                assert all(
                    "market_spaces" in row["query"] and "FOR UPDATE" in row["query"].upper()
                    for row in observations
                ), f"Both waits must be the actual space row lock: {observations!r}"
            finally:
                # Release the controlling DB lock before waiting for HTTP workers,
                # including PID/monitor/assertion failures. Restore wrapper only
                # after both workers have left their bounded real transactions.
                transaction.rollback()
                try:
                    record_property(
                        "master_reference_lock_overlap",
                        {
                            "market_space_id": str(locked_id),
                            "blocker_pid": blocker_pid,
                            "request_backend_pids": backend_pids,
                            "activity": observations,
                            "request_ids": [body["request_id"] for body in bodies],
                        },
                    )
                    outcomes = [future.result(timeout=30) for future in futures]
                finally:
                    executor.shutdown(wait=True, cancel_futures=True)
    record_property("master_reference_race_http_statuses", sorted(outcomes))
    return sorted(outcomes)


def test_concurrent_same_and_conflicting_requests_have_one_atomic_receipt(
    candidate: MasterCandidate,
    monkeypatch: pytest.MonkeyPatch,
    record_property: Callable[[str, object], None],
) -> None:
    body = candidate.request()
    before = candidate.state()
    assert race(candidate, (body, deepcopy(body)), monkeypatch, record_property) == [201, 201]
    after = candidate.state()
    assert len(after[0]) == len(before[0]) + 1 and after[1:] == (before[1] + 1, before[2] + 1)
    conflict = candidate.request(external_id="CONFLICTING-REQUEST")
    before = candidate.state()
    assert race(
        candidate, (conflict, {**conflict, "external_revision": "B"}), monkeypatch, record_property
    ) == [201, 409]
    after = candidate.state()
    assert len(after[0]) == len(before[0]) + 1 and after[1:] == (before[1] + 1, before[2] + 1)


def test_concurrent_successors_and_duplicate_live_locator_cannot_fork(
    candidate: MasterCandidate,
    monkeypatch: pytest.MonkeyPatch,
    record_property: Callable[[str, object], None],
) -> None:
    original = head(candidate.save(candidate.request()))
    left = candidate.request(action="correct", previous_id=original["id"], external_revision="B")
    right = candidate.request(action="withdraw", previous_id=original["id"])
    before = candidate.state()
    assert race(candidate, (left, right), monkeypatch, record_property) == [201, 409]
    after = candidate.state()
    assert len(after[0]) == len(before[0]) + 1 and after[1:] == (before[1] + 1, before[2] + 1)
    left = candidate.request(external_id="DUPLICATE-LIVE")
    right = {**left, "request_id": str(uuid4())}
    before = candidate.state()
    assert race(candidate, (left, right), monkeypatch, record_property) == [201, 409]
    after = candidate.state()
    assert len(after[0]) == len(before[0]) + 1 and after[1:] == (before[1] + 1, before[2] + 1)


def test_actual_event_emit_failure_rolls_back_receipt(
    candidate: MasterCandidate, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = _emit

    def fail_after_emit(*args: Any, **kwargs: Any) -> None:
        original(*args, **kwargs)
        raise RuntimeError("synthetic failure after actual event and audit insertion")

    monkeypatch.setattr(product_master_references, "_emit", fail_after_emit)
    before = candidate.state()
    with pytest.raises(RuntimeError, match="synthetic failure"):
        candidate.client.post(candidate.url, headers=candidate.headers, json=candidate.request())
    assert candidate.state() == before


def assert_current_authority_denies_history_and_replay(
    candidate: MasterCandidate,
    headers: dict[str, str],
    body: dict[str, Any],
    registered: dict[str, Any],
) -> None:
    """An old receipt cannot bypass current authorization or disclose private identifiers."""
    before = candidate.state()
    for response in (
        candidate.client.get(candidate.url, headers=headers),
        candidate.client.post(candidate.url, headers=headers, json=body),
    ):
        assert response.status_code == 403, response.text
        for private in (
            registered["id"],
            registered["external_id"],
            candidate.reference["ref_id"],
            candidate.reference["digest"],
        ):
            assert private not in response.text
    assert candidate.state() == before


def test_line_acl_revocation_keeps_space_manager_but_denies_history_and_replay(
    candidate: MasterCandidate,
) -> None:
    manager, manager_headers = member(candidate, "manager", "project_manager")
    original_headers = deepcopy(manager_headers)
    body = candidate.request(external_id="PRIVATE-LINE-REFERENCE")
    registered = head(candidate.save(body, headers=manager_headers))
    assert candidate.read(manager_headers)["items"][0]["id"] == registered["id"]
    frozen_rows = deepcopy(candidate.state()[0])
    with candidate.scope.engine.connect() as connection:
        space_grant = dict(
            connection.execute(
                select(tables.market_space_members).where(
                    tables.market_space_members.c.tenant_id == candidate.scope.tenant_id,
                    tables.market_space_members.c.market_space_id
                    == UUID(candidate.base.rsplit("/", 1)[-1]),
                    tables.market_space_members.c.user_id == manager,
                )
            )
            .mappings()
            .one()
        )
    assert space_grant["access"] == "manager"
    line = next(row for row in catalog(candidate) if row["level"] == "line")
    post(
        candidate.client,
        candidate.base,
        candidate.headers,
        f"/products/{line['id']}/members",
        {**command(line), "user_id": str(manager), "access": None},
    )
    with candidate.scope.engine.connect() as connection:
        assert (
            dict(
                connection.execute(
                    select(tables.market_space_members).where(
                        tables.market_space_members.c.tenant_id == candidate.scope.tenant_id,
                        tables.market_space_members.c.market_space_id
                        == space_grant["market_space_id"],
                        tables.market_space_members.c.user_id == manager,
                    )
                )
                .mappings()
                .one()
            )
            == space_grant
        )
    assert candidate.state()[0] == frozen_rows
    assert_current_authority_denies_history_and_replay(candidate, manager_headers, body, registered)
    assert manager_headers == original_headers  # No logout/relogin or replacement JWT.
    line = next(row for row in catalog(candidate) if row["level"] == "line")
    post(
        candidate.client,
        candidate.base,
        candidate.headers,
        f"/products/{line['id']}/members",
        {**command(line), "user_id": str(manager), "access": "manager"},
    )
    restored = candidate.state()
    recovered = candidate.read(manager_headers)  # Explicit fresh read after restored current ACL.
    assert recovered["items"][0]["id"] == registered["id"]
    assert recovered["items"][0]["sources"] == registered["sources"]
    assert candidate.save(body, headers=manager_headers) == recovered
    assert candidate.state() == restored and restored[0] == frozen_rows


def test_role_revocation_rechecks_current_role_with_unchanged_login_token(
    candidate: MasterCandidate,
) -> None:
    manager, manager_headers = member(candidate, "manager", "project_manager")
    original_headers = deepcopy(manager_headers)
    body = candidate.request(external_id="PRIVATE-ROLE-REFERENCE")
    registered = head(candidate.save(body, headers=manager_headers))
    assert candidate.read(manager_headers)["items"][0]["id"] == registered["id"]
    frozen_rows = deepcopy(candidate.state()[0])
    with candidate.scope.engine.connect() as connection:
        space_grants = [
            dict(row)
            for row in connection.execute(
                select(tables.market_space_members).where(
                    tables.market_space_members.c.tenant_id == candidate.scope.tenant_id,
                    tables.market_space_members.c.user_id == manager,
                )
            ).mappings()
        ]
        line_grants = [
            dict(row)
            for row in connection.execute(
                select(tables.product_line_members).where(
                    tables.product_line_members.c.tenant_id == candidate.scope.tenant_id,
                    tables.product_line_members.c.user_id == manager,
                )
            ).mappings()
        ]
    response = candidate.client.patch(
        f"/api/admin/users/{manager}", headers=candidate.headers, json={"role": "supplier"}
    )
    assert response.status_code == 200 and response.json()["role"] == "supplier", response.text
    with candidate.scope.engine.connect() as connection:
        assert [
            dict(row)
            for row in connection.execute(
                select(tables.market_space_members).where(
                    tables.market_space_members.c.tenant_id == candidate.scope.tenant_id,
                    tables.market_space_members.c.user_id == manager,
                )
            ).mappings()
        ] == space_grants
        assert [
            dict(row)
            for row in connection.execute(
                select(tables.product_line_members).where(
                    tables.product_line_members.c.tenant_id == candidate.scope.tenant_id,
                    tables.product_line_members.c.user_id == manager,
                )
            ).mappings()
        ] == line_grants
    assert candidate.state()[0] == frozen_rows
    assert_current_authority_denies_history_and_replay(candidate, manager_headers, body, registered)
    assert manager_headers == original_headers  # The existing JWT must not retain the old role.
    response = candidate.client.patch(
        f"/api/admin/users/{manager}", headers=candidate.headers, json={"role": "project_manager"}
    )
    assert response.status_code == 200 and response.json()["role"] == "project_manager", (
        response.text
    )
    restored = candidate.state()
    recovered = candidate.read(manager_headers)  # Current authorization is re-read server-side.
    assert recovered["items"][0]["id"] == registered["id"]
    assert recovered["items"][0]["sources"] == registered["sources"]
    assert candidate.save(body, headers=manager_headers) == recovered
    assert candidate.state() == restored and restored[0] == frozen_rows
