"""Durable scope-bound research search observations."""

import sqlalchemy as sa
from alembic import op

revision = "0102_research_searches"
down_revision = "0101_evidence_bodies"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "\nCREATE TABLE cehub_product.research_searches (\n\tid UUID NOT"
        " NULL, \n\ttenant_id UUID NOT NULL, \n\tmarket_space_id UUID NOT"
        " NULL, \n\tproduct_line_id UUID, \n\trequested_by_user_id UUID N"
        "OT NULL, \n\trequest_id UUID NOT NULL, \n\trequest_digest VARCHA"
        "R(64) NOT NULL, \n\tquery TEXT NOT NULL, \n\tlanguage VARCHAR(16"
        ") NOT NULL, \n\ttime_range VARCHAR(8), \n\tresult_limit INTEGER "
        "NOT NULL, \n\tprovider_key VARCHAR(32) NOT NULL, \n\tprovider_pr"
        "otocol_version VARCHAR(64) NOT NULL, \n\tprovider_endpoint_dig"
        "est VARCHAR(64), \n\tresponse_digest VARCHAR(64), \n\tstatus VAR"
        "CHAR(24) NOT NULL, \n\thits JSONB DEFAULT '[]'::jsonb NOT NULL"
        ", \n\twarnings JSONB DEFAULT '[]'::jsonb NOT NULL, \n\terror_cod"
        "e VARCHAR(64), \n\terror_message TEXT, \n\tstarted_at TIMESTAMP "
        "WITH TIME ZONE NOT NULL, \n\tfinished_at TIMESTAMP WITH TIME Z"
        "ONE, \n\tversion INTEGER DEFAULT 1 NOT NULL, \n\tCONSTRAINT pk_r"
        "esearch_searches PRIMARY KEY (id), \n\tCONSTRAINT ck_research_"
        "searches_status_allowed CHECK (status IN ('running','complet"
        "ed','partial','no_results','unavailable','not_configured','f"
        "ailed','denied')), \n\tCONSTRAINT ck_research_searches_require"
        "d_content CHECK (btrim(query)<>'' AND result_limit BETWEEN 1"
        " AND 10 AND version>0), \n\tCONSTRAINT ck_research_searches_ar"
        "rays CHECK (jsonb_typeof(hits)='array' AND jsonb_typeof(warn"
        "ings)='array'), \n\tCONSTRAINT ck_research_searches_finish_sta"
        "te CHECK ((status='running')=(finished_at IS NULL)), \n\tCONST"
        "RAINT uq_research_searches_request UNIQUE (tenant_id, market"
        "_space_id, requested_by_user_id, request_id), \n\tCONSTRAINT f"
        "k_research_searches_space FOREIGN KEY(tenant_id, market_spac"
        "e_id) REFERENCES cehub_product.market_spaces (tenant_id, id)"
        " ON DELETE RESTRICT, \n\tCONSTRAINT fk_research_searches_line "
        "FOREIGN KEY(tenant_id, market_space_id, product_line_id) REF"
        "ERENCES cehub_product.product_nodes (tenant_id, market_space"
        "_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_research_search"
        "es_requester FOREIGN KEY(tenant_id, requested_by_user_id) RE"
        "FERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT"
        "\n)\n\n;"
    )
    op.execute(
        "\n    CREATE FUNCTION cehub_product.protect_research_search()"
        " RETURNS trigger\n    LANGUAGE plpgsql SET search_path=pg_cat"
        "alog AS $$\n    BEGIN\n      IF TG_OP='DELETE' THEN\n        RA"
        "ISE EXCEPTION 'Search observations cannot be deleted' USING "
        "ERRCODE='42501';\n      END IF;\n      IF OLD.status<>'running"
        "' AND NEW IS DISTINCT FROM OLD THEN\n        RAISE EXCEPTION "
        "'Completed search observation is immutable' USING ERRCODE='4"
        "2501';\n      END IF;\n      IF (NEW.id,NEW.tenant_id,NEW.mark"
        "et_space_id,NEW.product_line_id,NEW.requested_by_user_id,NEW"
        ".request_id,NEW.request_digest,NEW.query,NEW.language,NEW.ti"
        "me_range,NEW.result_limit,NEW.provider_key,NEW.provider_prot"
        "ocol_version,NEW.provider_endpoint_digest,NEW.started_at)\n  "
        "      IS DISTINCT FROM (OLD.id,OLD.tenant_id,OLD.market_spac"
        "e_id,OLD.product_line_id,OLD.requested_by_user_id,OLD.reques"
        "t_id,OLD.request_digest,OLD.query,OLD.language,OLD.time_rang"
        "e,OLD.result_limit,OLD.provider_key,OLD.provider_protocol_ve"
        "rsion,OLD.provider_endpoint_digest,OLD.started_at) THEN\n    "
        "    RAISE EXCEPTION 'Search request and provider identity ar"
        "e immutable' USING ERRCODE='42501';\n      END IF;\n      IF N"
        "EW IS DISTINCT FROM OLD AND NEW.version<>OLD.version+1 THEN\n"
        "        RAISE EXCEPTION 'Search version must advance once' U"
        "SING ERRCODE='22023';\n      END IF;\n      RETURN NEW;\n    EN"
        "D $$;\n    CREATE TRIGGER protect_research_search BEFORE UPDA"
        "TE OR DELETE ON cehub_product.research_searches\n      FOR EA"
        "CH ROW EXECUTE FUNCTION cehub_product.protect_research_searc"
        "h();\n    CREATE TRIGGER protect_search_line_scope BEFORE INS"
        "ERT OR UPDATE ON cehub_product.research_searches\n      FOR E"
        "ACH ROW EXECUTE FUNCTION cehub_product.protect_product_line_"
        "scope();\n    REVOKE ALL ON FUNCTION cehub_product.protect_re"
        "search_search() FROM PUBLIC;\n    "
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS(SELECT 1 FROM cehub_product.research_searches)"))
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard research search history")
    op.drop_table("research_searches", schema="cehub_product")
    op.execute("DROP FUNCTION cehub_product.protect_research_search()")
