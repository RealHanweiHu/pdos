"""Generate local synthetic examples/schemas and read-only source/candidate summaries."""

import ast
import hashlib
import json
import platform
import sys
from copy import deepcopy
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
SERVER = ROOT / "pdos-next/server"
sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(SERVER / "tests"))

from supply_cost_engine.helpers import bom_item, pool, price, ref  # noqa: E402

from pdos_next.engines.supply_cost import (  # noqa: E402
    CostRequest,
    CostResult,
    CoverageRequest,
    CoverageResult,
    calculate_cost,
    calculate_coverage,
)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write(name, data):
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n")


def candidate():
    directories = [SERVER / "pdos_next/engines/supply_cost", SERVER / "tests/supply_cost_engine"]
    records = [
        {"path": str(path.relative_to(ROOT)), "sha256": sha(path.read_bytes())}
        for directory in directories
        for path in sorted(directory.rglob("*.py"))
    ]
    canonical = json.dumps(records, sort_keys=True, separators=(",", ":")).encode()
    write(
        "candidate.json",
        {
            "candidate_sha256": sha(canonical),
            "files": records,
            "scope": "engine/test Python sources only; excludes shared tree",
            "date": "2026-10-02",
        },
    )
    permitted = {
        "hashlib",
        "json",
        "datetime",
        "decimal",
        "typing",
        "pydantic",
        "collections",
        "types",
    }
    local = {"bom", "common", "dto", "units", "costs", "coverage"}
    imports = []
    for path in sorted(directories[0].glob("*.py")):
        source = path.read_text()
        tree = ast.parse(source)
        compile(tree, str(path), "exec")
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [item.name for item in node.names]
                assert all(name.split(".")[0] in permitted for name in names)
                imports.extend(names)
            if isinstance(node, ast.ImportFrom):
                assert node.level <= 1
                assert (
                    node.module in local if node.level else node.module.split(".")[0] in permitted
                )
                imports.append("." * node.level + node.module)
    write(
        "import-audit.json",
        {
            "candidate_sha256": sha(canonical),
            "engine_imports": sorted(set(imports)),
            "allowed_external_modules": sorted(permitted),
            "syntax_compilation": "passed",
            "legacy_database_network_business_imports": "absent",
            "runtime": {
                "python": platform.python_version(),
                "pydantic": version("pydantic"),
                "pytest": version("pytest"),
                "ruff": version("ruff"),
            },
        },
    )


def source_summary():
    entries = [
        (
            "server/app/domain/material_coverage.py",
            ["calculate", "_calculate"],
            "Group repeated BOM demand and separate secured vs unreserved supply; "
            "no old schedule/service",
        ),
        (
            "server/app/domain/cost_rollups.py",
            ["calculate", "_calculate"],
            "Parent-relative quantity, package/child overlap, Decimal, "
            "tax/freight/FX, partial totals/NRE",
        ),
        (
            "server/app/domain/cost_inputs.py",
            ["PriceDraft", "RateDraft", "normalized"],
            "Price denominator, explicit currency/source time/quote tier; no old source/DB lookup",
        ),
        (
            "server/app/domain/build_materials.py",
            ["_capture"],
            "Only bounded hierarchy and one supply level per leaf path; "
            "SQL/business freeze not copied",
        ),
        (
            "server/app/domain/material_allocations.py",
            ["_key", "_pools"],
            "Semantic reference for unique pool key, held subtraction, "
            "stale/frozen/unknown; no SQL/locks",
        ),
        (
            "server/app/domain/material_supply_pools.py",
            ["lock_pools"],
            "Pool identity/reference only; lock function NOT copied or imported",
        ),
        (
            "server/tests/test_material_coverage.py",
            [
                "test_shared_pool_is_counted_once_but_unallocated_stock_does_not_make_kit_ready",
                "test_expected_same_day_and_overdue_supply_stay_out_of_ready_kit",
                "test_decimal_context_cannot_change_fixed_quantity_or_basis_digest",
            ],
            "Counterexample semantics re-created in independent synthetic tests; old tests not run",
        ),
        (
            "server/tests/test_cost_rollups.py",
            [
                "test_unit_mismatch_is_visible_gap_in_each_cost_stage",
                "test_conversion_keeps_selected_rate_and_rejects_stale_rate",
            ],
            "Unit and FX counterexample semantics re-created; old app not imported",
        ),
    ]
    records = []
    for path, symbols, treatment in entries:
        content = (ROOT / path).read_bytes()
        source = content.decode()
        lines = source.splitlines(keepends=True)
        nodes = {
            node.name: node
            for node in ast.parse(source).body
            if isinstance(node, (ast.FunctionDef, ast.ClassDef))
        }
        functions = []
        for name in symbols:
            node = nodes[name]
            fragment = "".join(lines[node.lineno - 1 : node.end_lineno]).encode()
            functions.append(
                {
                    "name": name,
                    "start": node.lineno,
                    "end": node.end_lineno,
                    "sha256": sha(fragment),
                }
            )
        records.append(
            {
                "path": path,
                "file_sha256": sha(content),
                "symbols": functions,
                "treatment": treatment,
            }
        )
    write(
        "source-summary.json",
        {
            "kind": "reference/algorithm adaptation, not byte copy",
            "records": records,
            "legacy_imported": False,
            "legacy_approvals_qualifications_instances_inherited": False,
        },
    )


def examples():
    basis = dict(
        build=dict(build_id="build", ref=ref("build"), quantity="5", product_unit="ea"),
        bom=dict(
            ref=ref("bom"), engineering_configuration=ref("configuration"), items=[bom_item()]
        ),
    )
    coverage = dict(
        as_of="2026-01-02T00:00:00Z",
        basis=basis,
        supply_snapshot=ref("availability"),
        supply_scope_complete=True,
        pools=[pool()],
    )
    variants = [("unreserved_stock_candidate", deepcopy(coverage))]
    promise = deepcopy(coverage)
    promise["pools"][0]["stage"] = "commitment"
    variants.append(("promise_not_arrival", promise))
    secured = deepcopy(coverage)
    secured["reservations"] = [
        dict(
            reservation_id="reservation",
            ref=ref("reservation"),
            pool=pool()["key"],
            build_id="build",
            bom_item_id="a",
            quantity="10",
            unit="ea",
        )
    ]
    variants.append(("secured_actual_stock", secured))
    unknown = deepcopy(coverage)
    unknown["pools"][0]["quality"] = "unknown"
    variants.append(("unknown_quality", unknown))
    costs = dict(
        as_of="2026-01-02T00:00:00Z",
        basis=basis,
        scope=dict(
            currency="USD",
            tax_basis="exclusive",
            freight_basis="included",
            coverage="materials_only",
            rate_purpose="budget",
            max_rate_age_days=7,
            nre_policy="excluded",
            assumptions=["Synthetic materials-only estimate"],
        ),
        material_prices=[dict(bom_item_id="a", price_id="price")],
        prices=[price()],
    )
    calculated = {
        name: calculate_coverage(CoverageRequest.model_validate(payload)).model_dump(mode="json")
        for name, payload in variants
    }
    calculated["complete_materials_estimate"] = calculate_cost(
        CostRequest.model_validate(costs)
    ).model_dump(mode="json")
    missing_fx = deepcopy(costs)
    missing_fx["prices"][0]["currency"] = "EUR"
    calculated["missing_fx_no_total"] = calculate_cost(
        CostRequest.model_validate(missing_fx)
    ).model_dump(mode="json")
    write(
        "synthetic-examples.json",
        {"synthetic_only": True, "source_hashes_are_fixture_markers": True, "examples": calculated},
    )
    write(
        "input-schemas.json",
        {
            "CoverageRequest": CoverageRequest.model_json_schema(),
            "CostRequest": CostRequest.model_json_schema(),
        },
    )
    write(
        "output-schemas.json",
        {
            "CoverageResult": CoverageResult.model_json_schema(mode="serialization"),
            "CostResult": CostResult.model_json_schema(mode="serialization"),
        },
    )


if __name__ == "__main__":
    candidate()
    source_summary()
    examples()
    print("Generated candidate, import/source summaries, DTO v1 schemas and 6 synthetic examples")
