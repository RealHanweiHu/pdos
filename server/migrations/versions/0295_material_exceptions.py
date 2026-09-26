"""Confirmed material exceptions, actual Issues and immutable source reviews."""

from alembic import op

revision = "0295_material_exceptions"
down_revision = "0294_material_allocations"
branch_labels = None
depends_on = None

DDL = """
CREATE TABLE cehub_supplier.material_exceptions (
id UUID NOT NULL,
tenant_id UUID NOT NULL,
project_id UUID NOT NULL,
build_id UUID NOT NULL,
material_key VARCHAR(64) NOT NULL,
material_reference VARCHAR(256),
unit VARCHAR(64) NOT NULL,
issue_id UUID NOT NULL,
created_by_user_id UUID NOT NULL,
request_id UUID NOT NULL,
request_digest VARCHAR(64) NOT NULL,
created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
CONSTRAINT pk_material_exceptions PRIMARY KEY (id),
CONSTRAINT uq_material_exception_scope UNIQUE (tenant_id, project_id, id),
CONSTRAINT uq_material_exception_identity UNIQUE (tenant_id, build_id, material_key),
CONSTRAINT uq_material_exception_issue UNIQUE (tenant_id, issue_id),
CONSTRAINT uq_material_exception_request UNIQUE (tenant_id, created_by_user_id, request_id),
CONSTRAINT fk_material_exceptions_tenant_id_build_batches FOREIGN KEY(tenant_id, project_id,
build_id) REFERENCES cehub_product.build_batches (tenant_id, project_id, id) ON DELETE RESTRICT,
CONSTRAINT fk_material_exceptions_tenant_id_issues FOREIGN KEY(tenant_id, project_id, issue_id)
REFERENCES cehub_project.issues (tenant_id, project_id, id) ON DELETE RESTRICT,
CONSTRAINT fk_material_exceptions_tenant_id_users FOREIGN KEY(tenant_id, created_by_user_id)
REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
CONSTRAINT ck_material_exceptions_digests_valid CHECK (material_key ~ '^[0-9a-f]{64}$' AND
request_digest ~ '^[0-9a-f]{64}$')
);
CREATE TABLE cehub_supplier.material_exception_reviews (
id UUID NOT NULL,
tenant_id UUID NOT NULL,
project_id UUID NOT NULL,
exception_id UUID NOT NULL,
version INTEGER NOT NULL,
revision_id UUID NOT NULL,
created_by_user_id UUID NOT NULL,
request_id UUID NOT NULL,
request_digest VARCHAR(64) NOT NULL,
basis_digest VARCHAR(64) NOT NULL,
disposition VARCHAR(24) NOT NULL,
reason TEXT NOT NULL,
snapshot JSONB NOT NULL,
created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
CONSTRAINT pk_material_exception_reviews PRIMARY KEY (id),
CONSTRAINT uq_material_exception_review_version UNIQUE (tenant_id, exception_id, version),
CONSTRAINT uq_material_exception_review_request UNIQUE (tenant_id, created_by_user_id,
request_id),
CONSTRAINT fk_material_exception_reviews_tenant_id_material_exceptions FOREIGN KEY(tenant_id,
project_id, exception_id) REFERENCES cehub_supplier.material_exceptions (tenant_id, project_id,
id) ON DELETE RESTRICT,
CONSTRAINT fk_material_exception_reviews_tenant_id_build_material__f2bd FOREIGN KEY(tenant_id,
project_id, revision_id) REFERENCES cehub_product.build_material_revisions (tenant_id, project_id,
id) ON DELETE RESTRICT,
CONSTRAINT fk_material_exception_reviews_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
CONSTRAINT ck_material_exception_reviews_review_disposition CHECK (version>0 AND disposition IN
('follow_up','supply_ready','scope_changed') AND btrim(reason)<>''),
CONSTRAINT ck_material_exception_reviews_snapshot_object CHECK (jsonb_typeof(snapshot)='object'),
CONSTRAINT ck_material_exception_reviews_digests_valid CHECK (basis_digest ~ '^[0-9a-f]{64}$' AND
request_digest ~ '^[0-9a-f]{64}$')
);
"""

GUARDS = """
CREATE FUNCTION cehub_supplier.material_exception_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 PERFORM 1 FROM cehub_project.projects WHERE tenant_id=NEW.tenant_id
 AND id=NEW.project_id FOR UPDATE;
 IF NOT EXISTS (SELECT 1 FROM cehub_project.issues i WHERE i.tenant_id=NEW.tenant_id
 AND i.project_id=NEW.project_id AND i.id=NEW.issue_id AND i.issue_type='supplier'
 AND i.status='open' AND i.reported_by_user_id=NEW.created_by_user_id) THEN
 RAISE EXCEPTION 'Material exception requires its actual reported supplier Issue'; END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION cehub_supplier.material_exception_review_guard()
 RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE parent cehub_supplier.material_exceptions%ROWTYPE; latest integer;
BEGIN
 PERFORM 1 FROM cehub_project.projects WHERE tenant_id=NEW.tenant_id
 AND id=NEW.project_id FOR UPDATE;
 SELECT * INTO STRICT parent FROM cehub_supplier.material_exceptions
 WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.exception_id;
 SELECT coalesce(max(version),0) INTO latest FROM cehub_supplier.material_exception_reviews
 WHERE tenant_id=NEW.tenant_id AND exception_id=NEW.exception_id;
 IF NEW.version<>latest+1 OR NEW.snapshot->>'digest' IS DISTINCT FROM NEW.basis_digest
 OR NEW.snapshot#>>'{basis,revision_id}' IS DISTINCT FROM NEW.revision_id::text
 OR NEW.snapshot#>>'{basis,material_key}' IS DISTINCT FROM parent.material_key THEN
 RAISE EXCEPTION 'Material review requires the next version and fixed source basis'; END IF;
 IF NOT EXISTS (SELECT 1 FROM cehub_product.build_material_revisions r
 WHERE r.tenant_id=NEW.tenant_id AND r.project_id=NEW.project_id AND r.id=NEW.revision_id
 AND r.build_id=parent.build_id
 AND r.content_digest=NEW.snapshot#>>'{basis,revision_digest}'
 AND NOT EXISTS (SELECT 1 FROM cehub_product.build_material_revisions newer
 WHERE newer.tenant_id=r.tenant_id AND newer.build_id=r.build_id AND newer.version>r.version)) THEN
 RAISE EXCEPTION 'Material review requires current fixed Build demand'; END IF;
 IF NEW.disposition='scope_changed' AND NEW.snapshot#>'{basis,material}'<>'null'::jsonb THEN
 RAISE EXCEPTION 'Scope change requires absent demand material'; END IF;
 IF NEW.disposition<>'scope_changed' AND (
 NEW.snapshot#>>'{basis,material,material_key}' IS DISTINCT FROM parent.material_key OR
 NEW.snapshot#>>'{basis,material,unit}' IS DISTINCT FROM parent.unit OR
 NEW.snapshot#>>'{basis,material,material_reference}' IS DISTINCT FROM parent.material_reference)
 THEN
 RAISE EXCEPTION 'Review material must match its original exception identity';
 END IF;
 IF NEW.disposition='supply_ready' AND (
 (NEW.snapshot#>>'{basis,material,allocated_on_hand}')::numeric IS NULL OR
 (NEW.snapshot#>>'{basis,material,required}')::numeric IS NULL OR
 (NEW.snapshot#>>'{basis,material,allocated_on_hand}')::numeric <
 (NEW.snapshot#>>'{basis,material,required}')::numeric) THEN
 RAISE EXCEPTION 'Supply readiness requires explicitly allocated qualified on-hand coverage';
 END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION cehub_supplier.material_exception_initial_review()
 RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NOT EXISTS (SELECT 1 FROM cehub_supplier.material_exception_reviews r
 WHERE r.tenant_id=NEW.tenant_id AND r.exception_id=NEW.id AND r.version=1
 AND r.created_by_user_id=NEW.created_by_user_id AND r.request_id=NEW.request_id
 AND r.request_digest=NEW.request_digest AND r.disposition='follow_up') THEN
 RAISE EXCEPTION 'Confirmed material exception requires its original review'; END IF;
 RETURN NULL;
END $$;
CREATE TRIGGER material_exception_guard BEFORE INSERT ON cehub_supplier.material_exceptions
 FOR EACH ROW EXECUTE FUNCTION cehub_supplier.material_exception_guard();
CREATE TRIGGER material_exception_review_guard
 BEFORE INSERT ON cehub_supplier.material_exception_reviews
 FOR EACH ROW EXECUTE FUNCTION cehub_supplier.material_exception_review_guard();
CREATE CONSTRAINT TRIGGER material_exception_initial_review
 AFTER INSERT ON cehub_supplier.material_exceptions DEFERRABLE INITIALLY DEFERRED
 FOR EACH ROW EXECUTE FUNCTION cehub_supplier.material_exception_initial_review();
CREATE TRIGGER material_exception_immutable BEFORE UPDATE OR DELETE
 ON cehub_supplier.material_exceptions
 FOR EACH ROW EXECUTE FUNCTION cehub_supplier.material_ledger_immutable();
CREATE TRIGGER material_exception_review_immutable BEFORE UPDATE OR DELETE
 ON cehub_supplier.material_exception_reviews
 FOR EACH ROW EXECUTE FUNCTION cehub_supplier.material_ledger_immutable();
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARDS)


def downgrade() -> None:
    op.execute("""
    DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM cehub_supplier.material_exceptions) THEN
    RAISE EXCEPTION 'Material exception history requires retention; downgrade refused'; END IF;
    END $$;
    DROP TABLE cehub_supplier.material_exception_reviews;
    DROP TABLE cehub_supplier.material_exceptions;
    DROP FUNCTION cehub_supplier.material_exception_guard();
    DROP FUNCTION cehub_supplier.material_exception_review_guard();
    DROP FUNCTION cehub_supplier.material_exception_initial_review();
    """)
