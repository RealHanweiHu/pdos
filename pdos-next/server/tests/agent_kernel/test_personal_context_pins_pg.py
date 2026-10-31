"""Actual ordinary personal read pins; no business binding, model or new scan.

Root-only PG draft. Synthetic fixture categories/grants and fault injection are
local test data; no execution of this file is authorized in the subagent stage.
"""
# ruff: noqa: F811 -- registers the existing offline parser/scanner fixture

import hashlib
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.bootstrap import Bootstrap
from pdos_next.agent_kernel.models import AgentRun
from pdos_next.enterprise_search.assistant_materials import read
from pdos_next.enterprise_search.assistant_schemas import MaterialsInput
from pdos_next.enterprise_search.assistant_sources import human_snapshot
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Category, Grant
from pdos_next.original_security import configure
from tests.agent_kernel.test_context_corrections_pg import finish
from tests.agent_kernel.test_run_continuation import scope, start, synthetic_artifact
from tests.test_original_security import parsed, uploaded
from tests.test_original_security import security_work as security_work


def pin_personal(setup, identities):
    parent, accepted = start(setup, personal=True, goal="按选定资料核对，压力单位未知。")
    finish(setup, parent, personal=True)
    path = f"/v1/personal/agent-sessions/{accepted['session_id']}/work-state"
    state = setup.client.get(path, headers=setup.headers).json()
    changed = setup.client.post(
        path,
        headers=setup.headers,
        json={
            "expected_revision": state["revision"],
            "request_key": str(uuid4()),
            "action": "correct_context",
            "context_change": {
                "kind": "limit_sources",
                "sources": [
                    {"source_type": "artifact", "source_id": str(identity), "expected_revision": 1}
                    for identity in identities
                ],
            },
        },
    )
    assert changed.status_code == 200, changed.text
    child, _ = start(
        setup,
        personal=True,
        continue_from_run_id=str(parent),
        goal="只依据这些资料继续核对。",
        context_revision=changed.json()["revision"],
    )
    actual = scope(setup, child, personal=True)
    Bootstrap(setup.engine).project_context(actual, "只依据这些资料继续核对。")
    with Session(setup.admin) as session:
        row = session.get(AgentRun, child)
        assert row.category_id is None and row.product_id is None and row.read_sources == []
        assert row.private_context
    return actual


def material(setup, actual, identities):
    with human_snapshot(setup.engine, actual) as session:
        return read(session, actual, MaterialsInput(artifact_ids=identities), uuid4())


def test_personal_explicit_two_category_pins_read_normally_then_revoke_without_business_scope(
    security_work,
):
    work, setup = security_work, security_work.setup
    first = parsed(work, uploaded(work, content="个人固定原件。".encode()))
    other_category, second = uuid4(), uuid4()
    content = "另一品类本人可读固定资料。"
    with Session(setup.admin) as session, session.begin():
        session.add(
            Category(
                id=other_category,
                tenant_id=setup.tenant,
                owner_id=setup.peer,
                name="合成只读品类",
                purpose="显式纠正的普通 RLS fixture",
            )
        )
        session.flush()
        session.add(
            Grant(
                tenant_id=setup.tenant,
                category_id=other_category,
                principal_id=setup.human,
                can_write=False,
            )
        )
        session.add(
            Artifact(
                id=second,
                tenant_id=setup.tenant,
                category_id=other_category,
                product_id=None,
                owner_id=setup.human,
                title="另一品类本人资料",
                source_label="合成",
                content=content,
                content_hash=hashlib.sha256(content.encode()).hexdigest(),
                visibility="private",
                revision=1,
                status="active",
            )
        )
    actual = pin_personal(setup, [first, second])
    scans = work.scanner.calls
    result = material(setup, actual, [first, second])
    assert result["returned"] == 2 and {row["source_id"] for row in result["items"]} == {
        str(first),
        str(second),
    }
    with Session(setup.admin) as session, session.begin():
        grant = session.scalar(
            select(Grant).where(
                Grant.category_id == other_category, Grant.principal_id == setup.human
            )
        )
        session.delete(grant)
    with pytest.raises(DomainError):
        material(setup, actual, [second])
    assert work.scanner.calls == scans


@pytest.mark.parametrize("changed", ["version", "scan"])
def test_personal_pin_is_not_upgraded_after_version_or_current_scan_proof_changes(
    security_work,
    changed,
):
    work, setup = security_work, security_work.setup
    identity = (
        UUID(str(synthetic_artifact(setup, "固定版本的合成文字资料")))
        if changed == "version"
        else UUID(str(parsed(work, uploaded(work, content="个人固定原件。".encode()))))
    )
    actual = pin_personal(setup, [identity])
    assert material(setup, actual, [identity])["returned"] == 1
    scans = work.scanner.calls
    if changed == "version":
        # Legal synthetic revision drift must not upgrade a fixed personal pin.
        # Artifact content/hash remain immutable under the original DB guard.
        with Session(setup.admin) as session, session.begin():
            row = session.get(Artifact, identity)
            assert row.revision == 1
            row.revision += 1
    else:
        configuration = replace(
            work.runtime.configuration,
            scanner=replace(
                work.runtime.configuration.scanner, rules_version="context-pins-changed@2"
            ),
        )
        configure(setup.engine, replace(work.runtime, configuration=configuration))
    with pytest.raises(DomainError):
        material(setup, actual, [identity])
    assert work.scanner.calls == scans
