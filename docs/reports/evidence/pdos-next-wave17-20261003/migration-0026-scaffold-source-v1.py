"""Uninstalled next_0026: static CAPA publication atoms, exact head25 parent.

Only Alembic's caller executes upgrade/downgrade. No runtime reads of mutable
models, staging generators, evidence files, credentials or application profiles.
Pending Root final plan binding; the scaffold refuses execution before any IO.
"""

import hashlib
import json

from alembic import op
from sqlalchemy import text

revision = "next_0026"
down_revision = "next_0025"
branch_labels = None
depends_on = None

TABLES = (
    "capa_verification_rule_facts",
    "capa_observation_facts",
    "capa_named_verification_reviews",
    "capa_current_verification_rules",
    "capa_current_observations",
)
# Explicit reverse FK order: Current/review -> observation -> rule. No CASCADE.
DROP_TABLES = (
    "capa_current_observations",
    "capa_current_verification_rules",
    "capa_named_verification_reviews",
    "capa_observation_facts",
    "capa_verification_rule_facts",
)
PARENT_UNIQUE = "uq_confirmations_tenant_id_id_capa"
EXPECTED_OLD_DEFINITION_SHA256 = (
    (
        "assert_quality_followup_proof(uuid,uuid,uuid,text,jsonb,timestamptz)",
        "3804a6762816a5a4bbb92c4055637f682dddc6fb9c42cb7489d8ca44ae047fe0",
    ),
    (
        "protect_quality_followup_confirmation()",
        "50041550ae20c84c36b09df868373ca4b100e7a02af6fbd892448b3a8aca89bb",
    ),
    (
        "require_quality_followup_consumption_atom()",
        "958a891cdf688705c27b501d81df876aa392d5f473a79c30d0821a6513f09ee6",
    ),
    (
        "assert_quality_change_receipt(uuid,uuid,uuid,integer,text,text,uuid,text)",
        "664ed1b5bc62c9558dfe2b1b6d60e92ae91a399a7c1922fef174e9521caa0685",
    ),
    (
        "assert_quality_followup_receipt(uuid,uuid,uuid,integer,text,text,uuid,text,text)",
        "7dcf70ba1b333572e7d4afc08c0eae123310ba6e4f639c81d116178f1218aa3b",
    ),
    (
        "require_quality_followup_atom()",
        "af47a61163221c81b2c7f40745cc08163cdd70a4d26cced24d1c17f03bc9cb2c",
    ),
)

# BEGIN STATIC ROOT PLAN -- filled only after Root freezes the final v3 plan.
FINAL_PLAN_BOUND = False
PLAN_SOURCE_SHA256 = ""
MODEL_SOURCE_SHA256 = ""
EMBEDDED_SQL_SHA256 = ""
PARENT_UNIQUE_AND_TABLES = ()
MODEL_INDEXES = ()
UPGRADE_PREFLIGHT = ()
REPLACE_FUNCTIONS = ()
NEW_FUNCTIONS = ()
NEW_TRIGGERS = ()
PERMISSIONS = ()
DOWNGRADE_PREFLIGHT = ()
DOWNGRADE_GUARDS = ()
RESTORE_ACTUAL_HEAD25_FUNCTIONS = ()
# END STATIC ROOT PLAN


def _sql_material():
    return {
        "parent_unique_and_tables": PARENT_UNIQUE_AND_TABLES,
        "model_indexes_after_tables": MODEL_INDEXES,
        "guard_preflight_after_tables": UPGRADE_PREFLIGHT,
        "replace_functions": REPLACE_FUNCTIONS,
        "new_functions": NEW_FUNCTIONS,
        "new_triggers": NEW_TRIGGERS,
        "permissions": PERMISSIONS,
        "rollback_preflight_before_any_changes": DOWNGRADE_PREFLIGHT,
        "rollback_guards": DOWNGRADE_GUARDS,
        "restore_actual_old_functions": RESTORE_ACTUAL_HEAD25_FUNCTIONS,
    }


def _require_bound_plan():
    if FINAL_PLAN_BOUND is not True:
        raise RuntimeError("Final Root SQL plan is not bound; uninstalled scaffold cannot execute")
    groups = _sql_material()
    counts = (6, 5, 3, 4, 6, 15, 41, 2, 23, 4)
    if tuple(len(group) for group in groups.values()) != counts:
        raise RuntimeError("Embedded final SQL statement groups differ from the reviewed plan")
    if any(
        not isinstance(statement, str) or not statement.strip()
        for group in groups.values()
        for statement in group
    ):
        raise RuntimeError("Every migration statement must be a static complete SQL literal")
    value = json.dumps(groups, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if hashlib.sha256(value.encode()).hexdigest() != EMBEDDED_SQL_SHA256:
        raise RuntimeError("Embedded SQL differs from the exact frozen final plan")
    if not all(
        len(value) == 64 and set(value) <= set("0123456789abcdef")
        for value in (PLAN_SOURCE_SHA256, MODEL_SOURCE_SHA256, EMBEDDED_SQL_SHA256)
    ):
        raise RuntimeError("Final plan and model provenance are not exactly bound")


def _connection(expected_head):
    bind = op.get_bind()
    if bind.dialect.name != "postgresql" or bind.in_transaction() is not True:
        raise RuntimeError("Migration requires the caller's active PostgreSQL transaction")
    if bind.scalar(text("SELECT current_schema()")) != "public":
        raise RuntimeError("Static migration objects require the exact public schema")
    heads = tuple(
        bind.execute(text("SELECT version_num FROM public.alembic_version FOR UPDATE")).scalars()
    )
    if heads != (expected_head,):
        raise RuntimeError(
            "Actual single Alembic head differs from the allocated migration boundary"
        )
    return bind


def _assert_actual_head25_functions(bind):
    for signature, expected in EXPECTED_OLD_DEFINITION_SHA256:
        definition = bind.scalar(
            text("SELECT pg_get_functiondef(to_regprocedure(:signature))"),
            {"signature": "public." + signature},
        )
        if (
            not isinstance(definition, str)
            or hashlib.sha256(definition.encode()).hexdigest() != expected
        ):
            raise RuntimeError(
                "Installed SQL guard differs from the exact reviewed head25 definition"
            )


def _run(bind, statements):
    for statement in statements:
        # SQLAlchemy text compilation handles literal %ROWTYPE for the actual
        # PostgreSQL driver; no client format interpolation or arbitrary SQL.
        bind.execute(text(statement))


def upgrade():
    _require_bound_plan()  # Never query or perform partial DDL from a scaffold.
    bind = _connection(down_revision)
    _assert_actual_head25_functions(bind)
    for table in TABLES:
        if bind.scalar(text("SELECT to_regclass(:name)"), {"name": "public." + table}) is not None:
            raise RuntimeError(
                "New CAPA tables must be created, never adopted from an existing catalog"
            )
    # Empty new targets/proofs/Receipts before creating anything. Old rootcause,
    # complete and Link facts are retained; no head24 legacy-empty precheck.
    _run(bind, UPGRADE_PREFLIGHT[:2])
    _run(bind, PARENT_UNIQUE_AND_TABLES)
    _run(bind, MODEL_INDEXES)
    _run(bind, UPGRADE_PREFLIGHT[2:])
    _run(bind, REPLACE_FUNCTIONS)
    _run(bind, NEW_FUNCTIONS)
    _run(bind, NEW_TRIGGERS)
    _run(bind, PERMISSIONS)


def downgrade():
    _require_bound_plan()
    bind = _connection(revision)
    # Keep all old/new related group tables fenced throughout the downgrade.
    # Root's new-target empty check is additional; old retained business facts
    # may remain and are never deleted or rewritten by this migration.
    _run(
        bind,
        (
            "LOCK TABLE quality_issue_versions,quality_current_issues,capa_remediation_links,"
            "confirmations,action_receipts,audit_entries,outbox_events,request_keys,"
            "capa_verification_evidence," + ",".join(TABLES) + " IN SHARE ROW EXCLUSIVE MODE",
        ),
    )
    _run(bind, DOWNGRADE_PREFLIGHT)
    _run(bind, DOWNGRADE_GUARDS)
    _run(bind, RESTORE_ACTUAL_HEAD25_FUNCTIONS)
    _assert_actual_head25_functions(bind)  # Six, including the two untouched functions.
    for table in DROP_TABLES:
        _run(bind, (f'DROP TABLE "{table}"',))
    _run(bind, (f'ALTER TABLE confirmations DROP CONSTRAINT "{PARENT_UNIQUE}"',))
