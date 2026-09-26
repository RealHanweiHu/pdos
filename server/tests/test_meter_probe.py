"""Probe side effects are bounded and opt-in; all adapters here are synthetic."""

import json
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.ai.model_catalog import ResolvedModelRoute
from app.ai.provider_adapters import (
    ChatMessage,
    ProviderCallLimits,
    ProviderRequestError,
    ProviderResponse,
)
from scripts import probe_minimax_input_metering as probe
from tests.test_model_gateway import qualification


@pytest.mark.parametrize("error", [False, True])
def test_probe_is_opt_in_stops_unknown_usage_and_never_overwrites(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: bool
) -> None:
    for name in ["tokenizer.json", "chat_template.jinja", "tokenizer_config.json"]:
        (tmp_path / name).write_text("{}")
    output = tmp_path / "candidate.json"
    argv = ["probe", "--tokenizer-dir", str(tmp_path), "--output", str(output)]
    monkeypatch.setattr(probe, "os", SimpleNamespace(environ={}))
    monkeypatch.setattr(
        probe,
        "dotenv_values",
        lambda _: dict(
            PDOS_LLM_PROVIDER="minimax",
            PDOS_LLM_MODEL="MiniMax-M3",
            PDOS_LLM_API_KEY="synthetic-key",
            PDOS_LLM_BASE_URL="https://synthetic.invalid/v1",
        ),
    )
    monkeypatch.setattr(
        probe,
        "load_golden_qualifications",
        lambda *a, **k: [qualification().model_copy(update={"model": "MiniMax-M3"})],
    )

    class Meter:
        def __init__(self, *args: object) -> None:
            pass

        def count(self, route: ResolvedModelRoute, messages: Sequence[ChatMessage]) -> int:
            return sum(len(m.content.split()) for m in messages)

    calls: list[tuple[ResolvedModelRoute, Sequence[ChatMessage], ProviderCallLimits]] = []

    class Adapter:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def complete_bounded(
            self,
            route: ResolvedModelRoute,
            messages: Sequence[ChatMessage],
            *,
            limits: ProviderCallLimits,
        ) -> ProviderResponse:
            calls.append((route, messages, limits))
            if error:
                raise ProviderRequestError("provider_transport_error", "synthetic")
            return ProviderResponse(
                content="OK",
                input_tokens=5,
                output_tokens=3,
                request_id="synthetic",
                model_version="synthetic",
            )

    monkeypatch.setattr(probe, "LocalTemplateMeter", Meter)
    monkeypatch.setattr(probe, "OpenAICompatibleAdapter", Adapter)
    monkeypatch.setattr("sys.argv", argv)
    probe.main()
    assert not output.exists() and calls == []
    monkeypatch.setattr("sys.argv", argv + ["--execute"])
    probe.main()
    report = json.loads(output.read_text())
    assert len(calls) == (1 if error else 4)
    assert report["status"] == ("stopped_usage_unknown" if error else "observed_not_qualified")
    assert report["qualification_published"] is False
    assert all(c[2].max_output_tokens == 32 for c in calls)
    prior = output.read_bytes()
    with pytest.raises(FileExistsError):
        probe.main()
    assert output.read_bytes() == prior and len(calls) == (1 if error else 4)
