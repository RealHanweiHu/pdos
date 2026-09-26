"""Immutable market segments, reproducible estimates and measurable outcomes."""

import sqlalchemy as sa
from alembic import op

revision = "0105_market_analysis"
down_revision = "0104_competitor_observations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "\nCREATE TABLE cehub_product.desired_outcomes (\n\tid UUID NOT "
        "NULL, \n\ttenant_id UUID NOT NULL, \n\tmarket_space_id UUID NOT "
        "NULL, \n\tproduct_line_id UUID, \n\towner_user_id UUID NOT NULL,"
        " \n\tversion INTEGER DEFAULT 1 NOT NULL, \n\tstatement TEXT NOT "
        "NULL, \n\tmetric_key VARCHAR(128) NOT NULL, \n\tunit VARCHAR(64)"
        " NOT NULL, \n\tbaseline_value NUMERIC(24, 8), \n\ttarget_value N"
        'UMERIC(24, 8), \n\tmeasurement_method TEXT NOT NULL, \n\t"window'
        "\" TEXT NOT NULL, \n\tsources JSONB DEFAULT '[]'::jsonb NOT NUL"
        "L, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIM"
        "ESTAMP NOT NULL, \n\tCONSTRAINT pk_desired_outcomes PRIMARY KE"
        "Y (id), \n\tCONSTRAINT ck_desired_outcomes_measurable_outcome "
        "CHECK (version>0 AND btrim(statement)<>'' AND btrim(metric_k"
        "ey)<>'' AND btrim(unit)<>'' AND btrim(measurement_method)<>'"
        "' AND btrim(\"window\")<>''), \n\tCONSTRAINT uq_desired_outcomes"
        "_space_id UNIQUE (tenant_id, market_space_id, id), \n\tCONSTRA"
        "INT fk_desired_outcomes_space FOREIGN KEY(tenant_id, market_"
        "space_id) REFERENCES cehub_product.market_spaces (tenant_id,"
        " id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_desired_outcomes_li"
        "ne FOREIGN KEY(tenant_id, market_space_id, product_line_id) "
        "REFERENCES cehub_product.product_nodes (tenant_id, market_sp"
        "ace_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_desired_outc"
        "omes_owner FOREIGN KEY(tenant_id, owner_user_id) REFERENCES "
        "cehub_core.users (tenant_id, id) ON DELETE RESTRICT\n)\n\n;\n\nCR"
        "EATE TABLE cehub_product.market_segments (\n\tid UUID NOT NULL"
        ", \n\ttenant_id UUID NOT NULL, \n\tmarket_space_id UUID NOT NULL"
        ", \n\tproduct_line_id UUID, \n\towner_user_id UUID NOT NULL, \n\ts"
        "eries_id UUID NOT NULL, \n\tsupersedes_id UUID, \n\tversion INTE"
        "GER NOT NULL, \n\ttitle VARCHAR(512) NOT NULL, \n\ttarget_users "
        "JSONB NOT NULL, \n\tjob_to_be_done JSONB NOT NULL, \n\tcustomer_"
        "problems JSONB NOT NULL, \n\tuse_environments JSONB NOT NULL, "
        "\n\tbuying_criteria JSONB NOT NULL, \n\tunmet_needs JSONB NOT NU"
        "LL, \n\tdesired_outcome_id UUID NOT NULL, \n\tsizing_inputs JSON"
        "B NOT NULL, \n\tsizing_result JSONB NOT NULL, \n\trevision_reaso"
        "n TEXT NOT NULL, \n\trequest_id UUID NOT NULL, \n\trequest_diges"
        "t VARCHAR(64) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZON"
        "E DEFAULT CURRENT_TIMESTAMP NOT NULL, \n\tCONSTRAINT pk_market"
        "_segments PRIMARY KEY (id), \n\tCONSTRAINT ck_market_segments_"
        "required_content CHECK (version>0 AND btrim(title)<>'' AND b"
        "trim(revision_reason)<>''), \n\tCONSTRAINT ck_market_segments_"
        "revision_shape CHECK ((version=1 AND series_id=id AND supers"
        "edes_id IS NULL) OR (version>1 AND series_id<>id AND superse"
        "des_id IS NOT NULL)), \n\tCONSTRAINT ck_market_segments_fact_a"
        "rrays CHECK (jsonb_typeof(target_users)='array' AND jsonb_ty"
        "peof(customer_problems)='array' AND jsonb_typeof(use_environ"
        "ments)='array' AND jsonb_typeof(buying_criteria)='array' AND"
        " jsonb_typeof(unmet_needs)='array'), \n\tCONSTRAINT uq_market_"
        "segments_space_id UNIQUE (tenant_id, market_space_id, id), \n"
        "\tCONSTRAINT uq_market_segments_version UNIQUE (tenant_id, se"
        "ries_id, version), \n\tCONSTRAINT uq_market_segments_successor"
        " UNIQUE (tenant_id, supersedes_id), \n\tCONSTRAINT uq_market_s"
        "egments_request UNIQUE (tenant_id, market_space_id, owner_us"
        "er_id, request_id), \n\tCONSTRAINT fk_market_segments_space FO"
        "REIGN KEY(tenant_id, market_space_id) REFERENCES cehub_produ"
        "ct.market_spaces (tenant_id, id) ON DELETE RESTRICT, \n\tCONST"
        "RAINT fk_market_segments_line FOREIGN KEY(tenant_id, market_"
        "space_id, product_line_id) REFERENCES cehub_product.product_"
        "nodes (tenant_id, market_space_id, id) ON DELETE RESTRICT, \n"
        "\tCONSTRAINT fk_market_segments_series FOREIGN KEY(tenant_id,"
        " market_space_id, series_id) REFERENCES cehub_product.market"
        "_segments (tenant_id, market_space_id, id) ON DELETE RESTRIC"
        "T, \n\tCONSTRAINT fk_market_segments_previous FOREIGN KEY(tena"
        "nt_id, market_space_id, supersedes_id) REFERENCES cehub_prod"
        "uct.market_segments (tenant_id, market_space_id, id) ON DELE"
        "TE RESTRICT, \n\tCONSTRAINT fk_market_segments_outcome FOREIGN"
        " KEY(tenant_id, market_space_id, desired_outcome_id) REFEREN"
        "CES cehub_product.desired_outcomes (tenant_id, market_space_"
        "id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_market_segments_"
        "owner FOREIGN KEY(tenant_id, owner_user_id) REFERENCES cehub"
        "_core.users (tenant_id, id) ON DELETE RESTRICT\n)\n\n;"
    )
    op.execute(
        "\n    CREATE FUNCTION cehub_product.protect_market_analysis()"
        " RETURNS trigger\n    LANGUAGE plpgsql SET search_path=pg_cat"
        "alog AS $$\n    DECLARE previous cehub_product.market_segment"
        "s%ROWTYPE; outcome_line uuid;\n    BEGIN\n      IF TG_OP<>'INS"
        "ERT' THEN\n        RAISE EXCEPTION 'Market analyses are immut"
        "able; append a revision' USING ERRCODE='42501';\n      END IF"
        ";\n      SELECT product_line_id INTO outcome_line FROM cehub_"
        "product.desired_outcomes WHERE tenant_id=NEW.tenant_id AND m"
        "arket_space_id=NEW.market_space_id AND id=NEW.desired_outcom"
        "e_id;\n      IF NOT FOUND OR NEW.product_line_id IS DISTINCT "
        "FROM outcome_line THEN\n        RAISE EXCEPTION 'Outcome scop"
        "e differs from segment' USING ERRCODE='23514';\n      END IF;"
        "\n      IF NEW.supersedes_id IS NOT NULL THEN\n        SELECT "
        "* INTO previous FROM cehub_product.market_segments WHERE ten"
        "ant_id=NEW.tenant_id AND market_space_id=NEW.market_space_id"
        " AND id=NEW.supersedes_id;\n        IF NOT FOUND OR (NEW.seri"
        "es_id,NEW.product_line_id,NEW.version) IS DISTINCT FROM (pre"
        "vious.series_id,previous.product_line_id,previous.version+1)"
        " THEN\n          RAISE EXCEPTION 'Market analysis revision mi"
        "smatch' USING ERRCODE='23514';\n        END IF;\n      END IF;"
        "\n      RETURN NEW;\n    END $$;\n    CREATE FUNCTION cehub_pro"
        "duct.protect_desired_outcome() RETURNS trigger\n    LANGUAGE "
        "plpgsql SET search_path=pg_catalog AS $$\n    BEGIN\n      RAI"
        "SE EXCEPTION 'Referenced outcomes are immutable; create a ne"
        "w version' USING ERRCODE='42501';\n    END $$;\n    CREATE TRI"
        "GGER protect_desired_outcome BEFORE UPDATE OR DELETE ON cehu"
        "b_product.desired_outcomes\n      FOR EACH ROW EXECUTE FUNCTI"
        "ON cehub_product.protect_desired_outcome();\n    CREATE TRIGG"
        "ER protect_market_analysis BEFORE INSERT OR UPDATE OR DELETE"
        " ON cehub_product.market_segments\n      FOR EACH ROW EXECUTE"
        " FUNCTION cehub_product.protect_market_analysis();\n    CREAT"
        "E TRIGGER protect_outcome_line_scope BEFORE INSERT ON cehub_"
        "product.desired_outcomes\n      FOR EACH ROW EXECUTE FUNCTION"
        " cehub_product.protect_product_line_scope();\n    CREATE TRIG"
        "GER protect_segment_line_scope BEFORE INSERT ON cehub_produc"
        "t.market_segments\n      FOR EACH ROW EXECUTE FUNCTION cehub_"
        "product.protect_product_line_scope();\n    REVOKE ALL ON FUNC"
        "TION cehub_product.protect_market_analysis() FROM PUBLIC;\n  "
        "  REVOKE ALL ON FUNCTION cehub_product.protect_desired_outco"
        "me() FROM PUBLIC;\n    "
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM cehub_product.market_segments) O"
                "R EXISTS(SELECT 1 FROM cehub_product.desired_outcomes)"
            )
        )
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard market analysis and outcome history")
    op.drop_table("market_segments", schema="cehub_product")
    op.drop_table("desired_outcomes", schema="cehub_product")
    op.execute("DROP FUNCTION cehub_product.protect_market_analysis()")
    op.execute("DROP FUNCTION cehub_product.protect_desired_outcome()")
