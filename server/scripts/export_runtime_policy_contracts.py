"""Export N0-02 policy candidates without changing frozen N0-01 artifacts.

From server: .venv/bin/python -m scripts.export_runtime_policy_contracts [--check]
"""

from __future__ import annotations

import argparse
import inspect
import json
from hashlib import sha256
from pathlib import Path
from typing import Any

from app.contracts import runtime_adoption, runtime_policy, tool_payloads
from app.contracts.capability_matrix import VERSION, matrix_metadata
from app.contracts.common_objects import Contract
from app.contracts.runtime_policy import (
    DebatePolicy,
    EgressPolicy,
    PolicyPin,
    RetentionPolicy,
    RunBudgetProfile,
)
from scripts.runtime_adoption_inventory import inventory as adoption_inventory

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "docs/contracts/pdos-runtime-v1"


def profile_candidates() -> tuple[RunBudgetProfile, ...]:
    return tuple(
        RunBudgetProfile(
            key=key,
            version=VERSION,
            input_token_limit=inputs,
            output_token_reserve=outputs,
            lineage_token_limit=tokens,
            tool_call_limit=tools,
            model_call_limit=models,
            active_seconds=active,
            lifetime_seconds=lifetime,
        )
        for key, inputs, outputs, tokens, tools, models, active, lifetime in (
            ("short", 16000, 2000, 60000, 8, 3, 120, 86400),
            ("work_package", 32000, 6000, 240000, 20, 6, 600, 604800),
            ("research_discussion", 32000, 4000, 360000, 40, 10, 900, 604800),
        )
    )


def artifacts() -> dict[str, str]:
    schemas: dict[str, Any] = {}
    for module in (runtime_policy, tool_payloads, runtime_adoption):
        for name, model in inspect.getmembers(module, inspect.isclass):
            if (
                model.__module__ != module.__name__
                or not issubclass(model, Contract)
                or name == "ToolResult"
            ):
                continue
            schema = model.model_json_schema(ref_template="#/components/schemas/{model}")
            schemas.update(schema.pop("$defs", {}))
            schemas[name] = schema
    raw: dict[str, Any] = {
        "runtime-policy.openapi.json": {
            "openapi": "3.1.0",
            "info": {
                "title": "PDOS N0-02 frozen policy contracts",
                "version": "1.0.0",
            },
            "paths": {},
            "components": {"schemas": schemas},
            "x-status": "frozen-not-runtime-wired",
            "x-validation": "Pydantic validators supplement JSON Schema; not ACL evidence",
        },
        "runtime-policy-defaults.json": {
            "status": "frozen-not-enabled",
            "source": (
                "complete-design-contract sections 18 and 20; "
                "DC-06/07/08 approved; see freeze-record.md"
            ),
            "budget_profiles": [
                profile.model_dump(mode="json") for profile in profile_candidates()
            ],
            "retention_profiles": [
                RetentionPolicy(key=key, version=VERSION, temporary_body_days=days).model_dump(
                    mode="json"
                )
                for key, days in (("minimal", 7), ("standard", 90), ("extended", 365))
            ],
            "egress": EgressPolicy(
                key="source_aware_egress",
                version=VERSION,
                projection=PolicyPin(key="context_projection", version="pending.v3"),
            ).model_dump(mode="json"),
            "debate": DebatePolicy(key="authorized_discussion", version=VERSION).model_dump(
                mode="json"
            ),
            "existing_config_precedence": "Keep effective old settings until explicit adoption",
            "unconfigured_qualified_window": None,
            "unconfigured_price": None,
            "rate_cards": [],
            "monetary_hard_limit_enabled": False,
            "runtime_registry_changed": False,
        },
    }
    raw["capability-policy-matrix.json"] = matrix_metadata()
    raw["runtime-adoption-inventory.json"] = adoption_inventory()
    result = {name: render(value) for name, value in raw.items()}
    sources = (
        "server/app/contracts/runtime_policy.py",
        "server/app/contracts/runtime_adoption.py",
        "server/scripts/runtime_adoption_inventory.py",
        "server/tests/test_runtime_adoption_contracts.py",
        "server/app/contracts/tool_payloads.py",
        "server/app/contracts/capability_matrix.py",
        "server/app/ai/capability_contract.py",
        "server/app/ai/runtime_contract.py",
        "server/app/ai/tools.py",
        "server/app/contracts/common_objects.py",
        "server/tests/test_runtime_policy_contracts.py",
        "server/tests/test_tool_payload_contracts.py",
        "server/scripts/export_runtime_policy_contracts.py",
        "docs/design/2026-09-10-pdos-complete-design-contract.md",
        "docs/contracts/pdos-v1/freeze-record.md",
        "docs/contracts/pdos-runtime-v1/README.md",
        "docs/contracts/pdos-runtime-v1/freeze-record.md",
        "docs/contracts/pdos-runtime-v1/approved-draft.3/runtime-policy-manifest.json",
        "docs/contracts/pdos-runtime-v1/tool-examples.json",
        "docs/contracts/pdos-runtime-v1/authorization-and-adoption.md",
        "docs/contracts/pdos-runtime-v1/n0-02-freeze-proposal.md",
        "docs/reports/2026-09-10-n0-02-freeze-validation.md",
        "docs/reports/2026-09-10-n0-02-capability-tool-validation.md",
        "docs/reports/2026-09-10-n0-02-policy-contract-validation.md",
    )
    component_paths: set[str] = set(sources)

    def collect_sources(value: Any) -> None:
        if isinstance(value, dict):
            if value.get("status") == "present" and value.get("path") and value.get("sha256"):
                component_paths.add(value["path"])
            for item in value.values():
                collect_sources(item)
        elif isinstance(value, list):
            for item in value:
                collect_sources(item)

    collect_sources(raw["runtime-adoption-inventory.json"])
    result["runtime-policy-manifest.json"] = render(
        {
            "version": "1.0.0",
            "status": "frozen-not-runtime-wired",
            "sources": {
                p: sha256((ROOT / p).read_bytes()).hexdigest() for p in sorted(component_paths)
            },
            "artifacts": {p: sha256(body.encode()).hexdigest() for p, body in result.items()},
        }
    )
    return result


def render(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Compare only; do not write")
    args = parser.parse_args()
    generated = artifacts()
    if args.check:
        drift = [
            name
            for name, body in generated.items()
            if not (OUTPUT / name).exists() or (OUTPUT / name).read_text() != body
        ]
        if drift:
            raise SystemExit("runtime policy artifact drift: " + ", ".join(drift))
    else:
        OUTPUT.mkdir(parents=True, exist_ok=True)
        for name, body in generated.items():
            (OUTPUT / name).write_text(body)
    print(f"{'Checked' if args.check else 'Exported'} {len(generated)} runtime policy artifacts")


if __name__ == "__main__":
    main()
