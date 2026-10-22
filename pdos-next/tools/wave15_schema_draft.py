"""Offline schema review draft. Does not open a database or add an Alembic head."""

import hashlib
import json

from local_environment import ROOT
from pdos_next.domain.change_execution import models as change
from pdos_next.domain.quality_execution import models as quality
from pdos_next.models import Base
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

TABLES = {
    model.__tablename__
    for model in (
        quality.QualityIssueVersion,
        quality.QualityIssueCurrent,
        quality.QualityFailureMap,
        quality.QualityEventFailureLink,
        quality.QualityPolicyFact,
        quality.QualityPolicyCurrent,
        change.ChangeRequestVersion,
        change.ChangeCurrent,
        change.ChangeGraphCapture,
    )
}

dialect = postgresql.dialect()
statements = []
columns = {}
for table in Base.metadata.sorted_tables:
    if table.name not in TABLES:
        continue
    statements.append(str(CreateTable(table).compile(dialect=dialect)))
    statements.extend(
        str(CreateIndex(index).compile(dialect=dialect))
        for index in sorted(table.indexes, key=lambda index: index.name)
    )
    columns[table.name] = list(table.columns.keys())
assert set(columns) == TABLES and len(TABLES) == 9
sources = {
    str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
    for path in (
        ROOT / "server/pdos_next/domain/quality_execution/models.py",
        ROOT / "server/pdos_next/domain/change_execution/models.py",
    )
}
report = ROOT.parent / "docs/reports/evidence/pdos-next-wave15-20261002/schema-offline-draft.json"
with report.open("x") as output:
    output.write(
        json.dumps(
            {
                "status": "offline_only_not_applied",
                "tables": sorted(TABLES),
                "columns": columns,
                "statements": statements,
                "model_sources": sources,
                "parent_unique_columns": [
                    "tenant_id",
                    "product_id",
                    "project_id",
                    "request_id",
                    "run_id",
                    "id",
                    "revision",
                ],
                "parent_unique_tables": [
                    "verification_run_versions",
                    "test_measurements",
                    "test_result_projections",
                ],
                "remaining": (
                    "Root must add RLS/zero Agent writes, immutable and pointer/alias guards, "
                    "atomic receipt constraints, lifecycle protection and only then allocate "
                    "next_0023 after Wave14 checks finish."
                ),
            },
            indent=2,
        )
        + "\n"
    )
print("Nine-table offline schema draft saved; no database operation or Alembic head added.")
