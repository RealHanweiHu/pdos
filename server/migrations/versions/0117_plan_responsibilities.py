"""Immutable version-bound human plan responsibility responses."""

import sqlalchemy as sa
from alembic import op

revision = "0117_plan_responsibilities"
down_revision = "0116_plan_scenarios"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "\nCREATE TABLE cehub_project.plan_responsibility_responses (\n"
        "\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tcandidate_id"
        " UUID NOT NULL, \n\tnode_key VARCHAR(128) NOT NULL, \n\tslot VAR"
        "CHAR(16) NOT NULL, \n\tsequence INTEGER NOT NULL, \n\tprevious_r"
        "esponse_id UUID, \n\toutcome VARCHAR(32) NOT NULL, \n\treason TE"
        "XT NOT NULL, \n\tcandidate_digest VARCHAR(64) NOT NULL, \n\tacto"
        "r_user_id UUID NOT NULL, \n\trequest_id UUID NOT NULL, \n\treque"
        "st_digest VARCHAR(64) NOT NULL, \n\tcreated_at TIMESTAMP WITH "
        "TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, \n\tCONSTRAINT p"
        "k_plan_responsibility_responses PRIMARY KEY (id), \n\tCONSTRAI"
        "NT uq_plan_responsibility_responses_scope UNIQUE (tenant_id,"
        " id), \n\tCONSTRAINT uq_plan_responsibility_responses_sequence"
        " UNIQUE (tenant_id, candidate_id, sequence), \n\tCONSTRAINT uq"
        "_plan_responsibility_responses_request UNIQUE (tenant_id, ca"
        "ndidate_id, actor_user_id, request_id, node_key, slot), \n\tCO"
        "NSTRAINT fk_plan_responsibility_responses_tenant_id_initial_"
        "plan_3e9c FOREIGN KEY(tenant_id, candidate_id) REFERENCES ce"
        "hub_project.initial_plan_candidates (tenant_id, id) ON DELET"
        "E RESTRICT, \n\tCONSTRAINT fk_plan_responsibility_responses_te"
        "nant_id_plan_respons_3ab8 FOREIGN KEY(tenant_id, previous_re"
        "sponse_id) REFERENCES cehub_project.plan_responsibility_resp"
        "onses (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_pl"
        "an_responsibility_responses_tenant_id_users FOREIGN KEY(tena"
        "nt_id, actor_user_id) REFERENCES cehub_core.users (tenant_id"
        ", id) ON DELETE RESTRICT, \n\tCONSTRAINT ck_plan_responsibilit"
        "y_responses_plan_responsibility_va_0284 CHECK (sequence>0 AN"
        "D slot IN ('owner','receiver') AND outcome IN ('confirmed','"
        "changes_requested','withdrawn') AND btrim(reason)<>'')\n)\n\n"
    )
    op.execute(
        "CREATE FUNCTION cehub_project.protect_plan_responsibility_re"
        "sponse() RETURNS trigger\nLANGUAGE plpgsql SET search_path=pg"
        "_catalog AS $$\nDECLARE candidate jsonb; node jsonb; prior ce"
        "hub_project.plan_responsibility_responses%ROWTYPE; last_sequ"
        "ence integer;\nBEGIN\n IF TG_OP <> 'INSERT' THEN\n  RAISE EXCEP"
        "TION 'Responsibility responses are immutable' USING ERRCODE="
        "'42501';\n END IF;\n SELECT plan INTO candidate FROM cehub_pro"
        "ject.initial_plan_candidates\n WHERE tenant_id=NEW.tenant_id "
        "AND id=NEW.candidate_id FOR UPDATE;\n IF candidate IS NULL TH"
        "EN RAISE EXCEPTION 'Unknown candidate' USING ERRCODE='23514'"
        "; END IF;\n SELECT value INTO node FROM jsonb_array_elements("
        "candidate->'nodes') WHERE value->>'node_key'=NEW.node_key;\n "
        "IF node IS NULL OR node->>(NEW.slot || '_user_id') IS DISTIN"
        "CT FROM NEW.actor_user_id::text THEN\n  RAISE EXCEPTION 'Resp"
        "onse must belong to the actual assigned participant' USING E"
        "RRCODE='23514';\n END IF;\n SELECT * INTO prior FROM cehub_pro"
        "ject.plan_responsibility_responses\n WHERE tenant_id=NEW.tena"
        "nt_id AND candidate_id=NEW.candidate_id AND node_key=NEW.nod"
        "e_key AND slot=NEW.slot\n ORDER BY sequence DESC LIMIT 1;\n IF"
        " prior.id IS DISTINCT FROM NEW.previous_response_id THEN\n  R"
        "AISE EXCEPTION 'Responsibility response chain is stale' USIN"
        "G ERRCODE='23514';\n END IF;\n IF NEW.outcome='withdrawn' AND "
        "prior.outcome IS DISTINCT FROM 'confirmed' THEN\n  RAISE EXCE"
        "PTION 'Only a current confirmation can be withdrawn' USING E"
        "RRCODE='23514';\n END IF;\n SELECT MAX(sequence) INTO last_seq"
        "uence FROM cehub_project.plan_responsibility_responses\n WHER"
        "E tenant_id=NEW.tenant_id AND candidate_id=NEW.candidate_id;"
        "\n IF NEW.sequence <> COALESCE(last_sequence,0)+1 THEN\n  RAIS"
        "E EXCEPTION 'Responsibility sequence mismatch' USING ERRCODE"
        "='23514';\n END IF;\n RETURN NEW;\nEND $$;\nCREATE TRIGGER prote"
        "ct_plan_responsibility_response BEFORE INSERT OR UPDATE OR D"
        "ELETE\nON cehub_project.plan_responsibility_responses FOR EAC"
        "H ROW EXECUTE FUNCTION cehub_project.protect_plan_responsibi"
        "lity_response();\nREVOKE ALL ON FUNCTION cehub_project.protec"
        "t_plan_responsibility_response() FROM PUBLIC;\n"
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text("SELECT EXISTS(SELECT 1 FROM cehub_project.plan_responsibility_responses)")
        )
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard responsibility evidence")
    op.drop_table("plan_responsibility_responses", schema="cehub_project")
    op.execute("DROP FUNCTION cehub_project.protect_plan_responsibility_response()")
