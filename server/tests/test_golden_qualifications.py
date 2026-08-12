from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.ai.model_catalog import ProviderName
from app.ai.qualifications import GoldenQualificationFileError, load_golden_qualifications


def test_load_golden_qualifications_preserves_suite_identity(tmp_path: Path) -> None:
    path = tmp_path / "model-qualifications.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "suite_version": "s2-v1",
                "suite_digest": "sha256:trusted-suite",
                "models": [
                    {"provider": "minimax", "model": "MiniMax-M2.7", "status": "passed"},
                    {"provider": "openai", "model": "gpt-5.1", "status": "failed"},
                ],
            }
        )
    )

    qualifications = load_golden_qualifications(path)

    assert [(item.provider, item.model, item.status) for item in qualifications] == [
        (ProviderName.MINIMAX, "MiniMax-M2.7", "passed"),
        (ProviderName.OPENAI, "gpt-5.1", "failed"),
    ]
    assert {item.suite_version for item in qualifications} == {"s2-v1"}
    assert {item.suite_digest for item in qualifications} == {"sha256:trusted-suite"}


@pytest.mark.parametrize(
    "document",
    [
        {"schema_version": 2, "suite_version": "s2-v1", "suite_digest": "x", "models": []},
        {
            "schema_version": 1,
            "suite_version": "s2-v1",
            "suite_digest": "x",
            "models": [
                {
                    "provider": "minimax",
                    "model": "MiniMax-M2.7",
                    "status": "passed",
                    "unexpected": True,
                }
            ],
        },
    ],
)
def test_load_golden_qualifications_rejects_unfrozen_documents(
    tmp_path: Path,
    document: dict[str, object],
) -> None:
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(document))

    with pytest.raises(GoldenQualificationFileError):
        load_golden_qualifications(path)
