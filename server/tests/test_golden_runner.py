from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest
from pydantic import SecretStr

from app.ai.golden_runner import evaluate_candidate
from app.ai.golden_suite import load_golden_suite
from app.ai.model_catalog import AgentTier, ProtocolKind, ProviderName, ResolvedModelRoute
from app.ai.provider_adapters import ChatMessage, ProviderResponse
from app.ai.qualifications import GoldenQualificationFileError, load_golden_qualifications


class FakeAdapter:
    def __init__(self, responses: list[ProviderResponse]) -> None:
        self.responses = responses
        self.calls: list[Sequence[ChatMessage]] = []

    def complete(
        self,
        route: ResolvedModelRoute,
        messages: Sequence[ChatMessage],
    ) -> ProviderResponse:
        self.calls.append(messages)
        return self.responses.pop(0)


def response(content: str) -> ProviderResponse:
    return ProviderResponse(
        content=content,
        input_tokens=10,
        output_tokens=4,
        request_id="fake-request",
        model_version="MiniMax-M2.7-test",
    )


def write_suite(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "suite_version": "s2-gateway-v1",
                "pass_threshold": 1.0,
                "cases": [
                    {
                        "id": "risk-high",
                        "system_prompt": "Return only the requested JSON.",
                        "instruction": "Classify the project risk from the structured facts.",
                        "context": {
                            "project": {"code": "PRJ-1", "name": "Drive", "status": "active"},
                            "execution_metrics": {"open_issue_count": 4},
                            "raw_document": "never send this original",
                        },
                        "expected": {"label": "high", "evidence_codes": ["OPEN_ISSUES"]},
                    },
                    {
                        "id": "risk-low",
                        "system_prompt": "Return only the requested JSON.",
                        "instruction": "Classify the project risk from the structured facts.",
                        "context": {
                            "project": {"code": "PRJ-2", "name": "Pump", "status": "active"},
                            "execution_metrics": {"open_issue_count": 0},
                        },
                        "expected": {"label": "low", "evidence_codes": []},
                    },
                ],
            },
            ensure_ascii=False,
        )
    )


def route() -> ResolvedModelRoute:
    return ResolvedModelRoute(
        provider=ProviderName.MINIMAX,
        protocol=ProtocolKind.OPENAI_COMPATIBLE,
        base_url="http://127.0.0.1:39111/v1",
        model="MiniMax-M2.7",
        api_key=SecretStr("test-secret"),
        agent_tier=AgentTier.DEFAULT,
    )


def test_runner_executes_the_full_suite_and_never_writes_qualification(
    tmp_path: Path,
) -> None:
    suite_path = tmp_path / "suite.json"
    qualification_path = tmp_path / "model-qualifications.json"
    write_suite(suite_path)
    loaded = load_golden_suite(suite_path)
    adapter = FakeAdapter(
        [
            response("not-json"),
            response('{"label":"high","evidence_codes":["OPEN_ISSUES"]}'),
            response('{"label":"medium","evidence_codes":[]}'),
        ]
    )

    report = evaluate_candidate(route(), adapter, loaded, max_structured_attempts=2)

    assert report.status == "failed"
    assert report.pass_rate == 0.5
    assert [(case.case_id, case.passed, case.attempts) for case in report.cases] == [
        ("risk-high", True, 2),
        ("risk-low", False, 1),
    ]
    assert len(adapter.calls) == 3
    assert "never send this original" not in " ".join(
        message.content for messages in adapter.calls for message in messages
    )
    assert not qualification_path.exists()


def test_runtime_rejects_a_published_qualification_for_another_suite(tmp_path: Path) -> None:
    suite_path = tmp_path / "suite.json"
    qualification_path = tmp_path / "model-qualifications.json"
    write_suite(suite_path)
    loaded = load_golden_suite(suite_path)
    qualification_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "suite_version": loaded.suite.suite_version,
                "suite_digest": "sha256:wrong-suite",
                "models": [{"provider": "minimax", "model": "MiniMax-M2.7", "status": "passed"}],
            }
        )
    )

    with pytest.raises(GoldenQualificationFileError):
        load_golden_qualifications(qualification_path, trusted_suite=loaded)


def test_checked_in_trusted_suite_and_empty_publication_match() -> None:
    server_root = Path(__file__).resolve().parents[1]
    loaded = load_golden_suite(server_root / "golden" / "model-gateway-v1.json")

    assert (
        load_golden_qualifications(
            server_root / "golden" / "model-qualifications.json",
            trusted_suite=loaded,
        )
        == []
    )
