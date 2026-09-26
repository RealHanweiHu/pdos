"""Export N0-01 review artifacts without connecting to a database or network.

Run from server: .venv/bin/python -m scripts.export_common_contracts [--check]
The OpenAPI document has components only: no unimplemented endpoint is advertised.
"""

from __future__ import annotations

import argparse
import inspect
import json
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from typing import Any

from alembic.script import ScriptDirectory
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint

from app.ai.runtime_contract import NO_ROUTE_EVENT_TYPES, agents_for_event
from app.auth.roles import Role, allowed_actions
from app.contracts import (
    common_objects,
    object_operations,
    planning_records,
    product_records,
    runtime_records,
    time_operations,
    version_lifecycle,
)
from app.contracts.common_objects import Contract
from app.db.namespaces import SCHEMAS
from app.db.schema import metadata
from app.events.catalog import EVENT_REGISTRY

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "docs/contracts/pdos-v1"


def candidate_models() -> dict[str, type[Contract]]:
    return {
        name: value
        for module in (
            common_objects,
            runtime_records,
            product_records,
            planning_records,
            object_operations,
            time_operations,
            version_lifecycle,
        )
        for name, value in inspect.getmembers(module, inspect.isclass)
        if value.__module__ == module.__name__
        and issubclass(value, Contract)
        and value is not Contract
    }


def candidate_openapi() -> dict[str, Any]:
    schemas: dict[str, Any] = {}
    for name, model in sorted(candidate_models().items()):
        schema = model.model_json_schema(ref_template="#/components/schemas/{model}")
        schemas.update(schema.pop("$defs", {}))
        schemas[name] = schema
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "PDOS N0-01 common contracts",
            "version": "1.0.0",
            "description": (
                "Frozen common contracts; not deployed API or executable authorization policy."
            ),
        },
        "paths": {},
        "components": {"schemas": schemas},
        "x-work-item": "N0-01",
        "x-status": "frozen-not-runtime-wired",
        "x-runtime-validation": "Pydantic cross-field validators supplement JSON Schema",
    }


def implementation_inventory() -> dict[str, Any]:
    scripts = ScriptDirectory(str(ROOT / "server/migrations"))
    table_records = []
    for table in sorted(metadata.tables.values(), key=lambda table: table.fullname):
        table_records.append(
            {
                "table": table.fullname,
                "columns": [
                    {
                        "name": column.name,
                        "type": str(column.type),
                        "nullable": column.nullable,
                        "primary_key": column.primary_key,
                    }
                    for column in table.columns
                ],
                "checks": sorted(
                    str(c.sqltext) for c in table.constraints if isinstance(c, CheckConstraint)
                ),
                "unique": sorted(
                    sorted(c.columns.keys())
                    for c in table.constraints
                    if isinstance(c, UniqueConstraint)
                ),
                "foreign_keys": sorted(
                    [
                        {
                            "local": [e.parent.name for e in c.elements],
                            "target": [e.target_fullname for e in c.elements],
                            "ondelete": c.ondelete,
                        }
                        for c in table.constraints
                        if isinstance(c, ForeignKeyConstraint)
                    ],
                    key=str,
                ),
            }
        )
    # Importing app builds its route declarations; no request/lifespan is run.
    from app.main import app

    current_api = app.openapi()
    operations = [
        {"path": path, "method": method.upper(), "operation_id": operation.get("operationId")}
        for path, item in sorted(current_api["paths"].items())
        for method, operation in sorted(item.items())
        if method in {"get", "post", "patch", "put", "delete", "head", "options"}
    ]
    events = []
    for key, definition in sorted(EVENT_REGISTRY.items()):
        events.append(
            {
                **asdict(definition),
                "agent_routes": [agent.value for agent in agents_for_event(key)],
                "explicit_no_route": key in NO_ROUTE_EVENT_TYPES,
            }
        )
    return {
        "evidence_level": "static-working-tree-not-database-or-production",
        "namespaces": list(SCHEMAS),
        "migration_heads": scripts.get_heads(),
        "migration_chain": [
            {"revision": revision.revision, "down_revision": revision.down_revision}
            for revision in scripts.walk_revisions()
        ],
        "tables": table_records,
        "events": events,
        "authorization": {
            role.value: sorted(action.value for action in allowed_actions(role)) for role in Role
        },
        "api_operations": operations,
    }


def render(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def artifacts() -> dict[str, str]:
    result = {
        "common-objects.openapi.json": render(candidate_openapi()),
        "implementation-inventory.json": render(implementation_inventory()),
        "logical-operations.json": render(
            {
                "status": "candidate-not-registered",
                "operations": [
                    asdict(operation)
                    for operation in object_operations.OPERATIONS + time_operations.TIME_OPERATIONS
                ],
                "lifecycles": dict(object_operations.LIFECYCLES),
                "queries": [asdict(query) for query in time_operations.QUERY_CONTRACTS],
                "error_http_status": {
                    "scope_denied": 403,
                    "object_not_found": 404,
                    "version_conflict": 409,
                    "idempotency_conflict": 409,
                    "source_stale": 409,
                    "approval_required": 409,
                    "dependency_unmet": 409,
                    "input_invalid": 422,
                    "dependency_unavailable": 503,
                },
                "existence_hiding": (
                    "Return object_not_found instead of scope_denied "
                    "when current ACL policy hides existence"
                ),
                "model_dispatch": (
                    "No runtime registration; capability routes and bounded triggers "
                    "belong to N0-02/03"
                ),
            }
        ),
    }
    source_files = [
        "docs/contracts/pdos-v1/README.md",
        "docs/contracts/pdos-v1/object-ownership.json",
        "docs/contracts/pdos-v1/physical-contract-map.md",
        "docs/contracts/pdos-v1/n0-freeze-proposal.md",
        "docs/contracts/pdos-v1/freeze-record.md",
        "docs/contracts/pdos-v1/approved-draft.3/manifest.json",
        "docs/reports/2026-09-10-n0-01-freeze-candidate-validation.md",
        "docs/reports/2026-09-10-n0-01-product-planning-contract-validation.md",
        "docs/reports/2026-09-10-n0-01-contract-foundation-validation.md",
        "docs/design/2026-09-10-pdos-complete-design-contract.md",
        "docs/design/2026-08-25-vnext-object-contract-v1.md",
        "server/app/contracts/__init__.py",
        "server/app/contracts/common_objects.py",
        "server/app/contracts/runtime_records.py",
        "server/app/contracts/product_records.py",
        "server/app/contracts/planning_records.py",
        "server/app/contracts/object_operations.py",
        "server/app/contracts/time_operations.py",
        "server/app/contracts/version_lifecycle.py",
        "server/tests/test_common_object_contracts.py",
        "server/tests/test_product_planning_contracts.py",
        "server/tests/test_version_time_contracts.py",
        "server/scripts/export_common_contracts.py",
        "server/app/main.py",
        "server/app/db/schema.py",
        "server/app/db/namespaces.py",
        "server/app/auth/roles.py",
        "server/app/auth/project_access.py",
        "server/app/ai/runtime_contract.py",
        "server/app/events/catalog.py",
        "server/app/events/writer.py",
    ]
    # Bind every API/domain/migration source used by the static inventory.
    for folder in ("server/app/api", "server/app/domain", "server/migrations/versions"):
        source_files.extend(str(path.relative_to(ROOT)) for path in (ROOT / folder).glob("*.py"))
    result["manifest.json"] = render(
        {
            "contract_version": "1.0.0",
            "status": "frozen-not-runtime-wired",
            "sources": {
                path: sha256((ROOT / path).read_bytes()).hexdigest()
                for path in sorted(set(source_files))
            },
            "artifacts": {name: sha256(body.encode()).hexdigest() for name, body in result.items()},
        }
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="Fail on artifact drift; write nothing"
    )
    args = parser.parse_args()
    generated = artifacts()
    differences = []
    for name, content in generated.items():
        path = OUTPUT / name
        if args.check:
            if not path.exists() or path.read_text() != content:
                differences.append(name)
        else:
            OUTPUT.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
    if differences:
        raise SystemExit("contract artifact drift: " + ", ".join(differences))
    print(f"{'Checked' if args.check else 'Exported'} {len(generated)} N0-01 artifacts")


if __name__ == "__main__":
    main()
