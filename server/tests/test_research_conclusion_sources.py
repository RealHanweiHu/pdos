"""New research completion requires snapshots; historical records remain readable."""

import socket
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy import Engine

from app.contracts.object_operations import ResearchConcludeRequest
from app.domain.product_workspace import CancelResearch


@pytest.fixture(autouse=True)
def forbid_external_access(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("Pure contract tests must not access database or network")

    monkeypatch.setattr(Engine, "connect", forbidden)
    monkeypatch.setattr(Engine, "begin", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)


def payload() -> dict[str, Any]:
    return {
        "expected_version": 1,
        "payload_digest": "a" * 64,
        "idempotency_key": "conclusion-1",
        "research_task_id": UUID(int=1),
        "conclusion": "未发现支持该假设的结果，保留样本局限",
        "findings": [],
        "unresolved": ["需要扩大样本"],
        "source_refs": [],
    }


def snapshot_ref(kind: str = "evidence_snapshot") -> dict[str, Any]:
    return {
        "tenant_id": UUID(int=2),
        "kind": kind,
        "ref_id": UUID(int=3),
        "as_of": "2026-09-30T12:00:00Z",
        "digest": "b" * 64,
    }


@pytest.mark.parametrize("findings", [[], ["一项发现"]])
def test_every_new_conclusion_requires_at_least_one_snapshot(findings: list[str]) -> None:
    with pytest.raises(ValidationError, match="research_conclusion_requires_snapshot_sources"):
        ResearchConcludeRequest.model_validate({**payload(), "findings": findings})


@pytest.mark.parametrize("kind", ["research_task", "product", "external_document"])
def test_non_snapshot_reference_cannot_complete_research(kind: str) -> None:
    with pytest.raises(ValidationError, match="research_conclusion_requires_snapshot_sources"):
        ResearchConcludeRequest.model_validate({**payload(), "source_refs": [snapshot_ref(kind)]})


def test_no_findings_conclusion_can_reference_actual_result_snapshot() -> None:
    command = ResearchConcludeRequest.model_validate({**payload(), "source_refs": [snapshot_ref()]})
    assert command.findings == ()
    assert command.source_refs[0].kind == "evidence_snapshot"
    # UUID/type/digest shape is not authority: the domain still reloads the real snapshot.
    assert command.source_refs[0].ref_id == UUID(int=3)


def test_no_evidence_stop_uses_existing_cancel_command() -> None:
    command = CancelResearch.model_validate(
        {
            key: value
            for key, value in payload().items()
            if key in ("expected_version", "payload_digest", "idempotency_key")
        }
        | {"reason": "未获得可用证据，停止本轮研究"}
    )
    assert command.reason == "未获得可用证据，停止本轮研究"
