"""Product hierarchy and explicitly granted product-line work scopes.

Revision ID: 0100_product_scopes
Revises: 0099_preproject_work
"""

import sqlalchemy as sa
from alembic import op

revision = "0100_product_scopes"
down_revision = "0099_preproject_work"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "\n\nCREATE TABLE cehub_product.product_nodes (\n\tid UUID NOT NU"
        "LL, \n\ttenant_id UUID NOT NULL, \n\tmarket_space_id UUID NOT NU"
        "LL, \n\tproduct_line_id UUID NOT NULL, \n\tparent_id UUID, \n\tlev"
        "el VARCHAR(16) NOT NULL, \n\tcode VARCHAR(128) NOT NULL, \n\tnam"
        "e TEXT NOT NULL, \n\towner_user_id UUID NOT NULL, \n\tlifecycle "
        "VARCHAR(16) DEFAULT 'proposed' NOT NULL, \n\tregions JSONB DEF"
        "AULT '[]'::jsonb NOT NULL, \n\tchannels JSONB DEFAULT '[]'::js"
        "onb NOT NULL, \n\tversion INTEGER DEFAULT 1 NOT NULL, \n\treques"
        "t_id UUID NOT NULL, \n\trequest_digest VARCHAR(64) NOT NULL, \n"
        "\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTA"
        "MP NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT C"
        "URRENT_TIMESTAMP NOT NULL, \n\tCONSTRAINT pk_product_nodes PRI"
        "MARY KEY (id), \n\tCONSTRAINT ck_product_nodes_level_allowed C"
        "HECK (level IN ('line','family','platform','series','model',"
        "'variant')), \n\tCONSTRAINT ck_product_nodes_parent_shape CHEC"
        "K ((level='line' AND parent_id IS NULL AND product_line_id=i"
        "d) OR (level<>'line' AND parent_id IS NOT NULL AND parent_id"
        "<>id AND product_line_id<>id)), \n\tCONSTRAINT ck_product_node"
        "s_lifecycle_allowed CHECK (lifecycle IN ('proposed','develop"
        "ing','available','retired')), \n\tCONSTRAINT ck_product_nodes_"
        "required_content CHECK (version>0 AND btrim(code)<>'' AND bt"
        "rim(name)<>''), \n\tCONSTRAINT ck_product_nodes_arrays CHECK ("
        "jsonb_typeof(regions)='array' AND jsonb_typeof(channels)='ar"
        "ray'), \n\tCONSTRAINT uq_product_nodes_space_id UNIQUE (tenant"
        "_id, market_space_id, id), \n\tCONSTRAINT uq_product_nodes_cod"
        "e UNIQUE (tenant_id, code), \n\tCONSTRAINT uq_product_nodes_re"
        "quest UNIQUE (tenant_id, market_space_id, request_id), \n\tCON"
        "STRAINT fk_product_nodes_space FOREIGN KEY(tenant_id, market"
        "_space_id) REFERENCES cehub_product.market_spaces (tenant_id"
        ", id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_product_nodes_pare"
        "nt FOREIGN KEY(tenant_id, market_space_id, parent_id) REFERE"
        "NCES cehub_product.product_nodes (tenant_id, market_space_id"
        ", id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_product_nodes_line"
        " FOREIGN KEY(tenant_id, market_space_id, product_line_id) RE"
        "FERENCES cehub_product.product_nodes (tenant_id, market_spac"
        "e_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_product_nodes_"
        "owner FOREIGN KEY(tenant_id, owner_user_id) REFERENCES cehub"
        "_core.users (tenant_id, id) ON DELETE RESTRICT\n)\n\n;\n\nCREATE "
        "TABLE cehub_product.product_line_members (\n\ttenant_id UUID N"
        "OT NULL, \n\tmarket_space_id UUID NOT NULL, \n\tproduct_line_id "
        "UUID NOT NULL, \n\tuser_id UUID NOT NULL, \n\taccess VARCHAR(16)"
        " NOT NULL, \n\tadded_by_user_id UUID NOT NULL, \n\tcreated_at TI"
        "MESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, \n"
        "\tCONSTRAINT pk_product_line_members PRIMARY KEY (tenant_id, "
        "product_line_id, user_id), \n\tCONSTRAINT ck_product_line_memb"
        "ers_access_allowed CHECK (access IN ('viewer','contributor',"
        "'manager')), \n\tCONSTRAINT fk_product_line_members_line FOREI"
        "GN KEY(tenant_id, market_space_id, product_line_id) REFERENC"
        "ES cehub_product.product_nodes (tenant_id, market_space_id, "
        "id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_product_line_members"
        "_user FOREIGN KEY(tenant_id, user_id) REFERENCES cehub_core."
        "users (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_pr"
        "oduct_line_members_actor FOREIGN KEY(tenant_id, added_by_use"
        "r_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE "
        "RESTRICT\n)\n\n;\nALTER TABLE cehub_product.research_tasks ADD C"
        "OLUMN product_line_id UUID;\nALTER TABLE cehub_product.resear"
        "ch_tasks ADD CONSTRAINT fk_research_tasks_line FOREIGN KEY ("
        "tenant_id, market_space_id, product_line_id) REFERENCES cehu"
        "b_product.product_nodes(tenant_id,market_space_id,id) ON DEL"
        "ETE RESTRICT;\nALTER TABLE cehub_project.scoped_work_items AD"
        "D COLUMN product_line_id UUID;\nALTER TABLE cehub_project.sco"
        "ped_work_items ADD CONSTRAINT fk_scoped_work_items_line FORE"
        "IGN KEY (tenant_id, market_space_id, product_line_id) REFERE"
        "NCES cehub_product.product_nodes(tenant_id,market_space_id,i"
        "d) ON DELETE RESTRICT;\n    "
    )
    op.execute(
        "\n    CREATE FUNCTION cehub_product.protect_product_identity("
        ") RETURNS trigger\n    LANGUAGE plpgsql SET search_path=pg_ca"
        "talog AS $$\n    DECLARE parent cehub_product.product_nodes%R"
        "OWTYPE; required_level text;\n    BEGIN\n      IF TG_OP='DELET"
        "E' THEN\n        RAISE EXCEPTION 'Product identity history ca"
        "nnot be deleted' USING ERRCODE='42501';\n      END IF;\n      "
        "IF TG_OP='UPDATE' THEN\n        IF (NEW.id,NEW.tenant_id,NEW."
        "market_space_id,NEW.product_line_id,NEW.parent_id,NEW.level,"
        "NEW.code,NEW.request_id,NEW.request_digest,NEW.created_at)\n "
        "         IS DISTINCT FROM (OLD.id,OLD.tenant_id,OLD.market_s"
        "pace_id,OLD.product_line_id,OLD.parent_id,OLD.level,OLD.code"
        ",OLD.request_id,OLD.request_digest,OLD.created_at) THEN\n    "
        "      RAISE EXCEPTION 'Product identity and hierarchy are im"
        "mutable' USING ERRCODE='42501';\n        END IF;\n        IF N"
        "EW IS DISTINCT FROM OLD AND NEW.version<>OLD.version+1 THEN\n"
        "          RAISE EXCEPTION 'Product version must advance once"
        "' USING ERRCODE='22023';\n        END IF;\n      END IF;\n     "
        " IF NEW.level<>'line' THEN\n        SELECT * INTO parent FROM"
        " cehub_product.product_nodes WHERE tenant_id=NEW.tenant_id A"
        "ND market_space_id=NEW.market_space_id AND id=NEW.parent_id;"
        "\n        required_level := CASE NEW.level WHEN 'family' THEN"
        " 'line' WHEN 'platform' THEN 'family' WHEN 'series' THEN 'pl"
        "atform' WHEN 'model' THEN 'series' WHEN 'variant' THEN 'mode"
        "l' END;\n        IF NOT FOUND OR parent.level<>required_level"
        " OR parent.product_line_id<>NEW.product_line_id THEN\n       "
        "   RAISE EXCEPTION 'Product parent level or scope mismatch' "
        "USING ERRCODE='23514';\n        END IF;\n      END IF;\n      R"
        "ETURN NEW;\n    END $$;\n    CREATE TRIGGER protect_product_id"
        "entity BEFORE INSERT OR UPDATE OR DELETE ON cehub_product.pr"
        "oduct_nodes\n      FOR EACH ROW EXECUTE FUNCTION cehub_produc"
        "t.protect_product_identity();\n    REVOKE ALL ON FUNCTION ceh"
        "ub_product.protect_product_identity() FROM PUBLIC;\n\n    CREA"
        "TE FUNCTION cehub_product.protect_product_line_scope() RETUR"
        "NS trigger\n    LANGUAGE plpgsql SET search_path=pg_catalog A"
        "S $$\n    BEGIN\n      IF TG_OP='UPDATE' AND (NEW.tenant_id,NE"
        "W.market_space_id,NEW.product_line_id) IS DISTINCT FROM (OLD"
        ".tenant_id,OLD.market_space_id,OLD.product_line_id) THEN\n   "
        "     RAISE EXCEPTION 'Existing scope identity is immutable' "
        "USING ERRCODE='42501';\n      END IF;\n      IF NEW.product_li"
        "ne_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM cehub_produc"
        "t.product_nodes WHERE tenant_id=NEW.tenant_id AND market_spa"
        "ce_id=NEW.market_space_id AND id=NEW.product_line_id AND lev"
        "el='line') THEN\n        RAISE EXCEPTION 'Product line scope "
        "must reference a real line' USING ERRCODE='23514';\n      END"
        " IF;\n      RETURN NEW;\n    END $$;\n    CREATE TRIGGER protec"
        "t_research_line_scope BEFORE INSERT OR UPDATE ON cehub_produ"
        "ct.research_tasks\n      FOR EACH ROW EXECUTE FUNCTION cehub_"
        "product.protect_product_line_scope();\n    CREATE TRIGGER pro"
        "tect_work_line_scope BEFORE INSERT OR UPDATE ON cehub_projec"
        "t.scoped_work_items\n      FOR EACH ROW EXECUTE FUNCTION cehu"
        "b_product.protect_product_line_scope();\n    CREATE TRIGGER p"
        "rotect_members_line_scope BEFORE INSERT OR UPDATE ON cehub_p"
        "roduct.product_line_members\n      FOR EACH ROW EXECUTE FUNCT"
        "ION cehub_product.protect_product_line_scope();\n    REVOKE A"
        "LL ON FUNCTION cehub_product.protect_product_line_scope() FR"
        "OM PUBLIC;\n\n    CREATE FUNCTION cehub_product.protect_market"
        "_space_identity() RETURNS trigger\n    LANGUAGE plpgsql SET s"
        "earch_path=pg_catalog AS $$\n    BEGIN\n      IF TG_OP='DELETE"
        "' THEN\n        RAISE EXCEPTION 'Market space history cannot "
        "be deleted' USING ERRCODE='42501';\n      END IF;\n      IF (N"
        "EW.id,NEW.tenant_id,NEW.code,NEW.owner_user_id,NEW.request_i"
        "d,NEW.request_digest,NEW.created_at) IS DISTINCT FROM (OLD.i"
        "d,OLD.tenant_id,OLD.code,OLD.owner_user_id,OLD.request_id,OL"
        "D.request_digest,OLD.created_at) THEN\n        RAISE EXCEPTIO"
        "N 'Market space identity is immutable' USING ERRCODE='42501'"
        ";\n      END IF;\n      IF NEW IS DISTINCT FROM OLD AND NEW.ve"
        "rsion<>OLD.version+1 THEN\n        RAISE EXCEPTION 'Market sp"
        "ace version must advance once' USING ERRCODE='22023';\n      "
        "END IF;\n      RETURN NEW;\n    END $$;\n    CREATE TRIGGER pro"
        "tect_market_space_identity BEFORE UPDATE OR DELETE ON cehub_"
        "product.market_spaces\n      FOR EACH ROW EXECUTE FUNCTION ce"
        "hub_product.protect_market_space_identity();\n    REVOKE ALL "
        "ON FUNCTION cehub_product.protect_market_space_identity() FR"
        "OM PUBLIC;\n    "
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS(SELECT 1 FROM cehub_product.product_nodes)"))
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard product hierarchy or scope history")
    op.execute("DROP TRIGGER protect_market_space_identity ON cehub_product.market_spaces")
    op.execute("DROP FUNCTION cehub_product.protect_market_space_identity()")
    op.execute("DROP TRIGGER protect_research_line_scope ON cehub_product.research_tasks")
    op.execute("DROP TRIGGER protect_work_line_scope ON cehub_project.scoped_work_items")
    op.execute("DROP TRIGGER protect_members_line_scope ON cehub_product.product_line_members")
    op.execute("DROP FUNCTION cehub_product.protect_product_line_scope()")
    for schema, name in (
        ("cehub_product", "research_tasks"),
        ("cehub_project", "scoped_work_items"),
    ):
        op.drop_constraint(f"fk_{name}_line", name, schema=schema, type_="foreignkey")
        op.drop_column(name, "product_line_id", schema=schema)
    op.drop_table("product_line_members", schema="cehub_product")
    op.drop_table("product_nodes", schema="cehub_product")
    op.execute("DROP FUNCTION cehub_product.protect_product_identity()")
