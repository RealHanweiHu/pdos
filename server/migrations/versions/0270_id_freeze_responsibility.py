"""Explicit replacement of pending named design confirmations; retain every original signature."""

import sqlalchemy as sa
from alembic import op

revision = "0270_id_freeze_responsibility"
down_revision = "0269_input_wait_responsibility"
branch_labels = None
depends_on = None

DDL = """
CREATE FUNCTION cehub_product.guard_id_freeze_successor() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE previous cehub_product.id_design_freeze_requests;
BEGIN
 IF NEW.previous_request_id IS NULL THEN RETURN NEW; END IF;
 PERFORM 1 FROM cehub_project.projects
  WHERE tenant_id=NEW.tenant_id AND id=NEW.project_id FOR UPDATE;
 SELECT * INTO previous FROM cehub_product.id_design_freeze_requests
  WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id
    AND id=NEW.previous_request_id FOR UPDATE;
 IF previous.id IS NULL OR previous.id=NEW.id OR previous.revision_id<>NEW.revision_id
    OR previous.confirmation_document_id<>NEW.confirmation_document_id
    OR ROW(previous.product_user_id,previous.me_user_id,previous.hw_user_id)
       IS NOT DISTINCT FROM ROW(NEW.product_user_id,NEW.me_user_id,NEW.hw_user_id)
    OR EXISTS(SELECT 1 FROM cehub_product.id_design_freeze_requests
      WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id
        AND previous_request_id=previous.id)
    OR EXISTS(SELECT 1 FROM cehub_product.id_design_freeze_decisions
      WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id
        AND freeze_request_id=previous.id AND action='reject')
    OR EXISTS(SELECT 1 FROM cehub_product.id_design_freezes
      WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id
        AND freeze_request_id=previous.id) THEN
  RAISE EXCEPTION 'Replacement requires an unreplaced pending request and changed named reviewers'
    USING ERRCODE='23514';
 END IF;
 IF previous.snapshot::jsonb->'revision' IS DISTINCT FROM NEW.snapshot::jsonb->'revision'
    OR previous.snapshot::jsonb->'feedback_basis'
       IS DISTINCT FROM NEW.snapshot::jsonb->'feedback_basis'
    OR previous.snapshot::jsonb->'feedback_digest'
       IS DISTINCT FROM NEW.snapshot::jsonb->'feedback_digest'
    OR previous.snapshot::jsonb->'confirmation_evidence'
       IS DISTINCT FROM NEW.snapshot::jsonb->'confirmation_evidence'
    OR COALESCE(previous.snapshot::jsonb->'change_origin','null'::jsonb)
       IS DISTINCT FROM COALESCE(NEW.snapshot::jsonb->'change_origin','null'::jsonb)
    OR NEW.snapshot::jsonb->'responsibility_renewal'->>'previous_request_id'
       IS DISTINCT FROM previous.id::text
    OR NEW.snapshot::jsonb->'responsibility_renewal'->>'previous_digest'
       IS DISTINCT FROM previous.payload_digest THEN
  RAISE EXCEPTION 'Review responsibility replacement must preserve the original source package'
    USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION cehub_product.guard_id_freeze_unsuperseded() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 PERFORM 1 FROM cehub_project.projects
  WHERE tenant_id=NEW.tenant_id AND id=NEW.project_id FOR UPDATE;
 IF EXISTS(SELECT 1 FROM cehub_product.id_design_freeze_requests
   WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id
     AND previous_request_id=NEW.freeze_request_id) THEN
  RAISE EXCEPTION 'Superseded requests cannot receive new decisions or apply'
    USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION cehub_product.guard_id_freeze_successor() FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_product.guard_id_freeze_unsuperseded() FROM PUBLIC;
CREATE TRIGGER guard_id_freeze_successor BEFORE INSERT ON cehub_product.id_design_freeze_requests
 FOR EACH ROW EXECUTE FUNCTION cehub_product.guard_id_freeze_successor();
CREATE TRIGGER guard_id_freeze_unsuperseded BEFORE INSERT
 ON cehub_product.id_design_freeze_decisions
 FOR EACH ROW EXECUTE FUNCTION cehub_product.guard_id_freeze_unsuperseded();
CREATE TRIGGER guard_id_freeze_unsuperseded BEFORE INSERT ON cehub_product.id_design_freezes
 FOR EACH ROW EXECUTE FUNCTION cehub_product.guard_id_freeze_unsuperseded();
"""


def upgrade() -> None:
    op.add_column(
        "id_design_freeze_requests",
        sa.Column("previous_request_id", sa.Uuid),
        schema="cehub_product",
    )
    op.create_foreign_key(
        "fk_id_freeze_request_previous",
        "id_design_freeze_requests",
        "id_design_freeze_requests",
        ["tenant_id", "project_id", "previous_request_id"],
        ["tenant_id", "project_id", "id"],
        source_schema="cehub_product",
        referent_schema="cehub_product",
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_id_freeze_request_successor",
        "id_design_freeze_requests",
        ["tenant_id", "project_id", "previous_request_id"],
        schema="cehub_product",
    )
    op.create_check_constraint(
        "id_freeze_request_not_self",
        "id_design_freeze_requests",
        "previous_request_id IS NULL OR previous_request_id<>id",
        schema="cehub_product",
    )
    op.execute(DDL)


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM cehub_product.id_design_freeze_requests "
                "WHERE previous_request_id IS NOT NULL)"
            )
        )
        .scalar_one()
    ):
        raise RuntimeError("Refusing to erase named confirmation replacement history")
    for table in ("id_design_freeze_decisions", "id_design_freezes"):
        op.execute(f"DROP TRIGGER guard_id_freeze_unsuperseded ON cehub_product.{table}")
    op.execute("DROP FUNCTION cehub_product.guard_id_freeze_unsuperseded()")
    op.execute("DROP TRIGGER guard_id_freeze_successor ON cehub_product.id_design_freeze_requests")
    op.execute("DROP FUNCTION cehub_product.guard_id_freeze_successor()")
    op.drop_constraint(
        "id_freeze_request_not_self",
        "id_design_freeze_requests",
        type_="check",
        schema="cehub_product",
    )
    op.drop_constraint(
        "uq_id_freeze_request_successor",
        "id_design_freeze_requests",
        type_="unique",
        schema="cehub_product",
    )
    op.drop_constraint(
        "fk_id_freeze_request_previous",
        "id_design_freeze_requests",
        type_="foreignkey",
        schema="cehub_product",
    )
    op.drop_column("id_design_freeze_requests", "previous_request_id", schema="cehub_product")
