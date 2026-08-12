import pytest

from scripts.sprint2_removal_drill import run


def test_removal_drill_has_no_provider_or_finding_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in tuple(__import__("os").environ):
        if key.startswith("PDOS_LLM_"):
            monkeypatch.delenv(key, raising=False)

    report = run()

    assert report.brief_unavailable is True
    assert report.chat_degraded is True
    assert report.finding_count_unchanged is True
    assert report.provider_calls == 0
