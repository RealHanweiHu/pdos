"""Immutable competitor observations and linear, scoped revision history."""

import sqlalchemy as sa
from alembic import op

revision = "0104_competitor_observations"
down_revision = "0103_research_subscriptions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "\nCREATE TABLE cehub_product.competitor_observations (\n\tid UU"
        "ID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tmarket_space_id UU"
        "ID NOT NULL, \n\tproduct_line_id UUID, \n\tseries_id UUID NOT NU"
        "LL, \n\tsupersedes_id UUID, \n\tversion INTEGER NOT NULL, \n\towne"
        "r_user_id UUID NOT NULL, \n\tbrand VARCHAR(256) NOT NULL, \n\tmo"
        "del VARCHAR(256) NOT NULL, \n\tvariant VARCHAR(256) NOT NULL, "
        "\n\tcompetitor_kind VARCHAR(16) NOT NULL, \n\tregion VARCHAR(128"
        ") NOT NULL, \n\tchannel VARCHAR(128) NOT NULL, \n\tconfiguration"
        " TEXT NOT NULL, \n\tlifecycle VARCHAR(16) NOT NULL, \n\tobserved"
        "_on DATE NOT NULL, \n\tidentity_sources JSONB NOT NULL, \n\tmetr"
        "ics JSONB NOT NULL, \n\tprice_quote JSONB, \n\tcertifications JS"
        "ONB DEFAULT '[]'::jsonb NOT NULL, \n\tnotes TEXT NOT NULL, \n\tr"
        "evision_reason TEXT NOT NULL, \n\trequest_id UUID NOT NULL, \n\t"
        "request_digest VARCHAR(64) NOT NULL, \n\tcreated_at TIMESTAMP "
        "WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, \n\tCONSTRA"
        "INT pk_competitor_observations PRIMARY KEY (id), \n\tCONSTRAIN"
        "T ck_competitor_observations_required_identity CHECK (versio"
        "n>0 AND btrim(brand)<>'' AND btrim(model)<>'' AND btrim(vari"
        "ant)<>'' AND btrim(configuration)<>''), \n\tCONSTRAINT ck_comp"
        "etitor_observations_classification_allowed CHECK (competitor"
        "_kind IN ('direct','indirect','emerging','substitute') AND l"
        "ifecycle IN ('unknown','announced','available','discontinued"
        "')), \n\tCONSTRAINT ck_competitor_observations_revision_shape "
        "CHECK ((version=1 AND series_id=id AND supersedes_id IS NULL"
        ") OR (version>1 AND series_id<>id AND supersedes_id IS NOT N"
        "ULL)), \n\tCONSTRAINT ck_competitor_observations_arrays CHECK "
        "(jsonb_typeof(metrics)='array' AND jsonb_array_length(metric"
        "s)>0 AND jsonb_typeof(certifications)='array'), \n\tCONSTRAINT"
        " uq_competitor_observations_space_id UNIQUE (tenant_id, mark"
        "et_space_id, id), \n\tCONSTRAINT uq_competitor_observations_ve"
        "rsion UNIQUE (tenant_id, series_id, version), \n\tCONSTRAINT u"
        "q_competitor_observations_successor UNIQUE (tenant_id, super"
        "sedes_id), \n\tCONSTRAINT uq_competitor_observations_request U"
        "NIQUE (tenant_id, market_space_id, owner_user_id, request_id"
        "), \n\tCONSTRAINT fk_competitor_observations_space FOREIGN KEY"
        "(tenant_id, market_space_id) REFERENCES cehub_product.market"
        "_spaces (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_"
        "competitor_observations_line FOREIGN KEY(tenant_id, market_s"
        "pace_id, product_line_id) REFERENCES cehub_product.product_n"
        "odes (tenant_id, market_space_id, id) ON DELETE RESTRICT, \n\t"
        "CONSTRAINT fk_competitor_observations_series FOREIGN KEY(ten"
        "ant_id, market_space_id, series_id) REFERENCES cehub_product"
        ".competitor_observations (tenant_id, market_space_id, id) ON"
        " DELETE RESTRICT, \n\tCONSTRAINT fk_competitor_observations_pr"
        "evious FOREIGN KEY(tenant_id, market_space_id, supersedes_id"
        ") REFERENCES cehub_product.competitor_observations (tenant_i"
        "d, market_space_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_"
        "competitor_observations_owner FOREIGN KEY(tenant_id, owner_u"
        "ser_id) REFERENCES cehub_core.users (tenant_id, id) ON DELET"
        "E RESTRICT\n)\n\n;"
    )
    op.execute(
        "\n    CREATE FUNCTION cehub_product.protect_competitor_observ"
        "ation() RETURNS trigger\n    LANGUAGE plpgsql SET search_path"
        "=pg_catalog AS $$\n    DECLARE previous cehub_product.competi"
        "tor_observations%ROWTYPE;\n    BEGIN\n      IF TG_OP<>'INSERT'"
        " THEN\n        RAISE EXCEPTION 'Competitor observations are i"
        "mmutable; append a revision' USING ERRCODE='42501';\n      EN"
        "D IF;\n      IF NEW.supersedes_id IS NOT NULL THEN\n        SE"
        "LECT * INTO previous FROM cehub_product.competitor_observati"
        "ons WHERE tenant_id=NEW.tenant_id AND market_space_id=NEW.ma"
        "rket_space_id AND id=NEW.supersedes_id;\n        IF NOT FOUND"
        " OR (NEW.series_id,NEW.product_line_id,NEW.brand,NEW.model,N"
        "EW.variant,NEW.version)\n          IS DISTINCT FROM (previous"
        ".series_id,previous.product_line_id,previous.brand,previous."
        "model,previous.variant,previous.version+1) THEN\n          RA"
        "ISE EXCEPTION 'Competitor revision identity or version misma"
        "tch' USING ERRCODE='23514';\n        END IF;\n      END IF;\n  "
        "    RETURN NEW;\n    END $$;\n    CREATE TRIGGER protect_compe"
        "titor_observation BEFORE INSERT OR UPDATE OR DELETE ON cehub"
        "_product.competitor_observations\n      FOR EACH ROW EXECUTE "
        "FUNCTION cehub_product.protect_competitor_observation();\n   "
        " CREATE TRIGGER protect_competitor_line_scope BEFORE INSERT "
        "ON cehub_product.competitor_observations\n      FOR EACH ROW "
        "EXECUTE FUNCTION cehub_product.protect_product_line_scope();"
        "\n    REVOKE ALL ON FUNCTION cehub_product.protect_competitor"
        "_observation() FROM PUBLIC;\n    "
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS(SELECT 1 FROM cehub_product.competitor_observations)"))
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard competitor observations")
    op.drop_table("competitor_observations", schema="cehub_product")
    op.execute("DROP FUNCTION cehub_product.protect_competitor_observation()")
