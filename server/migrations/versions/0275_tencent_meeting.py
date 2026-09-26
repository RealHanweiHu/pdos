"""Add named Tencent meeting identities and retain provider on every conference request."""

import sqlalchemy as sa
from alembic import op

revision = "0275_tencent_meeting"
down_revision = "0274_meeting_conference_requests"
branch_labels = None
depends_on = None

DDL = (
    "\nCREATE TABLE cehub_core.tencent_meeting_bindings (\n\tid UUID NOT "
    "NULL, \n\ttenant_id UUID NOT NULL, \n\tuser_id UUID NOT NULL, \n\tversi"
    "on INTEGER NOT NULL, \n\tstatus VARCHAR(16) NOT NULL, \n\tapp_id VARC"
    "HAR(256) NOT NULL, \n\tsdk_id VARCHAR(256) NOT NULL, \n\tapplication_"
    "fingerprint VARCHAR(64) NOT NULL, \n\texternal_user_id VARCHAR(256)"
    " NOT NULL, \n\texternal_display_name VARCHAR(256) NOT NULL, \n\tactor"
    "_user_id UUID NOT NULL, \n\tactor_name VARCHAR(256) NOT NULL, \n\tevi"
    "dence TEXT NOT NULL, \n\trequest_digest VARCHAR(64) NOT NULL, \n\tcre"
    "ated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tCONSTRAINT pk_tencen"
    "t_meeting_bindings PRIMARY KEY (id), \n\tCONSTRAINT uq_tencent_bind"
    "ing_version UNIQUE (tenant_id, user_id, version), \n\tCONSTRAINT fk"
    "_tencent_binding_user FOREIGN KEY(tenant_id, user_id) REFERENCES "
    "cehub_core.users (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT"
    " fk_tencent_binding_actor FOREIGN KEY(tenant_id, actor_user_id) R"
    "EFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT, \n\t"
    "CONSTRAINT ck_tencent_meeting_bindings_state CHECK (version>0 AND"
    " status IN ('pending','active','revoked')), \n\tCONSTRAINT ck_tence"
    "nt_meeting_bindings_digests CHECK (request_digest ~ '^[0-9a-f]{64"
    "}$' AND application_fingerprint ~ '^[0-9a-f]{64}$'), \n\tCONSTRAINT"
    " ck_tencent_meeting_bindings_details CHECK (length(btrim(external"
    "_user_id))>0 AND length(btrim(external_display_name))>0 AND lengt"
    "h(btrim(evidence))>0)\n)\n\n"
)
GUARD = (
    "CREATE FUNCTION cehub_core.guard_tencent_meeting_binding() RETURN"
    "S trigger\nLANGUAGE plpgsql SET search_path=pg_catalog AS $$\nDECLA"
    "RE previous cehub_core.tencent_meeting_bindings%ROWTYPE; actor_ro"
    "le text;\nBEGIN\n IF TG_OP<>'INSERT' THEN\n  RAISE EXCEPTION 'Tencen"
    "t identity versions are immutable' USING ERRCODE='23514';\n END IF"
    ";\n PERFORM 1 FROM cehub_core.tenants WHERE id=NEW.tenant_id AND s"
    "tatus='active' FOR UPDATE;\n IF NOT FOUND THEN RAISE EXCEPTION 'Ac"
    "tive tenant required' USING ERRCODE='23514'; END IF;\n SELECT * IN"
    "TO previous FROM cehub_core.tencent_meeting_bindings\n WHERE tenan"
    "t_id=NEW.tenant_id AND user_id=NEW.user_id ORDER BY version DESC "
    "LIMIT 1;\n IF NEW.version<>COALESCE(previous.version,0)+1 THEN\n  R"
    "AISE EXCEPTION 'Sequential binding version required' USING ERRCOD"
    "E='23514';\n END IF;\n SELECT role INTO actor_role FROM cehub_core."
    "users\n WHERE tenant_id=NEW.tenant_id AND id=NEW.actor_user_id AND"
    " is_active;\n IF actor_role IS NULL OR NOT EXISTS(SELECT 1 FROM ce"
    "hub_core.users\n   WHERE tenant_id=NEW.tenant_id AND id=NEW.user_i"
    "d AND (is_active OR NEW.status='revoked')) THEN\n  RAISE EXCEPTION"
    " 'Current named actor and target required' USING ERRCODE='23514';"
    "\n END IF;\n IF NEW.status='pending' THEN\n  IF actor_role NOT IN ('"
    "owner','admin') THEN\n   RAISE EXCEPTION 'Administrator registrati"
    "on required' USING ERRCODE='23514';\n  END IF;\n ELSE\n  IF previous"
    ".id IS NULL OR previous.status='revoked'\n    OR (NEW.app_id,NEW.s"
    "dk_id,NEW.application_fingerprint,NEW.external_user_id,NEW.extern"
    "al_display_name)\n       IS DISTINCT FROM (previous.app_id,previou"
    "s.sdk_id,previous.application_fingerprint,previous.external_user_"
    "id,previous.external_display_name)\n    OR (NEW.status='active' AN"
    "D (previous.status<>'pending' OR NEW.actor_user_id<>NEW.user_id))"
    "\n    OR (NEW.status='revoked' AND NEW.actor_user_id<>NEW.user_id "
    "AND actor_role NOT IN ('owner','admin')) THEN\n   RAISE EXCEPTION "
    "'Binding requires own confirmation or authorized revocation' USIN"
    "G ERRCODE='23514';\n  END IF;\n END IF;\n IF NEW.status<>'revoked' A"
    "ND EXISTS(SELECT 1 FROM (\n     SELECT DISTINCT ON (user_id) * FRO"
    "M cehub_core.tencent_meeting_bindings\n     WHERE tenant_id=NEW.te"
    "nant_id ORDER BY user_id,version DESC\n   ) latest WHERE latest.us"
    "er_id<>NEW.user_id AND latest.app_id=NEW.app_id\n    AND latest.ex"
    "ternal_user_id=NEW.external_user_id AND latest.status IN ('pendin"
    "g','active')) THEN\n  RAISE EXCEPTION 'Enterprise user already ass"
    "igned to another person' USING ERRCODE='23514';\n END IF;\n RETURN "
    "NEW;\nEND $$;\nCREATE TRIGGER tencent_meeting_binding_guard BEFORE "
    "INSERT OR UPDATE OR DELETE\nON cehub_core.tencent_meeting_bindings"
    " FOR EACH ROW\nEXECUTE FUNCTION cehub_core.guard_tencent_meeting_b"
    "inding();\n"
)


def upgrade() -> None:
    op.execute(sa.text(DDL))
    op.execute(sa.text(GUARD))
    op.add_column(
        "meeting_conference_requests",
        sa.Column("provider", sa.String(24), nullable=False, server_default=sa.text("'dingtalk'")),
        schema="cehub_project",
    )
    op.create_check_constraint(
        op.f("ck_meeting_conference_requests_provider"),
        "meeting_conference_requests",
        "provider IN ('dingtalk','tencent_meeting')",
        schema="cehub_project",
    )
    op.create_check_constraint(
        op.f("ck_meeting_conference_requests_snapshot_provider"),
        "meeting_conference_requests",
        "COALESCE(snapshot->>'provider','dingtalk')=provider",
        schema="cehub_project",
    )


def downgrade() -> None:
    c = op.get_bind()
    if c.execute(
        sa.text(
            "SELECT EXISTS(SELECT 1 FROM cehub_core.tencent_meeting_bindings) "
            "OR EXISTS(SELECT 1 FROM cehub_project.meeting_conference_requests "
            "WHERE provider='tencent_meeting')"
        )
    ).scalar_one():
        raise RuntimeError("Tencent identity and request history must be retained")
    for name in ("snapshot_provider", "provider"):
        op.drop_constraint(
            op.f(f"ck_meeting_conference_requests_{name}"),
            "meeting_conference_requests",
            schema="cehub_project",
            type_="check",
        )
    op.drop_column("meeting_conference_requests", "provider", schema="cehub_project")
    op.execute("DROP TABLE cehub_core.tencent_meeting_bindings")
    op.execute("DROP FUNCTION cehub_core.guard_tencent_meeting_binding()")
