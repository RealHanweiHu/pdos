"""Retain audit v1 files and allow readable audit v2 exports."""

# ruff: noqa: E501
from alembic import op

revision = "0376_readable_audit_reports"
down_revision = "0375_readable_engineering_reports"
branch_labels = None
depends_on = None

OLD_SHAPE = "format IN ('docx','xlsx','pptx','pdf') AND btrim(reason)<>'' AND btrim(filename)<>'' AND ((kind='audit' AND template_version='internal-audit-evidence.v1') OR (kind<>'audit' AND template_version='internal-project-reports.v1') OR (kind='weekly' AND template_version='internal-project-weekly.v2') OR (kind='8d' AND template_version='internal-project-8d.v2') OR (kind='dfmea' AND template_version='internal-project-dfmea.v2') OR (kind='gate' AND template_version='internal-project-gate.v2')) AND byte_size BETWEEN 1 AND 12582912 AND octet_length(content)=byte_size AND jsonb_typeof(snapshot)='object' AND snapshot->>'audience'='internal' AND jsonb_typeof(scope)='object' AND scope->>'kind'=kind AND ((kind='8d' AND ncr_id IS NOT NULL AND gate_id IS NULL) OR (kind='gate' AND gate_id IS NOT NULL AND ncr_id IS NULL) OR (kind IN ('dfmea','weekly','audit') AND ncr_id IS NULL AND gate_id IS NULL)) AND content_digest ~ '^[a-f0-9]{64}$' AND source_digest ~ '^[a-f0-9]{64}$' AND preview_digest ~ '^[a-f0-9]{64}$' AND request_digest ~ '^[a-f0-9]{64}$'"
SHAPE = "format IN ('docx','xlsx','pptx','pdf') AND btrim(reason)<>'' AND btrim(filename)<>'' AND ((kind='audit' AND template_version IN ('internal-audit-evidence.v1','internal-audit-evidence.v2')) OR (kind<>'audit' AND template_version='internal-project-reports.v1') OR (kind='weekly' AND template_version='internal-project-weekly.v2') OR (kind='8d' AND template_version='internal-project-8d.v2') OR (kind='dfmea' AND template_version='internal-project-dfmea.v2') OR (kind='gate' AND template_version='internal-project-gate.v2')) AND byte_size BETWEEN 1 AND 12582912 AND octet_length(content)=byte_size AND jsonb_typeof(snapshot)='object' AND snapshot->>'audience'='internal' AND jsonb_typeof(scope)='object' AND scope->>'kind'=kind AND ((kind='8d' AND ncr_id IS NOT NULL AND gate_id IS NULL) OR (kind='gate' AND gate_id IS NOT NULL AND ncr_id IS NULL) OR (kind IN ('dfmea','weekly','audit') AND ncr_id IS NULL AND gate_id IS NULL)) AND content_digest ~ '^[a-f0-9]{64}$' AND source_digest ~ '^[a-f0-9]{64}$' AND preview_digest ~ '^[a-f0-9]{64}$' AND request_digest ~ '^[a-f0-9]{64}$'"


def replace_shape(shape: str) -> None:
    op.execute(
        "ALTER TABLE cehub_project.project_report_exports DROP CONSTRAINT ck_project_report_exports_shape"
    )
    op.execute(
        "ALTER TABLE cehub_project.project_report_exports ADD CONSTRAINT ck_project_report_exports_shape CHECK ("
        + shape
        + ")"
    )


def upgrade() -> None:
    replace_shape(SHAPE)


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM cehub_project.project_report_exports WHERE template_version='internal-audit-evidence.v2') THEN RAISE EXCEPTION 'Retain readable audit report history'; END IF; END $$;"
    )
    replace_shape(OLD_SHAPE)
