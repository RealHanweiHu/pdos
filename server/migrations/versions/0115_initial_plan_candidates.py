"""Immutable initial-plan candidates for opportunity, definition and Case sources."""

import sqlalchemy as sa
from alembic import op

revision = "0115_initial_plan_candidates"
down_revision = "0114_review_material_consistency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "\nCREATE TABLE cehub_project.initial_plan_candidates (\n\tid UU"
        "ID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tmarket_space_id UU"
        "ID, \n\tproduct_line_id UUID, \n\topportunity_id UUID, \n\tdefinit"
        "ion_id UUID, \n\tcase_id UUID, \n\tseries_id UUID NOT NULL, \n\tsu"
        "persedes_id UUID, \n\tversion INTEGER NOT NULL, \n\ttitle TEXT N"
        "OT NULL, \n\ttemplate_selection JSONB NOT NULL, \n\ttemplate_sna"
        "pshot JSONB NOT NULL, \n\tsource_snapshot JSONB NOT NULL, \n\tso"
        "urce_digest VARCHAR(64) NOT NULL, \n\tplan JSONB NOT NULL, \n\ts"
        "tage_assignments JSONB NOT NULL, \n\tid_plan JSONB NOT NULL, \n"
        "\trevision_reason TEXT NOT NULL, \n\tcreated_by_user_id UUID NO"
        "T NULL, \n\trequest_id UUID NOT NULL, \n\trequest_digest VARCHAR"
        "(64) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT"
        " CURRENT_TIMESTAMP NOT NULL, \n\tCONSTRAINT pk_initial_plan_ca"
        "ndidates PRIMARY KEY (id), \n\tCONSTRAINT uq_initial_plan_cand"
        "idates_scope UNIQUE (tenant_id, id), \n\tCONSTRAINT uq_initial"
        "_plan_candidates_version UNIQUE (tenant_id, series_id, versi"
        "on), \n\tCONSTRAINT uq_initial_plan_candidates_successor UNIQU"
        "E (tenant_id, supersedes_id), \n\tCONSTRAINT uq_initial_plan_c"
        "andidates_request UNIQUE (tenant_id, created_by_user_id, req"
        "uest_id), \n\tCONSTRAINT fk_initial_plan_candidates_tenant_id_"
        "initial_plan_candidates FOREIGN KEY(tenant_id, supersedes_id"
        ") REFERENCES cehub_project.initial_plan_candidates (tenant_i"
        "d, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_initial_plan_cand"
        "idates_tenant_id_development_cases FOREIGN KEY(tenant_id, ca"
        "se_id) REFERENCES cehub_project.development_cases (tenant_id"
        ", id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_initial_plan_candi"
        "dates_tenant_id_opportunities FOREIGN KEY(tenant_id, market_"
        "space_id, opportunity_id) REFERENCES cehub_product.opportuni"
        "ties (tenant_id, market_space_id, id) ON DELETE RESTRICT, \n\t"
        "CONSTRAINT fk_initial_plan_candidates_tenant_id_product_defi"
        "nitions FOREIGN KEY(tenant_id, market_space_id, definition_i"
        "d) REFERENCES cehub_product.product_definitions (tenant_id, "
        "market_space_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_ini"
        "tial_plan_candidates_tenant_id_product_nodes FOREIGN KEY(ten"
        "ant_id, market_space_id, product_line_id) REFERENCES cehub_p"
        "roduct.product_nodes (tenant_id, market_space_id, id) ON DEL"
        "ETE RESTRICT, \n\tCONSTRAINT fk_initial_plan_candidates_tenant"
        "_id_users FOREIGN KEY(tenant_id, created_by_user_id) REFEREN"
        "CES cehub_core.users (tenant_id, id) ON DELETE RESTRICT, \n\tC"
        "ONSTRAINT ck_initial_plan_candidates_initial_plan_source_sco"
        "pe CHECK (num_nonnulls(opportunity_id,definition_id,case_id)"
        "=1 AND ((case_id IS NOT NULL AND market_space_id IS NULL AND"
        " product_line_id IS NULL) OR (case_id IS NULL AND market_spa"
        "ce_id IS NOT NULL)) AND version>0)\n)\n\n"
    )
    op.execute(
        "CREATE FUNCTION cehub_project.protect_initial_plan_candidate"
        "() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catal"
        "og AS $$\nDECLARE previous cehub_project.initial_plan_candida"
        "tes%ROWTYPE;\nBEGIN\n IF TG_OP<>'INSERT' THEN RAISE EXCEPTION "
        "'Initial plan candidate revisions are immutable' USING ERRCO"
        "DE='42501'; END IF;\n IF NEW.supersedes_id IS NULL THEN\n  IF "
        "NEW.series_id<>NEW.id OR NEW.version<>1 THEN RAISE EXCEPTION"
        " 'Invalid first candidate revision' USING ERRCODE='23514'; E"
        "ND IF;\n ELSE\n  SELECT * INTO previous FROM cehub_project.ini"
        "tial_plan_candidates WHERE tenant_id=NEW.tenant_id AND id=NE"
        "W.supersedes_id FOR UPDATE;\n  IF NOT FOUND OR NEW.series_id<"
        ">previous.series_id OR NEW.version<>previous.version+1 OR RO"
        "W(NEW.market_space_id,NEW.product_line_id,NEW.opportunity_id"
        ",NEW.definition_id,NEW.case_id) IS DISTINCT FROM ROW(previou"
        "s.market_space_id,previous.product_line_id,previous.opportun"
        "ity_id,previous.definition_id,previous.case_id) THEN RAISE E"
        "XCEPTION 'Candidate revision must retain its source scope' U"
        "SING ERRCODE='23514'; END IF;\n END IF;\n IF NEW.plan->>'id' I"
        "S DISTINCT FROM NEW.id::text OR NEW.plan->>'tenant_id' IS DI"
        "STINCT FROM NEW.tenant_id::text OR (NEW.plan->>'version')::i"
        "nteger IS DISTINCT FROM NEW.version OR NEW.source_digest !~ "
        "'^[0-9a-f]{64}$' OR btrim(NEW.revision_reason)='' THEN RAISE"
        " EXCEPTION 'Candidate contract identity mismatch' USING ERRC"
        "ODE='23514'; END IF;\n RETURN NEW;\nEND $$;\nCREATE TRIGGER pro"
        "tect_initial_plan_candidate BEFORE INSERT OR UPDATE OR DELET"
        "E ON cehub_project.initial_plan_candidates FOR EACH ROW EXEC"
        "UTE FUNCTION cehub_project.protect_initial_plan_candidate();"
        "\nREVOKE ALL ON FUNCTION cehub_project.protect_initial_plan_c"
        "andidate() FROM PUBLIC;\n"
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS(SELECT 1 FROM cehub_project.initial_plan_candidates)"))
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard initial plan candidate history")
    op.drop_table("initial_plan_candidates", schema="cehub_project")
    op.execute("DROP FUNCTION cehub_project.protect_initial_plan_candidate()")
