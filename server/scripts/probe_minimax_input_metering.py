"""Four bounded synthetic probes; writes evidence only, never a qualification."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import TypedDict

import httpx2
from dotenv import dotenv_values

from app.ai.egress import ProviderEgressPolicy
from app.ai.golden_suite import load_golden_suite
from app.ai.input_metering import LocalTemplateMeter
from app.ai.model_catalog import AgentTier, ModelCatalog, ProviderName
from app.ai.provider_adapters import (
    ChatMessage,
    OpenAICompatibleAdapter,
    ProviderCallLimits,
    ProviderRequestError,
)
from app.ai.qualifications import load_golden_qualifications

SERVER_ROOT = Path(__file__).resolve().parents[1]


class Preflight(TypedDict):
    category: str
    local_input_tokens: int
    utf8_bytes: int


def candidate_evidence_path(path: Path) -> Path:
    resolved = path.resolve()
    if resolved.is_relative_to((SERVER_ROOT / "golden").resolve()):
        raise ValueError("candidate evidence cannot be written into the golden trust root")
    return resolved


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tokenizer-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--execute", action="store_true", help="Perform four real synthetic requests"
    )
    args = parser.parse_args()
    args.output = candidate_evidence_path(args.output)
    values = {k: v for k, v in dotenv_values(SERVER_ROOT.parent / ".env").items() if v is not None}
    values.update(os.environ)
    catalog = ModelCatalog.from_environment(values)
    suite = load_golden_suite(SERVER_ROOT / "golden/model-gateway-v1.json")
    qualifications = load_golden_qualifications(
        SERVER_ROOT / "golden/model-qualifications.json", trusted_suite=suite
    )
    route = catalog.resolve_route(
        provider=ProviderName.MINIMAX,
        model="MiniMax-M3",
        agent_tier=AgentTier.DEFAULT,
        qualifications=qualifications,
    )
    assets = {
        name: (args.tokenizer_dir / name).read_bytes()
        for name in ("tokenizer.json", "chat_template.jinja", "tokenizer_config.json")
    }
    meter = LocalTemplateMeter(
        assets["tokenizer.json"], assets["chat_template.jinja"], assets["tokenizer_config.json"]
    )

    def messages(body: str) -> list[ChatMessage]:
        return [
            ChatMessage(role="system", content="Synthetic PDOS input metering probe. Reply OK."),
            ChatMessage(role="user", content=body),
        ]

    rows = [
        ("short_text", messages("Synthetic measurement only. Reply OK.")),
        ("unicode", messages("合成测试：研发、品质、供应链。Café, naïve, 😊. Reply OK.")),
        (
            "structured_schema",
            messages(
                'Return JSON matching {"type":"object","properties":{"risk":'
                '{"enum":["low","high"]}},"required":["risk"]}. '
                "Synthetic project PRJ-TEST: open_tasks=3, overdue_tasks=0."
            ),
        ),
    ]
    low, high = 1, 200000 // len("Synthetic component readiness. ")
    while low < high:
        middle = (low + high + 1) // 2
        if meter.count(route, messages("Synthetic component readiness. " * middle)) <= 16000:
            low = middle
        else:
            high = middle - 1
    rows.append(("near_input_limit", messages("Synthetic component readiness. " * low)))
    preflight: list[Preflight] = [
        {
            "category": category,
            "local_input_tokens": meter.count(route, body),
            "utf8_bytes": sum(len(m.content.encode()) for m in body),
        }
        for category, body in rows
    ]
    assert len(rows) == 4 and all(row["local_input_tokens"] <= 16000 for row in preflight)
    report: dict[str, object] = {
        "status": "preflight_only",
        "qualification_published": False,
        "provider": route.provider.value,
        "model": route.model,
        "base_url": route.base_url,
        "golden_suite_digest": suite.digest,
        "max_output_tokens_per_call": 32,
        "automatic_retries": 0,
        "assets": {name: sha256(body).hexdigest() for name, body in assets.items()},
        "preflight": preflight,
        "observations": [],
    }
    if not args.execute:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    # Never overwrite an earlier evaluation or a trusted publication file.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as output:
        output.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    observations: list[dict[str, object]] = []

    def persist(status: str) -> None:
        report.update(status=status, observations=observations)
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=args.output.parent,
            prefix=args.output.name + ".",
            suffix=".partial",
            delete=False,
        ) as output:
            temporary = Path(output.name)
            try:
                output.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
                output.flush()
                temporary.replace(args.output)
            finally:
                temporary.unlink(missing_ok=True)

    with httpx2.Client(follow_redirects=False, trust_env=False) as client:
        adapter = OpenAICompatibleAdapter(
            client, ProviderEgressPolicy.from_catalog(catalog), request_timeout_seconds=30
        )
        for (category, body), prepared in zip(rows, preflight, strict=True):
            observed: dict[str, object] = {
                **prepared,
                "started_at": datetime.now(UTC).isoformat(),
                "input_sha256": sha256(
                    json.dumps(
                        [m.model_dump() for m in body],
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest(),
            }
            observations.append(observed)
            persist("running")
            try:
                response = adapter.complete_bounded(
                    route, body, limits=ProviderCallLimits(32, "max_tokens")
                )
                observed.update(
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                    cache_read_tokens=response.cache_read_tokens,
                    cache_creation_tokens=response.cache_creation_tokens,
                    request_id=response.request_id,
                    error_code=None,
                )
            except ProviderRequestError as error:
                observed.update(error_code=error.code, request_id=error.request_id)
                if error.usage is None:
                    persist("stopped_usage_unknown")
                    print(f"Stopped: {error.code}; no retry. Evidence: {args.output}")
                    return
                observed.update(asdict(error.usage))
            observed["completed_at"] = datetime.now(UTC).isoformat()
            persist("running")
            print(
                f"{category}: local={prepared['local_input_tokens']} "
                f"actual={observed['input_tokens']} output={observed['output_tokens']}",
                flush=True,
            )
            if int(str(observed["output_tokens"])) > 32:
                persist("stopped_output_limit_not_honored")
                return
    persist("observed_not_qualified")
    print(f"Candidate evidence: {args.output}")


if __name__ == "__main__":
    main()
