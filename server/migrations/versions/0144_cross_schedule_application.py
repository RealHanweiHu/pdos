"""Independent application of bilateral approved cross-project schedule edges."""

import sqlalchemy as sa
from alembic import op

revision = "0144_cross_schedule_application"
down_revision = "0143_cross_project_schedule"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "\nCREATE TABLE cehub_project.cross_project_schedule_applicati"
        "ons (\n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tpropos"
        "al_id UUID NOT NULL, \n\tpredecessor_project_id UUID NOT NULL,"
        " \n\tsuccessor_project_id UUID NOT NULL, \n\tpredecessor_node_id"
        " UUID NOT NULL, \n\tsuccessor_node_id UUID NOT NULL, \n\trelatio"
        "n VARCHAR(2) NOT NULL, \n\treplaces_application_id UUID, \n\tact"
        "or_user_id UUID NOT NULL, \n\treason TEXT NOT NULL, \n\tapproved"
        "_payload_digest VARCHAR(64) NOT NULL, \n\trequest_id UUID NOT "
        "NULL, \n\trequest_digest VARCHAR(64) NOT NULL, \n\tcreated_at TI"
        "MESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, \n"
        "\tCONSTRAINT pk_cross_project_schedule_applications PRIMARY K"
        "EY (id), \n\tCONSTRAINT uq_cross_schedule_application_scope UN"
        "IQUE (tenant_id, id), \n\tCONSTRAINT uq_cross_schedule_applica"
        "tion_proposal UNIQUE (tenant_id, proposal_id), \n\tCONSTRAINT "
        "uq_cross_schedule_application_replacement UNIQUE (tenant_id,"
        " replaces_application_id), \n\tCONSTRAINT uq_cross_schedule_ap"
        "plication_request UNIQUE (tenant_id, actor_user_id, request_"
        "id), \n\tCONSTRAINT fk_cross_schedule_application_proposal FOR"
        "EIGN KEY(tenant_id, proposal_id) REFERENCES cehub_project.cr"
        "oss_project_schedule_proposals (tenant_id, id) ON DELETE RES"
        "TRICT, \n\tCONSTRAINT fk_cross_schedule_application_previous F"
        "OREIGN KEY(tenant_id, replaces_application_id) REFERENCES ce"
        "hub_project.cross_project_schedule_applications (tenant_id, "
        "id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_cross_schedule_appli"
        "cation_predecessor FOREIGN KEY(tenant_id, predecessor_projec"
        "t_id, predecessor_node_id) REFERENCES cehub_project.schedule"
        "_nodes (tenant_id, project_id, id) ON DELETE RESTRICT, \n\tCON"
        "STRAINT fk_cross_schedule_application_successor FOREIGN KEY("
        "tenant_id, successor_project_id, successor_node_id) REFERENC"
        "ES cehub_project.schedule_nodes (tenant_id, project_id, id) "
        "ON DELETE RESTRICT, \n\tCONSTRAINT fk_cross_project_schedule_a"
        "pplications_tenant_id_users FOREIGN KEY(tenant_id, actor_use"
        "r_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE "
        "RESTRICT, \n\tCONSTRAINT ck_cross_project_schedule_application"
        "s_cross_schedule_a_4d21 CHECK (predecessor_project_id<>succe"
        "ssor_project_id AND relation IN ('fs','ss','ff','sf') AND le"
        "ngth(btrim(reason))>0)\n)\n\n"
    )
    op.execute(
        "CREATE FUNCTION cehub_project.guard_cross_schedule_applicati"
        "on() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_cat"
        "alog AS $$\nDECLARE proposal cehub_project.cross_project_sche"
        "dule_proposals%ROWTYPE; previous uuid; side text; pid uuid; "
        "latest uuid; policy uuid;\nBEGIN\n SELECT * INTO proposal FROM"
        " cehub_project.cross_project_schedule_proposals WHERE tenant"
        "_id=NEW.tenant_id AND id=NEW.proposal_id;\n IF proposal.id IS"
        " NULL OR proposal.predecessor_project_id IS DISTINCT FROM NE"
        "W.predecessor_project_id OR proposal.successor_project_id IS"
        " DISTINCT FROM NEW.successor_project_id OR proposal.predeces"
        "sor_node_id IS DISTINCT FROM NEW.predecessor_node_id OR prop"
        "osal.successor_node_id IS DISTINCT FROM NEW.successor_node_i"
        "d OR proposal.relation IS DISTINCT FROM NEW.relation OR prop"
        "osal.payload_digest IS DISTINCT FROM NEW.approved_payload_di"
        "gest THEN RAISE EXCEPTION 'Application must match the exact "
        "bilateral approved relation' USING ERRCODE='23514'; END IF;\n"
        " PERFORM 1 FROM cehub_project.projects WHERE tenant_id=NEW.t"
        "enant_id AND id IN (NEW.predecessor_project_id,NEW.successor"
        "_project_id) ORDER BY id FOR UPDATE;\n PERFORM pg_advisory_xa"
        "ct_lock(hashtextextended('schedule-graph:'||NEW.tenant_id::t"
        "ext,0));\n IF (SELECT count(*) FROM cehub_project.cross_proje"
        "ct_schedule_decisions WHERE tenant_id=NEW.tenant_id AND prop"
        "osal_id=NEW.proposal_id AND action='approve' AND approved_pa"
        "yload_digest=NEW.approved_payload_digest AND project_id IN ("
        "NEW.predecessor_project_id,NEW.successor_project_id))<>2 THE"
        "N RAISE EXCEPTION 'Both sides must approve before independen"
        "t application' USING ERRCODE='23514'; END IF;\n FOREACH side "
        "IN ARRAY ARRAY['predecessor','successor'] LOOP\n  pid:=(to_js"
        "onb(NEW)->>(side||'_project_id'))::uuid;\n  SELECT id INTO la"
        "test FROM cehub_project.schedule_time_records WHERE tenant_i"
        "d=NEW.tenant_id AND project_id=pid AND time_kind='baseline' "
        "ORDER BY version DESC LIMIT 1;\n  SELECT id INTO policy FROM "
        "cehub_project.baseline_change_policies WHERE tenant_id=NEW.t"
        "enant_id AND project_id=pid ORDER BY version DESC LIMIT 1;\n "
        " IF latest IS DISTINCT FROM (to_jsonb(proposal)->>(side||'_b"
        "aseline_id'))::uuid OR policy IS DISTINCT FROM (to_jsonb(pro"
        "posal)->>(side||'_policy_id'))::uuid THEN RAISE EXCEPTION 'A"
        "pplication requires both approved baselines and policies sti"
        "ll current' USING ERRCODE='23514'; END IF;\n END LOOP;\n SELEC"
        "T a.id INTO previous FROM cehub_project.cross_project_schedu"
        "le_applications a WHERE a.tenant_id=NEW.tenant_id AND a.pred"
        "ecessor_node_id=NEW.predecessor_node_id AND a.successor_node"
        "_id=NEW.successor_node_id AND a.relation=NEW.relation AND NO"
        "T EXISTS(SELECT 1 FROM cehub_project.cross_project_schedule_"
        "applications newer WHERE newer.tenant_id=a.tenant_id AND new"
        "er.replaces_application_id=a.id);\n IF previous IS DISTINCT F"
        "ROM NEW.replaces_application_id THEN RAISE EXCEPTION 'Relati"
        "on replacement must bind the current application' USING ERRC"
        "ODE='23514'; END IF;\n RETURN NEW;\nEND $$;\nCREATE TRIGGER gua"
        "rd_cross_schedule_application BEFORE INSERT ON cehub_project"
        ".cross_project_schedule_applications FOR EACH ROW EXECUTE FU"
        "NCTION cehub_project.guard_cross_schedule_application();\nCRE"
        "ATE TRIGGER protect_capacity_history BEFORE UPDATE OR DELETE"
        " ON cehub_project.cross_project_schedule_applications FOR EA"
        "CH ROW EXECUTE FUNCTION cehub_project.protect_capacity_histo"
        "ry();\nREVOKE ALL ON FUNCTION cehub_project.guard_cross_sched"
        "ule_application() FROM PUBLIC;\n"
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM cehub_project.cross_project_schedule_applications)"
            )
        )
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard applied cross-project history")
    op.drop_table("cross_project_schedule_applications", schema="cehub_project")
    op.execute("DROP FUNCTION cehub_project.guard_cross_schedule_application()")
