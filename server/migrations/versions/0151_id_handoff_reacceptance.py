"""Permit renewed ID handoff when prior evidence or accountable people become stale."""

import sqlalchemy as sa
from alembic import op

revision = "0151_id_handoff_reacceptance"
down_revision = "0150_id_design_handoff"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE OR REPLACE FUNCTION cehub_product.guard_id_handoff() "
        "RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog "
        "AS $$\nDECLARE previous cehub_product.id_design_handoffs%ROWT"
        "YPE;\nBEGIN\n PERFORM 1 FROM cehub_project.projects WHERE tena"
        "nt_id=NEW.tenant_id AND id=NEW.project_id FOR UPDATE;\n SELEC"
        "T * INTO previous FROM cehub_product.id_design_handoffs WHER"
        "E tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND "
        "freeze_id=NEW.freeze_id AND target_node_id=NEW.target_node_i"
        "d ORDER BY version DESC LIMIT 1;\n IF NEW.version<>COALESCE(p"
        "revious.version,0)+1 OR NEW.previous_handoff_id IS DISTINCT "
        "FROM previous.id THEN RAISE EXCEPTION 'Handoff must append t"
        "o the current round' USING ERRCODE='23514'; END IF;\n IF prev"
        "ious.id IS NOT NULL AND previous.snapshot->'target'->>'targe"
        "t_digest' IS NOT DISTINCT FROM NEW.snapshot->'target'->>'tar"
        "get_digest' AND NOT (EXISTS(SELECT 1 FROM cehub_product.id_d"
        "esign_handoff_items i LEFT JOIN cehub_project.documents d ON"
        " d.tenant_id=i.tenant_id AND d.project_id=i.project_id AND d"
        ".id=i.document_id WHERE i.tenant_id=NEW.tenant_id AND i.proj"
        "ect_id=NEW.project_id AND i.handoff_id=previous.id AND (d.id"
        " IS NULL OR d.sha256 IS DISTINCT FROM i.artifact_snapshot->>"
        "'sha256')) OR EXISTS(SELECT 1 FROM (SELECT previous.receiver"
        "_user_id AS id UNION SELECT (residual->>'owner_user_id')::uu"
        "id FROM cehub_product.id_design_handoff_items i CROSS JOIN L"
        "ATERAL jsonb_array_elements(i.residuals) residual WHERE i.te"
        "nant_id=NEW.tenant_id AND i.project_id=NEW.project_id AND i."
        "handoff_id=previous.id) person WHERE NOT EXISTS(SELECT 1 FRO"
        "M cehub_core.users u WHERE u.tenant_id=NEW.tenant_id AND u.i"
        "d=person.id AND u.is_active AND u.role IN ('owner','admin','"
        "project_manager','engineer','quality') AND (u.role IN ('owne"
        "r','admin') OR EXISTS(SELECT 1 FROM cehub_project.project_me"
        "mbers m WHERE m.tenant_id=NEW.tenant_id AND m.project_id=NEW"
        ".project_id AND m.user_id=u.id))))) AND NOT EXISTS(SELECT 1 "
        "FROM cehub_product.id_design_handoff_responses r JOIN cehub_"
        "product.id_design_handoff_items i ON i.tenant_id=r.tenant_id"
        " AND i.project_id=r.project_id AND i.id=r.item_id WHERE i.te"
        "nant_id=NEW.tenant_id AND i.project_id=NEW.project_id AND i."
        "handoff_id=previous.id AND r.action='return') THEN RAISE EXC"
        "EPTION 'Resubmission requires a returned package' USING ERRC"
        "ODE='23514'; END IF;\n IF NEW.snapshot->'freeze'->>'id' IS DI"
        "STINCT FROM NEW.freeze_id::text OR NEW.snapshot->'target'->>"
        "'node_id' IS DISTINCT FROM NEW.target_node_id::text OR NEW.s"
        "napshot->>'receiver_user_id' IS DISTINCT FROM NEW.receiver_u"
        "ser_id::text OR COALESCE(jsonb_array_length(NEW.snapshot->'i"
        "tems'),0) NOT BETWEEN 1 AND 30 THEN RAISE EXCEPTION 'Handoff"
        " package scope is inconsistent' USING ERRCODE='23514'; END I"
        "F;\n RETURN NEW;\nEND $$;\n"
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text("SELECT EXISTS(SELECT 1 FROM cehub_product.id_design_handoffs WHERE version>1)")
        )
        .scalar_one()
    ):
        raise RuntimeError("Refusing to invalidate recorded ID reacceptance history")
    op.execute(
        "CREATE OR REPLACE FUNCTION cehub_product.guard_id_handoff() "
        "RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog "
        "AS $$\nDECLARE previous cehub_product.id_design_handoffs%ROWT"
        "YPE;\nBEGIN\n PERFORM 1 FROM cehub_project.projects WHERE tena"
        "nt_id=NEW.tenant_id AND id=NEW.project_id FOR UPDATE;\n SELEC"
        "T * INTO previous FROM cehub_product.id_design_handoffs WHER"
        "E tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND "
        "freeze_id=NEW.freeze_id AND target_node_id=NEW.target_node_i"
        "d ORDER BY version DESC LIMIT 1;\n IF NEW.version<>COALESCE(p"
        "revious.version,0)+1 OR NEW.previous_handoff_id IS DISTINCT "
        "FROM previous.id THEN RAISE EXCEPTION 'Handoff must append t"
        "o the current round' USING ERRCODE='23514'; END IF;\n IF prev"
        "ious.id IS NOT NULL AND previous.snapshot->'target'->>'targe"
        "t_digest' IS NOT DISTINCT FROM NEW.snapshot->'target'->>'tar"
        "get_digest' AND NOT EXISTS(SELECT 1 FROM cehub_product.id_de"
        "sign_handoff_responses r JOIN cehub_product.id_design_handof"
        "f_items i ON i.tenant_id=r.tenant_id AND i.project_id=r.proj"
        "ect_id AND i.id=r.item_id WHERE i.tenant_id=NEW.tenant_id AN"
        "D i.project_id=NEW.project_id AND i.handoff_id=previous.id A"
        "ND r.action='return') THEN RAISE EXCEPTION 'Resubmission req"
        "uires a returned package' USING ERRCODE='23514'; END IF;\n IF"
        " NEW.snapshot->'freeze'->>'id' IS DISTINCT FROM NEW.freeze_i"
        "d::text OR NEW.snapshot->'target'->>'node_id' IS DISTINCT FR"
        "OM NEW.target_node_id::text OR NEW.snapshot->>'receiver_user"
        "_id' IS DISTINCT FROM NEW.receiver_user_id::text OR COALESCE"
        "(jsonb_array_length(NEW.snapshot->'items'),0) NOT BETWEEN 1 "
        "AND 30 THEN RAISE EXCEPTION 'Handoff package scope is incons"
        "istent' USING ERRCODE='23514'; END IF;\n RETURN NEW;\nEND $$;\n"
    )
