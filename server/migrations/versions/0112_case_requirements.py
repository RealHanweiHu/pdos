"""Append-only Case requirement relations with legacy primary compatibility."""

import sqlalchemy as sa
from alembic import op

revision = "0112_case_requirements"
down_revision = "0111_definition_intake"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "\nCREATE TABLE cehub_project.case_requirement_links (\n\tid UUI"
        "D NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tcase_id UUID NOT NU"
        "LL, \n\trequirement_id UUID NOT NULL, \n\tprevious_id UUID, \n\tse"
        "quence INTEGER NOT NULL, \n\taction VARCHAR(16) NOT NULL, \n\tre"
        "quirement_snapshot JSONB NOT NULL, \n\trequirement_digest VARC"
        "HAR(64) NOT NULL, \n\trationale TEXT NOT NULL, \n\tactor_user_id"
        " UUID NOT NULL, \n\trequest_id UUID NOT NULL, \n\trequest_digest"
        " VARCHAR(64) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE"
        " DEFAULT CURRENT_TIMESTAMP NOT NULL, \n\tCONSTRAINT pk_case_re"
        "quirement_links PRIMARY KEY (id), \n\tCONSTRAINT uq_case_requi"
        "rement_links_scope UNIQUE (tenant_id, case_id, id), \n\tCONSTR"
        "AINT uq_case_requirement_links_sequence UNIQUE (tenant_id, c"
        "ase_id, sequence), \n\tCONSTRAINT uq_case_requirement_links_re"
        "quest UNIQUE (tenant_id, case_id, actor_user_id, request_id)"
        ", \n\tCONSTRAINT fk_case_requirement_links_tenant_id_developme"
        "nt_cases FOREIGN KEY(tenant_id, case_id) REFERENCES cehub_pr"
        "oject.development_cases (tenant_id, id) ON DELETE RESTRICT, "
        "\n\tCONSTRAINT fk_case_requirement_links_tenant_id_requirement"
        "s FOREIGN KEY(tenant_id, requirement_id) REFERENCES cehub_pr"
        "oject.requirements (tenant_id, id) ON DELETE RESTRICT, \n\tCON"
        "STRAINT fk_case_requirement_links_tenant_id_case_requirement"
        "_links FOREIGN KEY(tenant_id, case_id, previous_id) REFERENC"
        "ES cehub_project.case_requirement_links (tenant_id, case_id,"
        " id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_case_requirement_li"
        "nks_tenant_id_users FOREIGN KEY(tenant_id, actor_user_id) RE"
        "FERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT"
        ", \n\tCONSTRAINT ck_case_requirement_links_valid_case_link_act"
        "ion CHECK (sequence>0 AND action IN ('attach','refresh','rel"
        "ease') AND btrim(rationale)<>''), \n\tCONSTRAINT ck_case_requi"
        "rement_links_valid_case_link_snapshot CHECK (jsonb_typeof(re"
        "quirement_snapshot)='object' AND requirement_digest ~ '^[0-9"
        "a-f]{64}$' AND request_digest ~ '^[0-9a-f]{64}$')\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_case_requirement_links_requirement ON cehub_"
        "project.case_requirement_links (tenant_id, requirement_id, c"
        "ase_id)"
    )
    op.execute(
        "CREATE FUNCTION cehub_project.protect_case_requirement_link("
        ") RETURNS trigger\nLANGUAGE plpgsql SET search_path=pg_catalo"
        "g AS $$\nDECLARE target cehub_project.development_cases%ROWTY"
        "PE; latest cehub_project.case_requirement_links%ROWTYPE; pri"
        "or_action text; active boolean;\nBEGIN\n IF TG_OP <> 'INSERT' "
        "THEN RAISE EXCEPTION 'Case requirement history is immutable'"
        " USING ERRCODE='42501'; END IF;\n SELECT * INTO target FROM c"
        "ehub_project.development_cases WHERE tenant_id=NEW.tenant_id"
        " AND id=NEW.case_id FOR UPDATE;\n IF NOT FOUND OR target.stat"
        "us NOT IN ('draft','evaluating') THEN RAISE EXCEPTION 'Case "
        "requirement scope is frozen' USING ERRCODE='23514'; END IF;\n"
        " SELECT * INTO latest FROM cehub_project.case_requirement_li"
        "nks WHERE tenant_id=NEW.tenant_id AND case_id=NEW.case_id OR"
        "DER BY sequence DESC LIMIT 1;\n IF NEW.previous_id IS DISTINC"
        "T FROM latest.id OR NEW.sequence <> COALESCE(latest.sequence"
        ",0)+1 THEN RAISE EXCEPTION 'Case requirement chain changed' "
        "USING ERRCODE='23514'; END IF;\n SELECT action INTO prior_act"
        "ion FROM cehub_project.case_requirement_links WHERE tenant_i"
        "d=NEW.tenant_id AND case_id=NEW.case_id AND requirement_id=N"
        "EW.requirement_id ORDER BY sequence DESC LIMIT 1;\n active :="
        " NEW.requirement_id=target.requirement_id OR COALESCE(prior_"
        "action <> 'release',false);\n IF (NEW.action='attach' AND act"
        "ive) OR (NEW.action IN ('refresh','release') AND NOT active)"
        " OR (NEW.action='release' AND NEW.requirement_id=target.requ"
        "irement_id) THEN RAISE EXCEPTION 'Invalid requirement relati"
        "on transition' USING ERRCODE='23514'; END IF;\n IF NEW.requir"
        "ement_snapshot->>'id' IS DISTINCT FROM NEW.requirement_id::t"
        "ext OR NEW.requirement_snapshot->>'tenant_id' IS DISTINCT FR"
        "OM NEW.tenant_id::text THEN RAISE EXCEPTION 'Requirement sna"
        "pshot scope mismatch' USING ERRCODE='23514'; END IF;\n RETURN"
        " NEW;\nEND $$;\nCREATE TRIGGER protect_case_requirement_link B"
        "EFORE INSERT OR UPDATE OR DELETE ON cehub_project.case_requi"
        "rement_links FOR EACH ROW EXECUTE FUNCTION cehub_project.pro"
        "tect_case_requirement_link();\nREVOKE ALL ON FUNCTION cehub_p"
        "roject.protect_case_requirement_link() FROM PUBLIC;\n"
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS(SELECT 1 FROM cehub_project.case_requirement_links)"))
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard Case requirement history")
    op.drop_table("case_requirement_links", schema="cehub_project")
    op.execute("DROP FUNCTION cehub_project.protect_case_requirement_link()")
