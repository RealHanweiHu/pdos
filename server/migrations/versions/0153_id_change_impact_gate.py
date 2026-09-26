"""Require complete source-bound ID impact analysis and separate human approval."""

from alembic import op

revision = "0153_id_change_impact_gate"
down_revision = "0152_id_design_change_routing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "\nCREATE FUNCTION cehub_product.guard_id_change_impact_gate()"
        " RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog"
        " AS $$\nDECLARE design jsonb; axis text; feedback_count integ"
        "er; link_count integer;\nBEGIN\n IF NEW.status NOT IN ('approv"
        "al','approved') THEN RETURN NEW; END IF;\n IF NEW.status='app"
        "roved' AND (NEW.approved_by_user_id=NEW.requested_by_user_id"
        " OR NEW.approved_by_user_id=NEW.analyzed_by_user_id) THEN RA"
        "ISE EXCEPTION 'ECR approval must be separate from requester "
        "and analyst' USING ERRCODE='23514'; END IF;\n SELECT count(*)"
        " INTO link_count FROM cehub_product.id_design_change_decisio"
        "ns WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_"
        "id AND ecr_id=NEW.id;\n IF link_count=0 THEN RETURN NEW; END "
        "IF;\n design:=NEW.impact_analysis->'id_design';\n IF design IS"
        " NULL OR design->'basis'->>'version' IS DISTINCT FROM 'id_ch"
        "ange_impact.v1' OR COALESCE(design->>'expected_basis_digest'"
        ",'') !~ '^[0-9a-f]{64}$' OR jsonb_typeof(design->'feedback_r"
        "esponses') IS DISTINCT FROM 'object' OR jsonb_typeof(design-"
        ">'assessments') IS DISTINCT FROM 'object' THEN RAISE EXCEPTI"
        "ON 'ID impact analysis must carry the fixed source package' "
        "USING ERRCODE='23514'; END IF;\n SELECT count(*) INTO feedbac"
        "k_count FROM jsonb_object_keys(design->'feedback_responses')"
        ";\n IF feedback_count<>link_count OR EXISTS(SELECT 1 FROM ceh"
        "ub_product.id_design_change_decisions l WHERE l.tenant_id=NE"
        "W.tenant_id AND l.project_id=NEW.project_id AND l.ecr_id=NEW"
        ".id AND (COALESCE(btrim(design->'feedback_responses'->>l.can"
        "didate_id::text),'')='' OR NOT EXISTS(SELECT 1 FROM jsonb_ar"
        "ray_elements(design->'basis'->'links') source WHERE source->"
        ">'id'=l.id::text AND source->>'candidate_digest'=l.candidate"
        "_digest))) THEN RAISE EXCEPTION 'Every current ID feedback s"
        "ource needs an explicit response' USING ERRCODE='23514'; END"
        " IF;\n FOREACH axis IN ARRAY ARRAY['requirements','mechanical"
        "','hardware','firmware','verification','supply','cost','sche"
        "dule','handoffs'] LOOP\n  IF COALESCE(design->'assessments'->"
        "axis->>'conclusion','') NOT IN ('affected','unaffected','unk"
        "nown') OR COALESCE(btrim(design->'assessments'->axis->>'basi"
        "s'),'')='' OR (design->'assessments'->axis->>'conclusion'='a"
        "ffected' AND COALESCE(btrim(design->'assessments'->axis->>'n"
        "ext_action'),'')='') OR (NEW.status='approved' AND design->'"
        "assessments'->axis->>'conclusion'='unknown') THEN RAISE EXCE"
        "PTION 'ID impact assessment is incomplete or unresolved' USI"
        "NG ERRCODE='23514'; END IF;\n END LOOP;\n RETURN NEW;\nEND $$;\n"
        "CREATE TRIGGER guard_id_change_impact_gate BEFORE INSERT OR "
        "UPDATE OF status,impact_analysis ON cehub_product.engineerin"
        "g_change_requests FOR EACH ROW EXECUTE FUNCTION cehub_produc"
        "t.guard_id_change_impact_gate();\nREVOKE ALL ON FUNCTION cehu"
        "b_product.guard_id_change_impact_gate() FROM PUBLIC;\n"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER guard_id_change_impact_gate ON cehub_product.engineering_change_requests"
    )
    op.execute("DROP FUNCTION cehub_product.guard_id_change_impact_gate()")
