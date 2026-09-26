"""Allow explicit named receiver succession as a new immutable ID handoff round."""

import sqlalchemy as sa
from alembic import op

revision = "0271_id_handoff_receiver"
down_revision = "0270_id_freeze_responsibility"
branch_labels = None
depends_on = None

ORIGINAL_GUARD = (
    "CREATE OR REPLACE FUNCTION cehub_product.guard_id_handoff() RETURNS trigger LANGUAGE p"
    "lpgsql SET search_path=pg_catalog AS $$\nDECLARE previous cehub_product.id_design_hando"
    "ffs%ROWTYPE;\nBEGIN\n PERFORM 1 FROM cehub_project.projects WHERE tenant_id=NEW.tenant_i"
    "d AND id=NEW.project_id FOR UPDATE;\n SELECT * INTO previous FROM cehub_product.id_desi"
    "gn_handoffs WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND freeze_id="
    "NEW.freeze_id AND target_node_id=NEW.target_node_id ORDER BY version DESC LIMIT 1;\n IF"
    " NEW.version<>COALESCE(previous.version,0)+1 OR NEW.previous_handoff_id IS DISTINCT FR"
    "OM previous.id THEN RAISE EXCEPTION 'Handoff must append to the current round' USING E"
    "RRCODE='23514'; END IF;\n IF previous.id IS NOT NULL AND previous.snapshot->'target'->>"
    "'target_digest' IS NOT DISTINCT FROM NEW.snapshot->'target'->>'target_digest' AND NOT "
    "(EXISTS(SELECT 1 FROM cehub_product.id_design_handoff_items i LEFT JOIN cehub_project."
    "documents d ON d.tenant_id=i.tenant_id AND d.project_id=i.project_id AND d.id=i.docume"
    "nt_id WHERE i.tenant_id=NEW.tenant_id AND i.project_id=NEW.project_id AND i.handoff_id"
    "=previous.id AND (d.id IS NULL OR d.sha256 IS DISTINCT FROM i.artifact_snapshot->>'sha"
    "256')) OR EXISTS(SELECT 1 FROM (SELECT previous.receiver_user_id AS id UNION SELECT (r"
    "esidual->>'owner_user_id')::uuid FROM cehub_product.id_design_handoff_items i CROSS JO"
    "IN LATERAL jsonb_array_elements(i.residuals) residual WHERE i.tenant_id=NEW.tenant_id "
    "AND i.project_id=NEW.project_id AND i.handoff_id=previous.id) person WHERE NOT EXISTS("
    "SELECT 1 FROM cehub_core.users u WHERE u.tenant_id=NEW.tenant_id AND u.id=person.id AN"
    "D u.is_active AND u.role IN ('owner','admin','project_manager','engineer','quality') A"
    "ND (u.role IN ('owner','admin') OR EXISTS(SELECT 1 FROM cehub_project.project_members "
    "m WHERE m.tenant_id=NEW.tenant_id AND m.project_id=NEW.project_id AND m.user_id=u.id))"
    "))) AND NOT EXISTS(SELECT 1 FROM cehub_product.id_design_handoff_responses r JOIN cehu"
    "b_product.id_design_handoff_items i ON i.tenant_id=r.tenant_id AND i.project_id=r.proj"
    "ect_id AND i.id=r.item_id WHERE i.tenant_id=NEW.tenant_id AND i.project_id=NEW.project"
    "_id AND i.handoff_id=previous.id AND r.action='return') THEN RAISE EXCEPTION 'Resubmis"
    "sion requires a returned package' USING ERRCODE='23514'; END IF;\n IF NEW.snapshot->'fr"
    "eeze'->>'id' IS DISTINCT FROM NEW.freeze_id::text OR NEW.snapshot->'target'->>'node_id"
    "' IS DISTINCT FROM NEW.target_node_id::text OR NEW.snapshot->>'receiver_user_id' IS DI"
    "STINCT FROM NEW.receiver_user_id::text OR COALESCE(jsonb_array_length(NEW.snapshot->'i"
    "tems'),0) NOT BETWEEN 1 AND 30 THEN RAISE EXCEPTION 'Handoff package scope is inconsis"
    "tent' USING ERRCODE='23514'; END IF;\n RETURN NEW;\nEND $$;\n"
)

RENEWED_GUARD = (
    "CREATE OR REPLACE FUNCTION cehub_product.guard_id_handoff() RETURNS trigger LANGUAGE p"
    "lpgsql SET search_path=pg_catalog AS $$\nDECLARE previous cehub_product.id_design_hando"
    "ffs%ROWTYPE;\nBEGIN\n PERFORM 1 FROM cehub_project.projects WHERE tenant_id=NEW.tenant_i"
    "d AND id=NEW.project_id FOR UPDATE;\n SELECT * INTO previous FROM cehub_product.id_desi"
    "gn_handoffs WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND freeze_id="
    "NEW.freeze_id AND target_node_id=NEW.target_node_id ORDER BY version DESC LIMIT 1;\n IF"
    " NEW.version<>COALESCE(previous.version,0)+1 OR NEW.previous_handoff_id IS DISTINCT FR"
    "OM previous.id THEN RAISE EXCEPTION 'Handoff must append to the current round' USING E"
    "RRCODE='23514'; END IF;\n IF NEW.snapshot ? 'receiver_renewal' THEN\n  IF previous.id IS"
    " NULL OR previous.receiver_user_id=NEW.receiver_user_id\n    OR NEW.snapshot->'receiver"
    "_renewal'->>'previous_handoff_id' IS DISTINCT FROM previous.id::text\n    OR NEW.snapsh"
    "ot->'receiver_renewal'->>'previous_digest' IS DISTINCT FROM previous.payload_digest\n  "
    "  OR NEW.snapshot->'receiver_renewal'->>'previous_receiver_user_id'\n       IS DISTINCT"
    " FROM previous.receiver_user_id::text\n    OR NEW.snapshot->'freeze' IS DISTINCT FROM p"
    "revious.snapshot->'freeze'\n    OR NEW.snapshot->'revision' IS DISTINCT FROM previous.s"
    "napshot->'revision'\n    OR NEW.snapshot->'items' IS DISTINCT FROM previous.snapshot->'"
    "items'\n    OR NEW.snapshot->'target'->>'target_digest'\n       IS DISTINCT FROM previou"
    "s.snapshot->'target'->>'target_digest'\n    OR (NEW.receiver_user_id::text IS DISTINCT "
    "FROM NEW.snapshot->'target'->>'owner_user_id'\n        AND NEW.receiver_user_id::text I"
    "S DISTINCT FROM NEW.snapshot->'target'->>'receiver_user_id')\n    OR ((NEW.snapshot->'t"
    "arget') - 'baseline_id' - 'baseline_version')\n        IS DISTINCT FROM ((previous.snap"
    "shot->'target') - 'baseline_id' - 'baseline_version')\n    OR EXISTS(SELECT 1 FROM cehu"
    "b_product.id_design_handoff_responses r\n       JOIN cehub_product.id_design_handoff_it"
    "ems i ON i.tenant_id=r.tenant_id\n        AND i.project_id=r.project_id AND i.id=r.item"
    "_id\n       WHERE i.tenant_id=NEW.tenant_id AND i.project_id=NEW.project_id\n        AND"
    " i.handoff_id=previous.id AND r.action='return')\n    OR NOT EXISTS(SELECT 1 FROM cehub"
    "_product.id_design_handoff_items i\n       WHERE i.tenant_id=NEW.tenant_id AND i.projec"
    "t_id=NEW.project_id\n        AND i.handoff_id=previous.id AND NOT EXISTS(\n         SELE"
    "CT 1 FROM cehub_product.id_design_handoff_responses r\n          WHERE r.tenant_id=i.te"
    "nant_id AND r.project_id=i.project_id AND r.item_id=i.id)) THEN\n   RAISE EXCEPTION 'Re"
    "ceiver renewal must preserve a pending original package with a new named receiver'\n   "
    " USING ERRCODE='23514';\n  END IF;\n END IF;\n IF NOT (NEW.snapshot ? 'receiver_renewal')"
    " AND previous.id IS NOT NULL AND previous.snapshot->'target'->>'target_digest' IS NOT "
    "DISTINCT FROM NEW.snapshot->'target'->>'target_digest' AND NOT (EXISTS(SELECT 1 FROM c"
    "ehub_product.id_design_handoff_items i LEFT JOIN cehub_project.documents d ON d.tenant"
    "_id=i.tenant_id AND d.project_id=i.project_id AND d.id=i.document_id WHERE i.tenant_id"
    "=NEW.tenant_id AND i.project_id=NEW.project_id AND i.handoff_id=previous.id AND (d.id "
    "IS NULL OR d.sha256 IS DISTINCT FROM i.artifact_snapshot->>'sha256')) OR EXISTS(SELECT"
    " 1 FROM (SELECT previous.receiver_user_id AS id UNION SELECT (residual->>'owner_user_i"
    "d')::uuid FROM cehub_product.id_design_handoff_items i CROSS JOIN LATERAL jsonb_array_"
    "elements(i.residuals) residual WHERE i.tenant_id=NEW.tenant_id AND i.project_id=NEW.pr"
    "oject_id AND i.handoff_id=previous.id) person WHERE NOT EXISTS(SELECT 1 FROM cehub_cor"
    "e.users u WHERE u.tenant_id=NEW.tenant_id AND u.id=person.id AND u.is_active AND u.rol"
    "e IN ('owner','admin','project_manager','engineer','quality') AND (u.role IN ('owner',"
    "'admin') OR EXISTS(SELECT 1 FROM cehub_project.project_members m WHERE m.tenant_id=NEW"
    ".tenant_id AND m.project_id=NEW.project_id AND m.user_id=u.id))))) AND NOT EXISTS(SELE"
    "CT 1 FROM cehub_product.id_design_handoff_responses r JOIN cehub_product.id_design_han"
    "doff_items i ON i.tenant_id=r.tenant_id AND i.project_id=r.project_id AND i.id=r.item_"
    "id WHERE i.tenant_id=NEW.tenant_id AND i.project_id=NEW.project_id AND i.handoff_id=pr"
    "evious.id AND r.action='return') THEN RAISE EXCEPTION 'Resubmission requires a returne"
    "d package' USING ERRCODE='23514'; END IF;\n IF NEW.snapshot->'freeze'->>'id' IS DISTINC"
    "T FROM NEW.freeze_id::text OR NEW.snapshot->'target'->>'node_id' IS DISTINCT FROM NEW."
    "target_node_id::text OR NEW.snapshot->>'receiver_user_id' IS DISTINCT FROM NEW.receive"
    "r_user_id::text OR COALESCE(jsonb_array_length(NEW.snapshot->'items'),0) NOT BETWEEN 1"
    " AND 30 THEN RAISE EXCEPTION 'Handoff package scope is inconsistent' USING ERRCODE='23"
    "514'; END IF;\n RETURN NEW;\nEND $$;\n"
)


def upgrade() -> None:
    op.execute(RENEWED_GUARD)


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM cehub_product.id_design_handoffs "
                "WHERE snapshot ? 'receiver_renewal')"
            )
        )
        .scalar_one()
    ):
        raise RuntimeError("Refusing to invalidate named receiver renewal history")
    op.execute(ORIGINAL_GUARD)
