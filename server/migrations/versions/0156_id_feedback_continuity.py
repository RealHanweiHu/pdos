"""Keep historical ID feedback original while evaluating pending requests on active revisions."""

import sqlalchemy as sa
from alembic import op

revision = "0156_id_feedback_continuity"
down_revision = "0155_id_design_activation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE OR REPLACE FUNCTION cehub_product.guard_id_change_dec"
        "ision() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_"
        "catalog AS $$\nDECLARE candidate cehub_product.id_design_chan"
        "ge_candidates%ROWTYPE; current_freeze uuid; chain_ids uuid[]"
        "; lineage_count integer;\nBEGIN\n PERFORM 1 FROM cehub_project"
        ".projects WHERE tenant_id=NEW.tenant_id AND id=NEW.project_i"
        "d FOR UPDATE;\n SELECT * INTO candidate FROM cehub_product.id"
        "_design_change_candidates WHERE tenant_id=NEW.tenant_id AND "
        "project_id=NEW.project_id AND id=NEW.candidate_id;\n IF candi"
        "date.id IS NULL THEN RAISE EXCEPTION 'Missing scoped ID feed"
        "back candidate' USING ERRCODE='23514'; END IF;\n WITH RECURSI"
        "VE chain(id) AS (SELECT candidate.freeze_id UNION SELECT a.n"
        "ew_freeze_id FROM cehub_product.id_design_activations a JOIN"
        " chain c ON c.id=a.old_freeze_id WHERE a.tenant_id=NEW.tenan"
        "t_id AND a.project_id=NEW.project_id) SELECT array_agg(id) I"
        "NTO chain_ids FROM chain;\n SELECT f.id INTO current_freeze F"
        "ROM cehub_product.id_design_freezes f WHERE f.tenant_id=NEW."
        "tenant_id AND f.project_id=NEW.project_id AND f.id=ANY(chain"
        "_ids) AND NOT EXISTS(SELECT 1 FROM cehub_product.id_design_a"
        "ctivations a WHERE a.tenant_id=NEW.tenant_id AND a.project_i"
        "d=NEW.project_id AND a.old_freeze_id=f.id);\n IF current_free"
        "ze IS NULL OR EXISTS(SELECT 1 FROM cehub_product.id_design_f"
        "reezes f JOIN cehub_product.id_design_change_branches b ON b"
        ".tenant_id=f.tenant_id AND b.project_id=f.project_id AND b.v"
        "ariant_id=f.variant_id WHERE f.tenant_id=NEW.tenant_id AND f"
        ".project_id=NEW.project_id AND f.id=current_freeze AND NOT E"
        "XISTS(SELECT 1 FROM cehub_product.id_design_activations WHER"
        "E tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND "
        "new_freeze_id=current_freeze)) THEN RAISE EXCEPTION 'Feedbac"
        "k must be evaluated against the active frozen design' USING "
        "ERRCODE='23514'; END IF;\n IF NEW.snapshot->'candidate'->>'id"
        "' IS DISTINCT FROM candidate.id::text OR NEW.snapshot->'orig"
        "inal_freeze'->>'id' IS DISTINCT FROM candidate.freeze_id::te"
        "xt OR NEW.snapshot->'freeze'->>'id' IS DISTINCT FROM current"
        "_freeze::text OR NEW.snapshot->'feedback'->>'id' IS DISTINCT"
        " FROM candidate.feedback_id::text OR jsonb_typeof(NEW.snapsh"
        "ot->'activation_lineage') IS DISTINCT FROM 'array' THEN RAIS"
        "E EXCEPTION 'Original feedback and current design evaluation"
        " must remain distinct' USING ERRCODE='23514'; END IF;\n SELEC"
        "T count(*) INTO lineage_count FROM cehub_product.id_design_a"
        "ctivations a WHERE a.tenant_id=NEW.tenant_id AND a.project_i"
        "d=NEW.project_id AND a.old_freeze_id=ANY(chain_ids);\n IF jso"
        "nb_array_length(NEW.snapshot->'activation_lineage')<>lineage"
        "_count OR EXISTS(SELECT 1 FROM cehub_product.id_design_activ"
        "ations a WHERE a.tenant_id=NEW.tenant_id AND a.project_id=NE"
        "W.project_id AND a.old_freeze_id=ANY(chain_ids) AND NOT EXIS"
        "TS(SELECT 1 FROM jsonb_array_elements(NEW.snapshot->'activat"
        "ion_lineage') l WHERE l->>'id'=a.id::text AND l->>'old_freez"
        "e_id'=a.old_freeze_id::text AND l->>'new_freeze_id'=a.new_fr"
        "eeze_id::text)) THEN RAISE EXCEPTION 'Feedback routing must "
        "preserve the actual replacement lineage' USING ERRCODE='2351"
        "4'; END IF;\n IF NEW.action='route_ecr' AND NOT EXISTS(SELECT"
        " 1 FROM cehub_product.engineering_change_requests WHERE tena"
        "nt_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW"
        ".ecr_id AND status IN ('request','impact_analysis')) THEN RA"
        "ISE EXCEPTION 'New design requirements cannot inherit alread"
        "y submitted ECR approval' USING ERRCODE='23514'; END IF;\n RE"
        "TURN NEW;\nEND $$;\n"
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM cehub_product.id_design_change_d"
                "ecisions WHERE jsonb_array_length(COALESCE(snapshot->'activa"
                "tion_lineage','[]'::jsonb))>0)"
            )
        )
        .scalar_one()
    ):
        raise RuntimeError("Refusing to remove recorded cross-version feedback continuity")
    op.execute(
        "CREATE OR REPLACE FUNCTION cehub_product.guard_id_change_dec"
        "ision() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_"
        "catalog AS $$\nDECLARE candidate cehub_product.id_design_chan"
        "ge_candidates%ROWTYPE;\nBEGIN\n PERFORM 1 FROM cehub_project.p"
        "rojects WHERE tenant_id=NEW.tenant_id AND id=NEW.project_id "
        "FOR UPDATE;\n SELECT * INTO candidate FROM cehub_product.id_d"
        "esign_change_candidates WHERE tenant_id=NEW.tenant_id AND pr"
        "oject_id=NEW.project_id AND id=NEW.candidate_id;\n IF candida"
        "te.id IS NULL OR NEW.snapshot->'candidate'->>'id' IS DISTINC"
        "T FROM candidate.id::text OR NEW.snapshot->'freeze'->>'id' I"
        "S DISTINCT FROM candidate.freeze_id::text OR NEW.snapshot->'"
        "feedback'->>'id' IS DISTINCT FROM candidate.feedback_id::tex"
        "t THEN RAISE EXCEPTION 'Design change decision must bind the"
        " original frozen feedback' USING ERRCODE='23514'; END IF;\n I"
        "F NEW.action='route_ecr' AND NOT EXISTS(SELECT 1 FROM cehub_"
        "product.engineering_change_requests WHERE tenant_id=NEW.tena"
        "nt_id AND project_id=NEW.project_id AND id=NEW.ecr_id AND st"
        "atus IN ('request','impact_analysis')) THEN RAISE EXCEPTION "
        "'New design requirements cannot inherit already submitted EC"
        "R approval' USING ERRCODE='23514'; END IF;\n RETURN NEW;\nEND "
        "$$;\n"
    )
