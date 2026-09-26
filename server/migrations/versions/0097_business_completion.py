"""N0 business completion evidence, handoff acceptance, and Issue policy.

Revision ID: 0097_business_completion
Revises: 0096_event_run_pauses
"""

import sqlalchemy as sa
from alembic import op

revision = "0097_business_completion"
down_revision = "0096_event_run_pauses"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "\n        ALTER TABLE cehub_project.projects\n          ADD CO"
        "LUMN issue_verify_low boolean NOT NULL DEFAULT false,\n      "
        "    ADD COLUMN issue_verify_medium boolean NOT NULL DEFAULT "
        "false;\n        ALTER TABLE cehub_project.decisions\n         "
        " ADD COLUMN follow_up_task_id uuid,\n          ADD COLUMN fol"
        "low_up_audit_id bigint REFERENCES cehub_audit.audit_log(id) "
        "ON DELETE RESTRICT,\n          ADD CONSTRAINT fk_decisions_te"
        "nant_project_follow_up_task\n            FOREIGN KEY (tenant_"
        "id, project_id, follow_up_task_id)\n            REFERENCES ce"
        "hub_project.tasks(tenant_id, project_id, id) ON DELETE RESTR"
        "ICT;\n        CREATE TABLE cehub_project.project_handoff_item"
        "s (\n          id uuid PRIMARY KEY, tenant_id uuid NOT NULL, "
        "project_id uuid NOT NULL,\n          item_key varchar(32) NOT"
        " NULL, document_id uuid NOT NULL,\n          receiver_user_id"
        " uuid NOT NULL, prepared_by_user_id uuid NOT NULL,\n         "
        " status varchar(16) NOT NULL DEFAULT 'pending', note text NO"
        "T NULL,\n          accepted_fingerprint varchar(64), responde"
        "d_at timestamptz,\n          created_at timestamptz NOT NULL "
        "DEFAULT CURRENT_TIMESTAMP,\n          updated_at timestamptz "
        "NOT NULL DEFAULT CURRENT_TIMESTAMP,\n          CONSTRAINT ck_"
        "project_handoff_items_item_key_allowed CHECK\n            (it"
        "em_key IN ('configuration','bom','manufacturing','test_certi"
        "fication','training','residuals','quality_follow_up')),\n    "
        "      CONSTRAINT ck_project_handoff_items_status_allowed CHE"
        "CK (status IN ('pending','accepted','returned')),\n          "
        "CONSTRAINT ck_project_handoff_items_note_nonblank CHECK (btr"
        "im(note) <> ''),\n          CONSTRAINT ck_project_handoff_ite"
        "ms_acceptance_consistent CHECK ((status = 'accepted') = (acc"
        "epted_fingerprint IS NOT NULL)),\n          CONSTRAINT ck_pro"
        "ject_handoff_items_response_consistent CHECK ((status = 'pen"
        "ding') = (responded_at IS NULL)),\n          CONSTRAINT fk_pr"
        "oject_handoff_items_project FOREIGN KEY (tenant_id, project_"
        "id) REFERENCES cehub_project.projects(tenant_id, id) ON DELE"
        "TE RESTRICT,\n          CONSTRAINT fk_project_handoff_items_d"
        "ocument FOREIGN KEY (tenant_id, project_id, document_id) REF"
        "ERENCES cehub_project.documents(tenant_id, project_id, id) O"
        "N DELETE RESTRICT,\n          CONSTRAINT fk_project_handoff_i"
        "tems_receiver FOREIGN KEY (tenant_id, receiver_user_id) REFE"
        "RENCES cehub_core.users(tenant_id, id) ON DELETE RESTRICT,\n "
        "         CONSTRAINT fk_project_handoff_items_preparer FOREIG"
        "N KEY (tenant_id, prepared_by_user_id) REFERENCES cehub_core"
        ".users(tenant_id, id) ON DELETE RESTRICT,\n          CONSTRAI"
        "NT uq_project_handoff_items_project_key UNIQUE (tenant_id, p"
        "roject_id, item_key)\n        );\n    "
    )


def downgrade() -> None:
    connection = op.get_bind()
    if connection.execute(
        sa.text(
            "SELECT EXISTS(SELECT 1 FROM cehub_project.project_handoff_it"
            "ems) OR EXISTS(SELECT 1 FROM cehub_project.decisions WHERE f"
            "ollow_up_audit_id IS NOT NULL OR follow_up_task_id IS NOT NU"
            "LL) OR EXISTS(SELECT 1 FROM cehub_project.projects WHERE iss"
            "ue_verify_low OR issue_verify_medium)"
        )
    ).scalar_one():
        raise RuntimeError("Refusing to discard business completion evidence or configured policy")
    op.drop_table("project_handoff_items", schema="cehub_project")
    op.drop_column("decisions", "follow_up_audit_id", schema="cehub_project")
    op.drop_column("decisions", "follow_up_task_id", schema="cehub_project")
    op.drop_column("projects", "issue_verify_low", schema="cehub_project")
    op.drop_column("projects", "issue_verify_medium", schema="cehub_project")
