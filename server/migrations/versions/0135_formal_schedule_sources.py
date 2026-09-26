"""Authoritative applied baseline provenance for shared formal schedule readers."""

import sqlalchemy as sa
from alembic import op

revision = "0135_formal_schedule_sources"
down_revision = "0134_baseline_change_approval"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "\nCREATE TABLE cehub_project.baseline_change_applications (\n\t"
        "id UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tproject_id UU"
        "ID NOT NULL, \n\tchange_id UUID NOT NULL, \n\tdecision_id UUID N"
        "OT NULL, \n\tbaseline_id UUID NOT NULL, \n\tprevious_baseline_id"
        " UUID NOT NULL, \n\tscenario_id UUID NOT NULL, \n\tactor_user_id"
        " UUID NOT NULL, \n\treceipt JSONB NOT NULL, \n\trequest_id UUID "
        "NOT NULL, \n\trequest_digest VARCHAR(64) NOT NULL, \n\tcreated_a"
        "t TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NUL"
        "L, \n\tCONSTRAINT pk_baseline_change_applications PRIMARY KEY "
        "(id), \n\tCONSTRAINT uq_baseline_application_scope UNIQUE (ten"
        "ant_id, project_id, id), \n\tCONSTRAINT uq_baseline_applicatio"
        "n_change UNIQUE (tenant_id, change_id), \n\tCONSTRAINT uq_base"
        "line_application_version UNIQUE (tenant_id, baseline_id), \n\t"
        "CONSTRAINT uq_baseline_application_request UNIQUE (tenant_id"
        ", actor_user_id, request_id), \n\tCONSTRAINT fk_baseline_appli"
        "cation_change FOREIGN KEY(tenant_id, project_id, change_id) "
        "REFERENCES cehub_project.baseline_change_requests (tenant_id"
        ", project_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_baseli"
        "ne_application_decision FOREIGN KEY(tenant_id, project_id, d"
        "ecision_id) REFERENCES cehub_project.baseline_change_decisio"
        "ns (tenant_id, project_id, id) ON DELETE RESTRICT, \n\tCONSTRA"
        "INT fk_baseline_application_new FOREIGN KEY(tenant_id, proje"
        "ct_id, baseline_id) REFERENCES cehub_project.schedule_time_r"
        "ecords (tenant_id, project_id, id) ON DELETE RESTRICT, \n\tCON"
        "STRAINT fk_baseline_application_previous FOREIGN KEY(tenant_"
        "id, project_id, previous_baseline_id) REFERENCES cehub_proje"
        "ct.schedule_time_records (tenant_id, project_id, id) ON DELE"
        "TE RESTRICT, \n\tCONSTRAINT fk_baseline_application_scenario F"
        "OREIGN KEY(tenant_id, project_id, scenario_id) REFERENCES ce"
        "hub_project.project_schedule_scenarios (tenant_id, project_i"
        "d, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_baseline_applicat"
        "ion_actor FOREIGN KEY(tenant_id, actor_user_id) REFERENCES c"
        "ehub_core.users (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTR"
        "AINT ck_baseline_change_applications_baseline_application_re"
        "ceipt CHECK (baseline_id<>previous_baseline_id AND jsonb_typ"
        "eof(receipt)='object')\n)\n\n"
    )
    op.execute(
        "CREATE FUNCTION cehub_project.guard_baseline_change_applicat"
        "ion() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_ca"
        "talog AS $$\nBEGIN\n IF NOT EXISTS(SELECT 1 FROM cehub_project"
        ".baseline_change_requests q JOIN cehub_project.baseline_chan"
        "ge_decisions d ON d.tenant_id=q.tenant_id AND d.project_id=q"
        ".project_id AND d.change_id=q.id JOIN cehub_project.schedule"
        "_time_records old ON old.tenant_id=q.tenant_id AND old.proje"
        "ct_id=q.project_id AND old.id=q.base_baseline_id JOIN cehub_"
        "project.schedule_time_records next ON next.tenant_id=q.tenan"
        "t_id AND next.project_id=q.project_id AND next.id=NEW.baseli"
        "ne_id WHERE q.tenant_id=NEW.tenant_id AND q.project_id=NEW.p"
        "roject_id AND q.id=NEW.change_id AND q.scenario_id=NEW.scena"
        "rio_id AND old.id=NEW.previous_baseline_id AND old.time_kind"
        "='baseline' AND next.time_kind='baseline' AND next.version=o"
        "ld.version+1 AND d.id=NEW.decision_id AND d.action='approve'"
        " AND d.approved_payload_digest=q.payload_digest AND next.con"
        "tract->'approval'->>'approval_record_id'=d.id::text AND next"
        ".contract->'approval'->>'payload_digest'=q.payload_digest) T"
        "HEN RAISE EXCEPTION 'Baseline application must link exact ap"
        "proved change and consecutive versions' USING ERRCODE='23514"
        "'; END IF;\n RETURN NEW;\nEND $$;\nCREATE TRIGGER guard_baselin"
        "e_change_application BEFORE INSERT ON cehub_project.baseline"
        "_change_applications FOR EACH ROW EXECUTE FUNCTION cehub_pro"
        "ject.guard_baseline_change_application();\nCREATE TRIGGER pro"
        "tect_capacity_history BEFORE UPDATE OR DELETE ON cehub_proje"
        "ct.baseline_change_applications FOR EACH ROW EXECUTE FUNCTIO"
        "N cehub_project.protect_capacity_history();\nREVOKE ALL ON FU"
        "NCTION cehub_project.guard_baseline_change_application() FRO"
        "M PUBLIC;\n"
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS(SELECT 1 FROM cehub_project.baseline_change_applications)"))
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard applied baseline provenance")
    op.drop_table("baseline_change_applications", schema="cehub_project")
    op.execute("DROP FUNCTION cehub_project.guard_baseline_change_application()")
