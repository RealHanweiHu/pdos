"""Human-reviewed change work packages apply to immutable scope versions.
Revision ID: 0193_change_work_package_application
Revises: 0192_change_work_package_runs
"""

import sqlalchemy as sa
from alembic import op

revision = "0193_change_work_package_application"
down_revision = "0192_change_work_package_runs"
branch_labels = None
depends_on = None

LIFECYCLE = """
(status <> 'applied' AND applied_by_user_id IS NULL AND applied_at IS NULL
AND applied_entity_type IS NULL AND applied_entity_id IS NULL) OR
(status = 'applied' AND applied_by_user_id IS NOT NULL AND applied_at IS NOT NULL
AND applied_entity_type IN ('risk', 'memory', 'issue', 'task', 'test_run',
'sample_build_configuration', 'knowledge_candidate', 'schedule_change_proposal',
'material_exception', 'test_plan', 'meeting_minutes', 'decision', 'ecr'{extra})
AND applied_entity_id IS NOT NULL AND reviewed_at < applied_at)
"""
GUARD = """
CREATE FUNCTION cehub_ai.guard_change_work_package_application() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
IF NEW.finding_type <> 'change_work_package' THEN RETURN NEW; END IF;
IF NEW.accepted_payload IS NOT NULL AND
(NEW.accepted_payload->'review_context' IS DISTINCT FROM NEW.proposed_payload->'review_context'
OR NEW.accepted_payload->'details_confirmed' IS DISTINCT FROM 'true'::jsonb
OR jsonb_typeof(NEW.accepted_payload->'review') IS DISTINCT FROM 'object')
THEN RAISE EXCEPTION 'Change work package requires human choices and original context'
USING ERRCODE='23514'; END IF;
IF TG_OP='UPDATE' AND OLD.accepted_payload IS NOT NULL AND
NEW.accepted_payload IS DISTINCT FROM OLD.accepted_payload
THEN RAISE EXCEPTION 'Accepted change work package is immutable' USING ERRCODE='23514'; END IF;
IF NEW.status='applied' AND
(NEW.applied_entity_type IS DISTINCT FROM 'change_impact_scope' OR NOT EXISTS(
SELECT 1 FROM cehub_product.change_impact_scope_versions s
WHERE s.tenant_id=NEW.tenant_id AND s.project_id=NEW.project_id AND s.id=NEW.applied_entity_id
AND s.ecr_id::text=NEW.accepted_payload->>'ecr_id'
AND s.created_by_user_id=NEW.applied_by_user_id
AND s.snapshot->'finding_origin'->>'finding_id'=NEW.id::text
AND s.snapshot->'finding_origin'->>'run_id'=NEW.run_id::text
AND s.snapshot->'finding_origin'->>'source_digest'=NEW.accepted_payload->>'source_digest'
AND s.snapshot->'finding_origin'->'review'=NEW.accepted_payload->'review'
AND s.snapshot->'finding_origin'->>'reviewed_by_user_id'=NEW.reviewed_by_user_id::text
)) THEN RAISE EXCEPTION 'Applied change work package must reference its actual scope receipt'
USING ERRCODE='23514'; END IF;
RETURN NEW;
END $$
"""


def lifecycle(extra: str) -> None:
    op.drop_constraint(
        op.f("ck_findings_apply_lifecycle_consistent"), "findings", schema="cehub_ai"
    )
    op.create_check_constraint(
        op.f("ck_findings_apply_lifecycle_consistent"),
        "findings",
        LIFECYCLE.format(extra=extra),
        schema="cehub_ai",
    )


def upgrade() -> None:
    # This is the first revision longer than Alembic's default 32 characters.
    # Keep the wider administrative column on downgrade: Alembic updates its
    # current revision only after the downgrade function returns.
    op.alter_column(
        "alembic_version", "version_num", existing_type=sa.String(32), type_=sa.String(64)
    )
    lifecycle(", 'change_impact_scope'")
    op.execute(sa.text(GUARD))
    op.execute("""CREATE TRIGGER guard_change_work_package_application
    BEFORE INSERT OR UPDATE ON cehub_ai.findings FOR EACH ROW
    EXECUTE FUNCTION cehub_ai.guard_change_work_package_application()""")


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text("""SELECT EXISTS(SELECT 1 FROM cehub_ai.findings
    WHERE finding_type='change_work_package' AND accepted_payload IS NOT NULL)""")
        )
        .scalar()
    ):
        raise RuntimeError("Refusing to discard human change work-package applications")
    op.execute("DROP TRIGGER guard_change_work_package_application ON cehub_ai.findings")
    op.execute("DROP FUNCTION cehub_ai.guard_change_work_package_application()")
    lifecycle("")
