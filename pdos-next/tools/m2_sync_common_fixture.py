"""Copy only root-approved common fixture changes into the verified M2 database."""

import hashlib
import json

import local_environment as local
from m2_verify import REPORT
from migrations.schema_s0_0404 import GRANT_FUNCTIONS
from migrations.schema_s0_0406 import UPGRADE_SQL
from migrations.schema_s0_0407 import UPGRADE_SQL as CATEGORY_SOURCE_SQL
from migrations.schema_s0_0408 import SQL as REVERT_CLOSURE_SQL
from migrations.schema_s0_0409 import SQL as ORIGINAL_SECURITY_SQL
from pdos_next.database import engine_for
from sqlalchemy import text


def main():
    local.STATE = local.ROOT / ".local/m2-runtime.json"
    state = local.verified(local.read_state())
    engine = engine_for(state["admin_url"])
    statements = [
        "ALTER TABLE grants ALTER COLUMN expires_at DROP NOT NULL",
        "ALTER TABLE grants ADD COLUMN IF NOT EXISTS "
        "product_manager BOOLEAN NOT NULL DEFAULT false",
        next(new for name, _old, new in GRANT_FUNCTIONS if name == "category_access"),
        "ALTER TABLE action_receipts ADD COLUMN IF NOT EXISTS agent_run_id UUID",
        """DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint
          WHERE conrelid='action_receipts'::regclass AND conname='receipt_one_run_identity') THEN
          ALTER TABLE action_receipts ADD CONSTRAINT receipt_one_run_identity
          CHECK (run_id IS NULL OR agent_run_id IS NULL); END IF; END $$""",
        "ALTER TABLE confirmations ADD COLUMN IF NOT EXISTS "
        "subject_type varchar(32) DEFAULT 'product'",
    ]
    upgrade_digest = hashlib.sha256(json.dumps(UPGRADE_SQL).encode()).hexdigest()
    report_path = REPORT / "common-fixture-sync.json"
    prior = json.loads(report_path.read_text()) if report_path.exists() else {}
    copied = (
        prior.get("marker") == state["marker"]
        and prior.get("schema_0406_copy_digest") == upgrade_digest
    )
    category_digest = hashlib.sha256(json.dumps(CATEGORY_SOURCE_SQL).encode()).hexdigest()
    category_copied = (
        prior.get("marker") == state["marker"]
        and prior.get("schema_0407_copy_digest") == category_digest
    )
    closure_digest = hashlib.sha256(REVERT_CLOSURE_SQL.encode()).hexdigest()
    closure_copied = (
        prior.get("marker") == state["marker"]
        and prior.get("schema_0408_function_sha256") == closure_digest
    )
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
        if not copied:
            for statement in UPGRADE_SQL:
                connection.execute(text(statement))
        if not category_copied:
            for statement in CATEGORY_SOURCE_SQL:
                connection.execute(text(statement))
        if not closure_copied:
            connection.execute(text(REVERT_CLOSURE_SQL))
        connection.execute(text(
            "REVOKE ALL ON FUNCTION revert_subjects_consumed(uuid,uuid,jsonb,uuid[]) FROM PUBLIC"
        ))
        connection.execute(text(
            "GRANT EXECUTE ON FUNCTION revert_subjects_consumed(uuid,uuid,jsonb,uuid[]) "
            "TO pdos_next_app"
        ))
        connection.execute(text(ORIGINAL_SECURITY_SQL))
    engine.dispose()
    REPORT.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(
            {
                "source": "root-approved common 0404/0405 minimal + "
                "0406/0407/0408/0409 fixture copy",
                "marker": state["marker"],
                "database": "pdos_test",
                "statements_sha256": [hashlib.sha256(s.encode()).hexdigest() for s in statements],
                "schema_0406_copy_digest": upgrade_digest,
                "schema_0406_statement_count": len(UPGRADE_SQL),
                "schema_0406_statements_sha256": [
                    hashlib.sha256(s.encode()).hexdigest() for s in UPGRADE_SQL
                ],
                "schema_0407_copy_digest": category_digest,
                "schema_0407_statement_count": len(CATEGORY_SOURCE_SQL),
                "schema_0407_statements_sha256": [
                    hashlib.sha256(s.encode()).hexdigest() for s in CATEGORY_SOURCE_SQL
                ],
                "schema_0408_function_sha256": closure_digest,
                "schema_0409_function_sha256": hashlib.sha256(
                    ORIGINAL_SECURITY_SQL.encode()
                ).hexdigest(),
                "public_migration_branch_applied": False,
            },
            indent=2,
        ) + "\n"
    )
    print("Root-approved common source fixture synchronized; M2 marker verified.")


if __name__ == "__main__":
    main()
