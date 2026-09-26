"""Immutable plan review basis and independent named acceptance receipts."""

import sqlalchemy as sa
from alembic import op

revision = "0121_initial_plan_reviews"
down_revision = "0120_legacy_resource_inventory"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "\nCREATE TABLE cehub_project.initial_plan_reviews (\n\tid UUID "
        "NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tcandidate_id UUID NOT"
        " NULL, \n\tscenario_id UUID NOT NULL, \n\tcapacity_check_id UUID"
        " NOT NULL, \n\tround_no INTEGER NOT NULL, \n\tversion INTEGER NO"
        "T NULL, \n\tstate VARCHAR(24) NOT NULL, \n\treviewer_user_id UUI"
        "D NOT NULL, \n\tsnapshot JSONB NOT NULL, \n\tbasis_digest VARCHA"
        "R(64) NOT NULL, \n\tpreparation_reason TEXT NOT NULL, \n\toutcom"
        "e_reason TEXT, \n\tapproval JSONB, \n\tcreated_by_user_id UUID N"
        "OT NULL, \n\trequest_id UUID NOT NULL, \n\trequest_digest VARCHA"
        "R(64) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAUL"
        "T CURRENT_TIMESTAMP NOT NULL, \n\tupdated_at TIMESTAMP WITH TI"
        "ME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, \n\tCONSTRAINT pk_"
        "initial_plan_reviews PRIMARY KEY (id), \n\tCONSTRAINT uq_initi"
        "al_plan_reviews_scope UNIQUE (tenant_id, id), \n\tCONSTRAINT u"
        "q_initial_plan_reviews_round UNIQUE (tenant_id, candidate_id"
        ", round_no), \n\tCONSTRAINT uq_initial_plan_reviews_request UN"
        "IQUE (tenant_id, created_by_user_id, request_id), \n\tCONSTRAI"
        "NT fk_initial_plan_reviews_tenant_id_initial_plan_candidates"
        " FOREIGN KEY(tenant_id, candidate_id) REFERENCES cehub_proje"
        "ct.initial_plan_candidates (tenant_id, id) ON DELETE RESTRIC"
        "T, \n\tCONSTRAINT fk_initial_plan_reviews_tenant_id_initial_pl"
        "an_scenarios FOREIGN KEY(tenant_id, scenario_id) REFERENCES "
        "cehub_project.initial_plan_scenarios (tenant_id, id) ON DELE"
        "TE RESTRICT, \n\tCONSTRAINT fk_initial_plan_reviews_tenant_id_"
        "plan_capacity_checks FOREIGN KEY(tenant_id, capacity_check_i"
        "d) REFERENCES cehub_project.plan_capacity_checks (tenant_id,"
        " id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_initial_plan_review"
        "s_reviewer_user_id FOREIGN KEY(tenant_id, reviewer_user_id) "
        "REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRI"
        "CT, \n\tCONSTRAINT fk_initial_plan_reviews_created_by_user_id "
        "FOREIGN KEY(tenant_id, created_by_user_id) REFERENCES cehub_"
        "core.users (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT "
        "ck_initial_plan_reviews_initial_plan_review_state CHECK (rou"
        "nd_no>0 AND version>0 AND state IN ('pending_review','accept"
        "ed','rejected','withdrawn') AND btrim(preparation_reason)<>'"
        "' AND (state='pending_review' OR (outcome_reason IS NOT NULL"
        " AND btrim(outcome_reason)<>'')) AND (state<>'accepted' OR ("
        "approval IS NOT NULL AND approval<>'null'::jsonb)))\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE cehub_project.initial_plan_review_receipts (\n\t"
        "id UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\treview_id UUI"
        "D NOT NULL, \n\tactor_user_id UUID NOT NULL, \n\trequest_id UUID"
        " NOT NULL, \n\trequest_digest VARCHAR(64) NOT NULL, \n\tsnapshot"
        " JSONB NOT NULL, \n\treason TEXT NOT NULL, \n\tcreated_at TIMEST"
        "AMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, \n\tCON"
        "STRAINT pk_initial_plan_review_receipts PRIMARY KEY (id), \n\t"
        "CONSTRAINT uq_initial_plan_review_receipts_request UNIQUE (t"
        "enant_id, actor_user_id, request_id), \n\tCONSTRAINT fk_initia"
        "l_plan_review_receipts_tenant_id_initial_plan_reviews FOREIG"
        "N KEY(tenant_id, review_id) REFERENCES cehub_project.initial"
        "_plan_reviews (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAI"
        "NT fk_initial_plan_review_receipts_tenant_id_users FOREIGN K"
        "EY(tenant_id, actor_user_id) REFERENCES cehub_core.users (te"
        "nant_id, id) ON DELETE RESTRICT\n)\n\n"
    )
    op.execute(
        "CREATE FUNCTION cehub_project.guard_initial_plan_review() RE"
        "TURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS"
        " $$\nDECLARE latest integer;\nBEGIN\n IF TG_OP='DELETE' THEN RA"
        "ISE EXCEPTION 'Plan review history cannot be deleted' USING "
        "ERRCODE='42501'; END IF;\n PERFORM 1 FROM cehub_project.initi"
        "al_plan_candidates WHERE tenant_id=NEW.tenant_id AND id=NEW."
        "candidate_id FOR UPDATE;\n IF TG_OP='INSERT' THEN\n  SELECT MA"
        "X(round_no) INTO latest FROM cehub_project.initial_plan_revi"
        "ews WHERE tenant_id=NEW.tenant_id AND candidate_id=NEW.candi"
        "date_id;\n  IF NEW.state<>'pending_review' OR NEW.version<>1 "
        "OR NEW.round_no<>COALESCE(latest,0)+1 OR NEW.approval IS NOT"
        " NULL OR NOT EXISTS(SELECT 1 FROM cehub_project.initial_plan"
        "_scenarios s JOIN cehub_project.plan_capacity_checks c ON c."
        "tenant_id=s.tenant_id AND c.scenario_id=s.id WHERE s.tenant_"
        "id=NEW.tenant_id AND s.candidate_id=NEW.candidate_id AND s.i"
        "d=NEW.scenario_id AND c.id=NEW.capacity_check_id) THEN RAISE"
        " EXCEPTION 'Invalid plan review basis chain' USING ERRCODE='"
        "23514'; END IF;\n ELSE\n  IF (to_jsonb(NEW)-ARRAY['state','ver"
        "sion','outcome_reason','approval','updated_at']) IS DISTINCT"
        " FROM (to_jsonb(OLD)-ARRAY['state','version','outcome_reason"
        "','approval','updated_at']) OR NEW.version<>OLD.version+1 OR"
        " NOT ((OLD.state='pending_review' AND NEW.state IN ('accepte"
        "d','rejected','withdrawn')) OR (OLD.state='accepted' AND NEW"
        ".state='withdrawn')) THEN RAISE EXCEPTION 'Plan review conte"
        "nt is immutable' USING ERRCODE='23514'; END IF;\n  IF OLD.sta"
        "te='accepted' AND NEW.approval IS DISTINCT FROM OLD.approval"
        " THEN RAISE EXCEPTION 'Accepted plan approval must remain in"
        " history' USING ERRCODE='23514'; END IF;\n END IF;\n IF NEW.st"
        "ate='accepted' THEN\n  IF NEW.approval->>'approved_by_user_id"
        "' IS DISTINCT FROM NEW.reviewer_user_id::text OR NEW.approva"
        "l->>'payload_digest' IS DISTINCT FROM NEW.basis_digest OR js"
        "onb_array_length(NEW.snapshot->'blockers') IS DISTINCT FROM "
        "0 OR EXISTS(SELECT 1 FROM cehub_project.initial_plan_reviews"
        " WHERE tenant_id=NEW.tenant_id AND candidate_id=NEW.candidat"
        "e_id AND round_no>NEW.round_no) THEN RAISE EXCEPTION 'Plan a"
        "cceptance requires the named reviewer and ready current roun"
        "d' USING ERRCODE='23514'; END IF;\n END IF;\n RETURN NEW;\nEND "
        "$$;\nCREATE TRIGGER guard_initial_plan_review BEFORE INSERT O"
        "R UPDATE OR DELETE ON cehub_project.initial_plan_reviews FOR"
        " EACH ROW EXECUTE FUNCTION cehub_project.guard_initial_plan_"
        "review();\nCREATE TRIGGER protect_capacity_history BEFORE UPD"
        "ATE OR DELETE ON cehub_project.initial_plan_review_receipts "
        "FOR EACH ROW EXECUTE FUNCTION cehub_project.protect_capacity"
        "_history();\nREVOKE ALL ON FUNCTION cehub_project.guard_initi"
        "al_plan_review() FROM PUBLIC;\n"
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS(SELECT 1 FROM cehub_project.initial_plan_reviews)"))
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard plan review evidence")
    op.drop_table("initial_plan_review_receipts", schema="cehub_project")
    op.drop_table("initial_plan_reviews", schema="cehub_project")
    op.execute("DROP FUNCTION cehub_project.guard_initial_plan_review()")
