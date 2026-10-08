"""One category identity and permission source; old space/line are compatibility names."""

# ruff: noqa: E501
from alembic import op
from sqlalchemy import text

revision = "0426_unified_categories"
down_revision = "0425_category_foundation"
branch_labels = None
depends_on = None

FUNCTIONS = """
CREATE FUNCTION cehub_product.sync_category_identity() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE n cehub_product.product_nodes%ROWTYPE; target_lifecycle text;
BEGIN
 target_lifecycle := CASE NEW.lifecycle WHEN 'active' THEN 'available' WHEN 'archived' THEN 'retired' ELSE 'proposed' END;
 SELECT * INTO n FROM cehub_product.product_nodes WHERE tenant_id=NEW.tenant_id AND market_space_id=NEW.id AND level='line';
 IF NOT FOUND THEN
  INSERT INTO cehub_product.product_nodes(id,tenant_id,market_space_id,product_line_id,level,code,name,owner_user_id,lifecycle,regions,request_id,request_digest,created_at,updated_at)
  VALUES(NEW.id,NEW.tenant_id,NEW.id,NEW.id,'line',NEW.code,NEW.title,NEW.owner_user_id,target_lifecycle,NEW.regions,NEW.request_id,NEW.request_digest,NEW.created_at,NEW.updated_at);
 ELSIF (n.code,n.name,n.owner_user_id,n.lifecycle,n.regions) IS DISTINCT FROM (NEW.code,NEW.title,NEW.owner_user_id,target_lifecycle,NEW.regions) THEN
  UPDATE cehub_product.product_nodes SET name=NEW.title,owner_user_id=NEW.owner_user_id,lifecycle=target_lifecycle,regions=NEW.regions,version=n.version+1,updated_at=NEW.updated_at WHERE tenant_id=NEW.tenant_id AND id=n.id;
 END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION cehub_product.sync_category_member() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE category_line uuid;
BEGIN
 IF TG_OP='DELETE' THEN
  DELETE FROM cehub_product.product_line_members WHERE tenant_id=OLD.tenant_id AND market_space_id=OLD.market_space_id AND user_id=OLD.user_id;
  RETURN OLD;
 END IF;
 SELECT id INTO STRICT category_line FROM cehub_product.product_nodes WHERE tenant_id=NEW.tenant_id AND market_space_id=NEW.market_space_id AND level='line';
 INSERT INTO cehub_product.product_line_members(tenant_id,market_space_id,product_line_id,user_id,access,added_by_user_id,created_at)
 VALUES(NEW.tenant_id,NEW.market_space_id,category_line,NEW.user_id,NEW.access,NEW.added_by_user_id,NEW.created_at)
 ON CONFLICT(tenant_id,product_line_id,user_id) DO UPDATE SET access=EXCLUDED.access;
 RETURN NEW;
END $$;
CREATE FUNCTION cehub_product.assert_category_identity() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE category_tenant uuid; category_space uuid; s cehub_product.market_spaces%ROWTYPE; n cehub_product.product_nodes%ROWTYPE; count_lines int;
BEGIN
 IF TG_TABLE_NAME='market_spaces' THEN
  category_tenant:=COALESCE(NEW.tenant_id,OLD.tenant_id); category_space:=COALESCE(NEW.id,OLD.id);
 ELSE
  category_tenant:=COALESCE(NEW.tenant_id,OLD.tenant_id); category_space:=COALESCE(NEW.market_space_id,OLD.market_space_id);
 END IF;
 SELECT * INTO s FROM cehub_product.market_spaces WHERE tenant_id=category_tenant AND id=category_space;
 IF NOT FOUND THEN RETURN NULL; END IF;
 SELECT count(*) INTO count_lines FROM cehub_product.product_nodes WHERE tenant_id=category_tenant AND market_space_id=category_space AND level='line';
 IF count_lines<>1 THEN RAISE EXCEPTION 'A category has exactly one compatibility line, not nested categories'; END IF;
 SELECT * INTO n FROM cehub_product.product_nodes WHERE tenant_id=category_tenant AND market_space_id=category_space AND level='line';
 IF (n.code,n.name,n.owner_user_id,n.regions,n.lifecycle) IS DISTINCT FROM (s.code,s.title,s.owner_user_id,s.regions,CASE s.lifecycle WHEN 'active' THEN 'available' WHEN 'archived' THEN 'retired' ELSE 'proposed' END) THEN
  RAISE EXCEPTION 'Category identity is maintained through the category only';
 END IF;
 IF EXISTS(SELECT user_id,access FROM cehub_product.market_space_members WHERE tenant_id=category_tenant AND market_space_id=category_space EXCEPT SELECT user_id,access FROM cehub_product.product_line_members WHERE tenant_id=category_tenant AND market_space_id=category_space)
 OR EXISTS(SELECT user_id,access FROM cehub_product.product_line_members WHERE tenant_id=category_tenant AND market_space_id=category_space EXCEPT SELECT user_id,access FROM cehub_product.market_space_members WHERE tenant_id=category_tenant AND market_space_id=category_space) THEN
  RAISE EXCEPTION 'Category permissions have one source';
 END IF;
 RETURN NULL;
END $$;
REVOKE ALL ON FUNCTION cehub_product.sync_category_identity(),cehub_product.sync_category_member(),cehub_product.assert_category_identity() FROM PUBLIC,pdos_agent;
"""


def upgrade():
    c = op.get_bind()
    if c.execute(
        text(
            "SELECT EXISTS(SELECT 1 FROM cehub_product.product_nodes WHERE level='line' GROUP BY tenant_id,market_space_id HAVING count(*)>1)"
        )
    ).scalar_one():
        raise RuntimeError(
            "Multiple old product lines need human category separation; no automatic merge"
        )
    if c.execute(
        text("""SELECT EXISTS(
       SELECT 1 FROM cehub_product.product_nodes n JOIN cehub_product.market_spaces s ON s.tenant_id=n.tenant_id AND s.id=n.market_space_id
       WHERE n.level='line' AND (n.code,n.name,n.owner_user_id,n.regions,n.lifecycle) IS DISTINCT FROM
       (s.code,s.title,s.owner_user_id,s.regions,CASE s.lifecycle WHEN 'active' THEN 'available' WHEN 'archived' THEN 'retired' ELSE 'proposed' END))""")
    ).scalar_one():
        raise RuntimeError(
            "Old space and line metadata disagree; human category reconciliation required"
        )
    if c.execute(
        text("""SELECT EXISTS(
       SELECT 1 FROM cehub_product.product_nodes n WHERE n.level='line' AND (
       EXISTS(SELECT user_id,access FROM cehub_product.market_space_members WHERE tenant_id=n.tenant_id AND market_space_id=n.market_space_id EXCEPT SELECT user_id,access FROM cehub_product.product_line_members WHERE tenant_id=n.tenant_id AND product_line_id=n.id)
       OR EXISTS(SELECT user_id,access FROM cehub_product.product_line_members WHERE tenant_id=n.tenant_id AND product_line_id=n.id EXCEPT SELECT user_id,access FROM cehub_product.market_space_members WHERE tenant_id=n.tenant_id AND market_space_id=n.market_space_id)))""")
    ).scalar_one():
        raise RuntimeError("Old space and line grants disagree; refuse implicit access expansion")
    op.execute("""INSERT INTO cehub_product.product_nodes(id,tenant_id,market_space_id,product_line_id,level,code,name,owner_user_id,lifecycle,regions,request_id,request_digest,created_at,updated_at)
       SELECT s.id,s.tenant_id,s.id,s.id,'line',s.code,s.title,s.owner_user_id,CASE s.lifecycle WHEN 'active' THEN 'available' WHEN 'archived' THEN 'retired' ELSE 'proposed' END,s.regions,s.request_id,s.request_digest,s.created_at,s.updated_at
       FROM cehub_product.market_spaces s WHERE NOT EXISTS(SELECT 1 FROM cehub_product.product_nodes n WHERE n.tenant_id=s.tenant_id AND n.market_space_id=s.id AND n.level='line')""")
    op.execute("""INSERT INTO cehub_product.product_line_members(tenant_id,market_space_id,product_line_id,user_id,access,added_by_user_id,created_at)
       SELECT m.tenant_id,m.market_space_id,n.id,m.user_id,m.access,m.added_by_user_id,m.created_at FROM cehub_product.market_space_members m JOIN cehub_product.product_nodes n ON n.tenant_id=m.tenant_id AND n.market_space_id=m.market_space_id AND n.level='line' ON CONFLICT DO NOTHING""")
    op.create_index(
        "uq_product_nodes_one_category",
        "product_nodes",
        ["tenant_id", "market_space_id"],
        schema="cehub_product",
        unique=True,
        postgresql_where=text("level='line'"),
    )
    op.execute(FUNCTIONS)
    op.execute(
        "CREATE TRIGGER category_identity_projection AFTER INSERT OR UPDATE ON cehub_product.market_spaces FOR EACH ROW EXECUTE FUNCTION cehub_product.sync_category_identity()"
    )
    op.execute(
        "CREATE TRIGGER category_member_projection AFTER INSERT OR UPDATE OR DELETE ON cehub_product.market_space_members FOR EACH ROW EXECUTE FUNCTION cehub_product.sync_category_member()"
    )
    for table in ("market_spaces", "product_nodes", "market_space_members", "product_line_members"):
        op.execute(
            f"CREATE CONSTRAINT TRIGGER category_identity_consistency AFTER INSERT OR UPDATE OR DELETE ON cehub_product.{table} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION cehub_product.assert_category_identity()"
        )


def downgrade():
    if (
        op.get_bind()
        .execute(text("SELECT EXISTS(SELECT 1 FROM cehub_product.market_spaces)"))
        .scalar_one()
    ):
        raise RuntimeError("Unified category records must be retained; downgrade refused")
    for table in ("market_spaces", "product_nodes", "market_space_members", "product_line_members"):
        op.execute(f"DROP TRIGGER category_identity_consistency ON cehub_product.{table}")
    op.execute("DROP TRIGGER category_member_projection ON cehub_product.market_space_members")
    op.execute("DROP TRIGGER category_identity_projection ON cehub_product.market_spaces")
    op.execute("DROP FUNCTION cehub_product.assert_category_identity()")
    op.execute("DROP FUNCTION cehub_product.sync_category_member()")
    op.execute("DROP FUNCTION cehub_product.sync_category_identity()")
    op.drop_index(
        "uq_product_nodes_one_category", table_name="product_nodes", schema="cehub_product"
    )
