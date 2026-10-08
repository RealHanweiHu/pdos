"""Freeze the reviewed schema only after Wave14 is complete on actual head 22."""
# ruff: noqa: E501

import hashlib
import json
from pprint import pformat

from local_environment import ROOT, SERVER, read_state, verified
from pdos_next.database import engine_for
from sqlalchemy import text
from wave15_schema_guards import ATOMIC, FUNCTIONS, IMMUTABLE, POINTERS

REPORT = ROOT.parent / "docs/reports/evidence/pdos-next-wave15-20261002"
final = json.loads(
    (
        ROOT.parent / "docs/reports/evidence/pdos-next-wave14-20261002/final-check-selection.json"
    ).read_text()
)
assert final["status"] == "completed" and final["deduplicated_passed"] == 429
assert not final["unreplaced_failed"] and not final["changed_covered_files"]
state = verified(read_state())
with engine_for(state["admin_url"]).connect() as connection:
    head = connection.scalar(text("SELECT version_num FROM alembic_version"))
assert head == "next_0022", "Allocate only the actual next migration head"
draft = json.loads((REPORT / "schema-offline-draft.json").read_text())
for name, expected in draft["model_sources"].items():
    assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected
tables = tuple(draft["columns"])
schema = (
    '"""Frozen Wave15 DDL and reviewed guards, independent of future model code."""\n'
    "# ruff: noqa: E501\n\n"
    + "\n\n".join(
        f"{name} = {pformat(value, width=100, sort_dicts=False)}"
        for name, value in (
            ("TABLES", tables),
            ("SCHEMA_SQL", tuple(draft["statements"])),
            ("FUNCTIONS", FUNCTIONS),
            ("IMMUTABLE", IMMUTABLE),
            ("POINTERS", POINTERS),
            ("ATOMIC", ATOMIC),
            ("PARENT_TABLES", tuple(draft["parent_unique_tables"])),
            ("PARENT_COLUMNS", tuple(draft["parent_unique_columns"])),
        )
    )
    + "\n"
)
with (SERVER / "migrations/schema_0023.py").open("x") as output:
    output.write(schema)
migration = '''"""Stable failures, quality/CAPA drafts and fixed change impact graphs."""
# ruff: noqa: E501

from alembic import op
from sqlalchemy import text
from migrations.schema_0023 import (
    ATOMIC, FUNCTIONS, IMMUTABLE, PARENT_COLUMNS, PARENT_TABLES, POINTERS, SCHEMA_SQL, TABLES,
)

revision = "next_0023"
down_revision = "next_0022"
branch_labels = None
depends_on = None


def upgrade():
    for table in PARENT_TABLES:
        op.create_unique_constraint(f"uq_{table}_quality_scope", table, list(PARENT_COLUMNS))
    for statement in SCHEMA_SQL:
        op.execute(statement)
    for statement in FUNCTIONS.values():
        op.execute(statement)
    for table in TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(f"CREATE POLICY tenant_scope ON \\\"{table}\\\" USING (tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid) WITH CHECK (tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid)")
        permissions = 'SELECT,INSERT,UPDATE' if table in POINTERS else 'SELECT,INSERT'
        op.execute(f'GRANT {permissions} ON "{table}" TO pdos_next_app')
        op.execute(f'CREATE TRIGGER lifecycle_reference BEFORE INSERT OR UPDATE OR DELETE ON "{table}" FOR EACH ROW EXECUTE FUNCTION lifecycle_reference_gate()')
        if table in IMMUTABLE:
            op.execute(f'CREATE TRIGGER retained_record BEFORE UPDATE OR DELETE ON "{table}" FOR EACH ROW EXECUTE FUNCTION protect_next_snapshot()')
        if table in POINTERS:
            op.execute(f'CREATE TRIGGER exact_current BEFORE INSERT OR UPDATE OR DELETE ON "{table}" FOR EACH ROW EXECUTE FUNCTION {POINTERS[table]}()')
        if table in ATOMIC:
            op.execute(f'CREATE CONSTRAINT TRIGGER quality_change_required AFTER INSERT ON "{table}" DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION require_quality_change_atom()')
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM pdos_agent")


def downgrade():
    if any(op.get_bind().scalar(text(f'SELECT count(*) FROM "{table}"')) for table in TABLES):
        raise RuntimeError("Retained quality/change history prevents destructive downgrade")
    for table in reversed(TABLES):
        op.drop_table(table)
    for name in reversed(FUNCTIONS):
        signature = '(uuid,uuid,uuid,integer,text,text,uuid,text)' if name == 'assert_quality_change_receipt' else '()'
        op.execute(f'DROP FUNCTION {name}{signature}')
    for table in PARENT_TABLES:
        op.drop_constraint(f"uq_{table}_quality_scope", table, type_="unique")
'''
with (SERVER / "migrations/versions/0023_quality_and_change_execution.py").open("x") as output:
    output.write(migration)
print("Frozen next_0023 from actual head22; not yet applied to the database.")
