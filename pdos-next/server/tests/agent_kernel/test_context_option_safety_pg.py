"""Native synthetic source/scan and HTTP/RLS paging regressions; root runs PG.

No model, index fixture, mock current/safe gate or forged scan receipt is used.
The configured synthetic scanner is the existing security fixture; changing its
actual configured rules is the same supported stale-scan case as retrieval PG.
"""
# ruff: noqa: F401, F811 -- imported PG fixture dependencies are intentionally re-exported

from dataclasses import replace
from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from pdos_next.database import tenant_session
from pdos_next.domain.preproject.category_models import KnowledgeEntry
from pdos_next.enterprise_search.schemas import SOURCE_TYPES
from pdos_next.enterprise_search.sources import prepare_read, retrieval_catalog
from pdos_next.models import Grant, OriginalSecurity, UploadedOriginal, now
from pdos_next.original_security import configure
from tests.agent_kernel.test_context_corrections_pg import finish, work_path
from tests.agent_kernel.test_run_continuation import start
from tests.enterprise_search.test_retrieval_pg import register
from tests.preproject.test_g0 import post, request
from tests.test_original_security import parsed, security_work, uploaded

PREFIX = "品类知识 · boundary"


def knowledge(setup, number, *, ref=None, supersedes=None):
    payload = {
        "kind": "boundary",
        "content": {"definition": f"Synthetic native fact {number}"},
        "source_refs": [ref] if ref else [],
    }
    if supersedes is not None:
        payload["supersedes"] = supersedes
    response = post(setup, request(setup, "category.knowledge.add", payload))
    assert response.status_code == 200, response.text
    lineage = UUID(response.json()["subject_id"])
    version = supersedes["expected_version"] + 1 if supersedes else 1
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
        read_snapshot=True,
    ) as s:
        identity = s.scalar(
            select(KnowledgeEntry.id).where(
                KnowledgeEntry.tenant_id == setup.tenant,
                KnowledgeEntry.lineage_id == lineage,
                KnowledgeEntry.version == version,
            )
        )
        assert identity is not None
    return identity, lineage


def chooser(setup):
    parent, accepted = start(setup)
    finish(setup, parent)
    return work_path(setup, accepted["session_id"]) + "/context-options"


@pytest.mark.parametrize("valid_count", [1, 41])
def test_scan_invalid_41_first_candidates_cannot_hide_later_valid_options(
    security_work, valid_count
):
    work, setup = security_work, security_work.setup
    original = uploaded(work, visibility="category", content="更换密封圈。".encode())
    artifact = parsed(work, original)
    ref = {"type": "artifact", "id": str(artifact), "version": 1, "line": 1, "quote": "更换密封圈"}
    invalid = {knowledge(setup, n, ref=ref)[0] for n in range(41)}
    valid = [
        register(setup, PREFIX + f" Z{n:03}", "Ordinary source without an uploaded original.")
        for n in range(valid_count)
    ]
    endpoint = chooser(setup)
    scans = work.scanner.calls
    # Establish the exact old-page failure condition against actual authority,
    # not assumptions about database collation or insertion order.
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
        read_snapshot=True,
    ) as s:
        prepare_read(s, SOURCE_TYPES)
        source = retrieval_catalog(SOURCE_TYPES)
        first = s.scalars(
            select(source.c.source_id)
            .where(
                source.c.tenant_id == setup.tenant,
                source.c.category_id == setup.category,
                source.c.title.icontains(PREFIX, autoescape=True),
            )
            .order_by(source.c.title, source.c.source_type, source.c.source_id)
            .limit(41)
        ).all()
        assert set(first) == invalid
    configuration = replace(
        work.runtime.configuration,
        scanner=replace(
            work.runtime.configuration.scanner,
            rules_version="context-option-current-rules@2",
        ),
    )
    configure(setup.engine, replace(work.runtime, configuration=configuration))
    # Persisted clean/status metadata stays unchanged; only the real current gate
    # knows that these receipts are bound to a different scanner configuration.
    with Session(setup.admin) as s:
        assert s.get(UploadedOriginal, original).scan_status == "clean"
        state = s.scalar(
            select(OriginalSecurity).where(
                OriginalSecurity.tenant_id == setup.tenant,
                OriginalSecurity.original_id == original,
            )
        )
        assert state is not None and state.current_request_id is not None
    response = setup.client.get(endpoint, params={"query": PREFIX}, headers=setup.headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["source_id"] for item in body["items"]] == [str(i) for i in valid[:40]]
    assert body["has_more"] is (valid_count > 40)
    assert all(item["source_type"] == "artifact" for item in body["items"])
    assert not invalid & {UUID(item["source_id"]) for item in body["items"]}
    assert work.scanner.calls == scans
    # Current category revocation hides the metadata chooser itself without
    # exposing any previously returned title or source identifier.
    with Session(setup.admin) as s, s.begin():
        s.execute(
            update(Grant)
            .where(
                Grant.tenant_id == setup.tenant,
                Grant.category_id == setup.category,
                Grant.principal_id == setup.human,
            )
            .values(expires_at=now() - timedelta(seconds=1))
        )
    denied = setup.client.get(endpoint, params={"query": PREFIX}, headers=setup.headers)
    assert denied.status_code == 403
    assert PREFIX not in denied.text and not any(str(i) in denied.text for i in valid)


def test_native_knowledge_history_keeps_exact_entry_versions_and_owner_only_read(setup):
    first, lineage = knowledge(setup, "historical-original")
    second, same = knowledge(
        setup,
        "native-successor",
        supersedes={
            "lineage_id": str(lineage),
            "expected_version": 1,
        },
    )
    assert same == lineage and first != second
    endpoint = chooser(setup)
    response = setup.client.get(endpoint, params={"object_id": str(lineage)}, headers=setup.headers)
    assert response.status_code == 200, response.text
    body = response.json()
    by_id = {item["source_id"]: item for item in body["items"]}
    assert set(by_id) == {str(first), str(second)}
    assert by_id[str(first)]["source_revision"] == 1 and by_id[str(first)]["is_current"] is False
    assert by_id[str(second)]["source_revision"] == 2 and by_id[str(second)]["is_current"] is True
    assert body["has_more"] is False and body["artifact_history"] == "unavailable"
    denied = setup.client.get(
        endpoint,
        params={"object_id": str(lineage)},
        headers={
            "Authorization": f"Bearer {setup.tokens[setup.peer]}",
        },
    )
    assert denied.status_code in {403, 404}
    assert (
        PREFIX not in denied.text
        and str(first) not in denied.text
        and str(second) not in denied.text
    )
