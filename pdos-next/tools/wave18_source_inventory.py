"""Read-only inventory on the verified retained synthetic environment.

No credentials, source bodies, business writes, HTTP calls or model calls leave
this tool. Future Rule/Observation/Review sources are never invented here.
"""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import select, text

from pdos_next.database import engine_for
from pdos_next.models import Artifact, Base
from pdos_next.domain.capa_verification.models import CapaVerificationEvidence
from pdos_next.domain.professional_authority.models import ProfessionalFact
from wave17_migrate import target

REPORT = Path(__file__).resolve().parents[2] / "docs/reports/evidence/pdos-next-wave18-20261003"
PRODUCT = UUID("b1e23421-6c70-4fc5-a87f-96744baab2e8")
ISSUE = UUID("16ff0607-08f8-5e3c-9b74-b48999791b00")


def main():
    result = {
        "status": "RUNNING",
        "scope": "existing retained synthetic candidate source inventory",
        "target": "127.0.0.1:62513/pdos_test",
        "business_writes": 0,
        "model_calls": 0,
        "tool_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    state = target()
    engine = engine_for(state["admin_url"])
    try:
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c:
            with c.begin():
                c.execute(text("SET TRANSACTION READ ONLY"))
                c.execute(text("SET LOCAL statement_timeout = '30s'"))
                assert c.scalar(text("SELECT version_num FROM alembic_version")) == "next_0026"
                candidates = (
                    c.execute(
                        select(CapaVerificationEvidence.__table__).where(
                            CapaVerificationEvidence.product_id == PRODUCT,
                            CapaVerificationEvidence.issue_id == ISSUE,
                        )
                    )
                    .mappings()
                    .all()
                )
                assert len(candidates) == 2
                wanted, roles = {}, {}

                def add(reads, role):
                    for read in reads:
                        key, rev = read["artifact_id"], read["expected_revision"]
                        assert key not in wanted or wanted[key] == rev
                        wanted[key] = rev
                        roles.setdefault(key, set()).add(role)

                result["candidates"] = []
                for row in candidates:
                    add(row["required_source_read_set"], "fixed_candidate")
                    result["candidates"].append(
                        {
                            "id": str(row["id"]),
                            "revision": row["revision"],
                            "owner_id": str(row["owner_id"]),
                            "visibility": row["visibility"],
                            "read_count": len(row["required_source_read_set"]),
                            "anchor_sha256": row["input_snapshot"]["stable_anchor"][
                                "anchor_sha256"
                            ],
                        }
                    )
                professional = (
                    c.execute(
                        select(ProfessionalFact.__table__).where(
                            ProfessionalFact.product_id == PRODUCT,
                            ProfessionalFact.project_id == candidates[0]["project_id"],
                        )
                    )
                    .mappings()
                    .all()
                )
                result["professional_scope"] = []
                for row in professional:
                    add(
                        row["required_source_read_set"],
                        "professional_scope_including_negative_and_historical",
                    )
                    result["professional_scope"].append(
                        {
                            "id": str(row["id"]),
                            "revision": row["revision"],
                            "subject_id": str(row["subject_id"]),
                            "kind": row["kind"],
                            "state": row["state"],
                            "issuer_epoch": None,
                            "operations": row["operations"],
                            "purposes": row["purposes"],
                            "valid_from": row["valid_from"].isoformat(),
                            "valid_until": row["valid_until"].isoformat(),
                        }
                    )
                result["sources"] = []
                for identity, revision in sorted(wanted.items()):
                    row = (
                        c.execute(
                            select(Artifact.__table__).where(
                                Artifact.id == UUID(identity), Artifact.product_id == PRODUCT
                            )
                        )
                        .mappings()
                        .one()
                    )
                    assert row["revision"] == revision
                    assert (
                        hashlib.sha256(row["content"].encode()).hexdigest() == row["content_hash"]
                    )
                    result["sources"].append(
                        {
                            "id": identity,
                            "revision": revision,
                            "roles": sorted(roles[identity]),
                            "owner_id": str(row["owner_id"]),
                            "visibility": row["visibility"],
                            "status": row["status"],
                            "hash": row["content_hash"],
                            "line_count": len(row["content"].splitlines()),
                            "original_id": str(row["original_id"]) if row["original_id"] else None,
                        }
                    )
                tables = (
                    "capa_verification_rule_facts",
                    "capa_observation_facts",
                    "capa_named_verification_reviews",
                    "capa_current_verification_rules",
                    "capa_current_observations",
                )
                result["fact_rows"] = {
                    name: c.scalar(select(text("count(*)")).select_from(Base.metadata.tables[name]))
                    for name in tables
                }
                result.update(
                    status="PASS_READ_ONLY_INVENTORY",
                    union_count=len(wanted),
                    command_limit=20,
                    scope_union_exceeds_command_limit=len(wanted) > 20,
                    qualified_for_new_operations=False,
                    independent_reviewer=False,
                    future_fact_source_slots_reserved=0,
                    observed_at=datetime.now(UTC).isoformat(),
                )
    finally:
        engine.dispose()
    REPORT.mkdir(parents=True, exist_ok=True)
    with (REPORT / "existing-source-inventory-v1.json").open("x") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(
        json.dumps(
            {
                "status": result["status"],
                "union_count": result["union_count"],
                "fact_rows": result["fact_rows"],
            }
        )
    )


if __name__ == "__main__":
    main()
