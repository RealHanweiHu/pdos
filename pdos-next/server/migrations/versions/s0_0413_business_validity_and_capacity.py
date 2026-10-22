# ruff: noqa: E501 -- frozen PostgreSQL definitions preserve their original SQL text
"""Optional declared intervals; remove material TTL and arbitrary capacity caps."""

from alembic import op

revision = "s0_0413"
down_revision = "s0_0412"
branch_labels = None
depends_on = None

TABLES = ("build_authorization_decisions", "build_operational_facts", "test_resource_facts")

OLD_BINDING = "CREATE OR REPLACE FUNCTION public.protect_build_start_binding()\n RETURNS trigger\n LANGUAGE plpgsql\nAS $function$\n      DECLARE assessment build_execution_assessments%ROWTYPE;\n              eng build_authorization_decisions%ROWTYPE; mfg build_authorization_decisions%ROWTYPE;\n      BEGIN\n        SELECT * INTO assessment FROM build_execution_assessments WHERE id=NEW.assessment_id\n          AND tenant_id=NEW.tenant_id AND product_id=NEW.product_id;\n        SELECT * INTO eng FROM build_authorization_decisions WHERE id=NEW.engineering_authorization_id\n          AND tenant_id=NEW.tenant_id AND product_id=NEW.product_id;\n        SELECT * INTO mfg FROM build_authorization_decisions WHERE id=NEW.manufacturing_authorization_id\n          AND tenant_id=NEW.tenant_id AND product_id=NEW.product_id;\n        IF assessment.id IS NULL OR eng.id IS NULL OR mfg.id IS NULL\n          OR NEW.assessment_sha256<>assessment.snapshot_sha256\n          OR NEW.build_revision<>assessment.build_revision\n          OR NEW.execution_scope IS DISTINCT FROM assessment.execution_scope\n          OR eng.assessment_id<>assessment.id OR mfg.assessment_id<>assessment.id\n          OR eng.status<>'approved' OR mfg.status<>'approved'\n          OR NEW.occurred_at>clock_timestamp()\n          OR NEW.occurred_at<eng.created_at OR NEW.occurred_at<mfg.created_at\n          OR NEW.occurred_at<(NEW.execution_scope->>'window_start')::timestamptz\n          OR NEW.occurred_at>=(NEW.execution_scope->>'window_end')::timestamptz\n          OR LEAST(eng.valid_until,mfg.valid_until)<(NEW.execution_scope->>'window_end')::timestamptz\n          OR NOT EXISTS (SELECT 1 FROM build_current_execution_assessments p\n            WHERE p.tenant_id=NEW.tenant_id AND p.build_id=NEW.build_id AND p.assessment_id=assessment.id)\n          OR NOT EXISTS (SELECT 1 FROM build_current_authorizations p\n            WHERE p.tenant_id=NEW.tenant_id AND p.build_id=NEW.build_id AND p.role='engineering' AND p.decision_id=eng.id)\n          OR NOT EXISTS (SELECT 1 FROM build_current_authorizations p\n            WHERE p.tenant_id=NEW.tenant_id AND p.build_id=NEW.build_id AND p.role='manufacturing' AND p.decision_id=mfg.id)\n          THEN RAISE EXCEPTION 'Start requires current matching approvals and actual occurrence'; END IF;\n        RETURN NEW;\n      END $function$\n"
NEW_BINDING = "CREATE OR REPLACE FUNCTION public.protect_build_start_binding()\n RETURNS trigger\n LANGUAGE plpgsql\nAS $function$\n      DECLARE assessment build_execution_assessments%ROWTYPE;\n              eng build_authorization_decisions%ROWTYPE; mfg build_authorization_decisions%ROWTYPE;\n      BEGIN\n        SELECT * INTO assessment FROM build_execution_assessments WHERE id=NEW.assessment_id\n          AND tenant_id=NEW.tenant_id AND product_id=NEW.product_id;\n        SELECT * INTO eng FROM build_authorization_decisions WHERE id=NEW.engineering_authorization_id\n          AND tenant_id=NEW.tenant_id AND product_id=NEW.product_id;\n        SELECT * INTO mfg FROM build_authorization_decisions WHERE id=NEW.manufacturing_authorization_id\n          AND tenant_id=NEW.tenant_id AND product_id=NEW.product_id;\n        IF assessment.id IS NULL OR eng.id IS NULL OR mfg.id IS NULL\n          OR NEW.assessment_sha256<>assessment.snapshot_sha256\n          OR NEW.build_revision<>assessment.build_revision\n          OR NEW.execution_scope IS DISTINCT FROM assessment.execution_scope\n          OR eng.assessment_id<>assessment.id OR mfg.assessment_id<>assessment.id\n          OR eng.status<>'approved' OR mfg.status<>'approved'\n          OR NEW.occurred_at>clock_timestamp()\n          OR NEW.occurred_at<eng.created_at OR NEW.occurred_at<mfg.created_at\n          OR NEW.occurred_at<(NEW.execution_scope->>'window_start')::timestamptz\n          OR NEW.occurred_at>=(NEW.execution_scope->>'window_end')::timestamptz\n          OR (eng.valid_until IS NOT NULL AND eng.valid_until<(NEW.execution_scope->>'window_end')::timestamptz) OR (mfg.valid_until IS NOT NULL AND mfg.valid_until<(NEW.execution_scope->>'window_end')::timestamptz)\n          OR NOT EXISTS (SELECT 1 FROM build_current_execution_assessments p\n            WHERE p.tenant_id=NEW.tenant_id AND p.build_id=NEW.build_id AND p.assessment_id=assessment.id)\n          OR NOT EXISTS (SELECT 1 FROM build_current_authorizations p\n            WHERE p.tenant_id=NEW.tenant_id AND p.build_id=NEW.build_id AND p.role='engineering' AND p.decision_id=eng.id)\n          OR NOT EXISTS (SELECT 1 FROM build_current_authorizations p\n            WHERE p.tenant_id=NEW.tenant_id AND p.build_id=NEW.build_id AND p.role='manufacturing' AND p.decision_id=mfg.id)\n          THEN RAISE EXCEPTION 'Start requires current matching approvals and actual occurrence'; END IF;\n        RETURN NEW;\n      END $function$\n"


def upgrade():
    for table in TABLES:
        op.alter_column(table, "valid_until", nullable=True)
    op.drop_constraint(
        "operational_resource_occupancies_check1", "operational_resource_occupancies", type_="check"
    )
    op.create_check_constraint(
        "operational_resource_occupancies_check1",
        "operational_resource_occupancies",
        "resource_revision>0 AND units>0 AND window_finish>window_start",
    )
    op.drop_constraint("sample_allocations_unit_count_check", "sample_allocations", type_="check")
    op.create_check_constraint(
        "sample_allocations_unit_count_check", "sample_allocations", "unit_count>0"
    )
    op.execute(NEW_BINDING)


def downgrade():
    op.execute(OLD_BINDING)
    op.drop_constraint("sample_allocations_unit_count_check", "sample_allocations", type_="check")
    op.create_check_constraint(
        "sample_allocations_unit_count_check",
        "sample_allocations",
        "unit_count>0 AND unit_count<=500",
    )
    op.drop_constraint(
        "operational_resource_occupancies_check1", "operational_resource_occupancies", type_="check"
    )
    op.create_check_constraint(
        "operational_resource_occupancies_check1",
        "operational_resource_occupancies",
        "resource_revision>0 AND units>0 AND units<=1000 AND window_finish>window_start",
    )
    for table in reversed(TABLES):
        op.alter_column(table, "valid_until", nullable=False)
