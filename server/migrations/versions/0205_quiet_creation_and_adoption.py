"""Capture ECR creation requirements and explicit immutable policy adoptions."""

import sqlalchemy as sa
from alembic import op

revision = "0205_quiet_creation_and_adoption"
down_revision = "0204_quiet_baseline_and_replacements"
branch_labels = None
depends_on = None

DDL = """

CREATE TABLE cehub_product.change_quiet_origins (
    id UUID NOT NULL,
    tenant_id UUID NOT NULL,
    project_id UUID NOT NULL,
    ecr_id UUID NOT NULL,
    policy_id UUID,
    checked_at TIMESTAMP WITH TIME ZONE NOT NULL,
    requirements JSONB NOT NULL,
    CONSTRAINT pk_change_quiet_origins PRIMARY KEY (id),
    CONSTRAINT uq_quiet_origin_ecr UNIQUE (tenant_id, project_id, ecr_id),
        CONSTRAINT fk_change_quiet_origins_tenant_id_engineering_change_requests FOREIGN
KEY(tenant_id, project_id, ecr_id) REFERENCES cehub_product.engineering_change_requests
(tenant_id, project_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_change_quiet_origins_tenant_id_change_quiet_policies FOREIGN
KEY(tenant_id, project_id, policy_id) REFERENCES cehub_product.change_quiet_policies
(tenant_id, project_id, id) ON DELETE RESTRICT,
    CONSTRAINT ck_change_quiet_origins_shape CHECK (jsonb_typeof(requirements)='array')
)

;

CREATE TABLE cehub_product.change_quiet_adoptions (
    id UUID NOT NULL,
    tenant_id UUID NOT NULL,
    project_id UUID NOT NULL,
    ecr_id UUID NOT NULL,
    old_policy_id UUID NOT NULL,
    new_policy_id UUID NOT NULL,
    new_policy_version INTEGER NOT NULL,
    window_key VARCHAR(8) NOT NULL,
    old_window JSONB NOT NULL,
    new_window JSONB NOT NULL,
    analysis_snapshot JSONB,
    body JSONB NOT NULL,
    created_by_user_id UUID NOT NULL,
    request_id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT pk_change_quiet_adoptions PRIMARY KEY (id),
        CONSTRAINT uq_quiet_adoption_source UNIQUE (tenant_id, project_id, ecr_id,
old_policy_id, window_key),
        CONSTRAINT uq_quiet_adoption_request UNIQUE (tenant_id, project_id, created_by_user_id,
request_id),
        CONSTRAINT fk_change_quiet_adoptions_tenant_id_engineering_change_requests FOREIGN
KEY(tenant_id, project_id, ecr_id) REFERENCES cehub_product.engineering_change_requests
(tenant_id, project_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_quiet_adoption_old_policy FOREIGN KEY(tenant_id, project_id,
old_policy_id) REFERENCES cehub_product.change_quiet_policies (tenant_id, project_id, id) ON
DELETE RESTRICT,
        CONSTRAINT fk_quiet_adoption_new_policy FOREIGN KEY(tenant_id, project_id,
new_policy_id) REFERENCES cehub_product.change_quiet_policies (tenant_id, project_id, id) ON
DELETE RESTRICT,
        CONSTRAINT fk_change_quiet_adoptions_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT ck_change_quiet_adoptions_shape CHECK (window_key IN ('pvt','mp') AND
old_policy_id<>new_policy_id AND new_policy_version>0 AND jsonb_typeof(body)='object' AND
jsonb_typeof(old_window)='object' AND jsonb_typeof(new_window)='object')
)

;
CREATE TRIGGER protect_change_quiet_origins BEFORE UPDATE OR DELETE ON
cehub_product.change_quiet_origins FOR EACH ROW EXECUTE FUNCTION
cehub_ai.protect_checkpoint_history();
REVOKE ALL ON cehub_product.change_quiet_origins FROM PUBLIC;
CREATE TRIGGER protect_change_quiet_adoptions BEFORE UPDATE OR DELETE ON
cehub_product.change_quiet_adoptions FOR EACH ROW EXECUTE FUNCTION
cehub_ai.protect_checkpoint_history();
REVOKE ALL ON cehub_product.change_quiet_adoptions FROM PUBLIC;
"""
GUARDS = """
CREATE OR REPLACE FUNCTION cehub_product.quiet_requirements(t uuid,p uuid,analysis jsonb,e
uuid)
RETURNS TABLE(policy_id uuid,window_body jsonb) LANGUAGE sql SET search_path=pg_catalog AS $$
 WITH RECURSIVE latest AS (SELECT * FROM cehub_product.change_quiet_policies
 WHERE tenant_id=t AND project_id=p ORDER BY version DESC LIMIT 1),
 seed(policy_id,window_body) AS (
 SELECT (v->>'policy_id')::uuid,v->'window'
 FROM jsonb_array_elements(coalesce(analysis->'quiet_period','[]'::jsonb)) v
 UNION
 SELECT r.policy_id,r.window FROM cehub_product.change_quiet_requests r
 WHERE r.tenant_id=t AND r.project_id=p AND r.ecr_id=e AND r.analysis_snapshot=analysis
 UNION
 SELECT l.id,w FROM latest l CROSS JOIN LATERAL jsonb_array_elements(l.body->'windows') w
 WHERE (l.body->>'enabled')::boolean AND clock_timestamp()>=(w->>'starts_at')::timestamptz
 AND clock_timestamp()<(w->>'ends_at')::timestamptz
 UNION
 SELECT (v->>'policy_id')::uuid,v->'window'
 FROM cehub_product.change_quiet_origins o CROSS JOIN LATERAL
 jsonb_array_elements(o.requirements) v WHERE o.tenant_id=t AND o.project_id=p AND o.ecr_id=e
 UNION
 SELECT a.new_policy_id,a.new_window FROM cehub_product.change_quiet_adoptions a
 WHERE a.tenant_id=t AND a.project_id=p AND a.ecr_id=e
 ), walk(policy_id,window_body) AS (
 SELECT s.policy_id,s.window_body FROM seed s
 UNION
 SELECT a.new_policy_id,a.new_window FROM walk w
 JOIN cehub_product.change_quiet_adoptions a ON a.tenant_id=t AND a.project_id=p
 AND a.ecr_id=e AND a.old_policy_id=w.policy_id AND a.window_key=w.window_body->>'key'
 ) SELECT DISTINCT w.policy_id,w.window_body FROM walk w WHERE NOT EXISTS (
 SELECT 1 FROM cehub_product.change_quiet_adoptions a WHERE a.tenant_id=t AND a.project_id=p
 AND a.ecr_id=e AND a.old_policy_id=w.policy_id AND a.window_key=w.window_body->>'key')
$$;
CREATE FUNCTION cehub_product.capture_quiet_origin() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE policy cehub_product.change_quiet_policies%ROWTYPE; checked timestamptz; needed jsonb;
BEGIN
 PERFORM 1 FROM cehub_project.projects WHERE tenant_id=NEW.tenant_id AND id=NEW.project_id
 FOR UPDATE;
 checked := clock_timestamp();
 SELECT * INTO policy FROM cehub_product.change_quiet_policies
 WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id ORDER BY version DESC LIMIT 1;
 SELECT coalesce(jsonb_agg(jsonb_build_object('policy_id',policy.id,
 'policy_version',policy.version,'window',w) ORDER BY w->>'key'),'[]'::jsonb) INTO needed
 FROM jsonb_array_elements(coalesce(policy.body->'windows','[]'::jsonb)) w
 WHERE (policy.body->>'enabled')::boolean AND checked>=(w->>'starts_at')::timestamptz
 AND checked<(w->>'ends_at')::timestamptz;
 INSERT INTO cehub_product.change_quiet_origins
 (id,tenant_id,project_id,ecr_id,policy_id,checked_at,requirements)
 VALUES(gen_random_uuid(),NEW.tenant_id,NEW.project_id,NEW.id,policy.id,checked,needed);
 RETURN NEW;
END $$;
CREATE TRIGGER capture_quiet_origin AFTER INSERT ON cehub_product.engineering_change_requests
FOR EACH ROW EXECUTE FUNCTION cehub_product.capture_quiet_origin();
CREATE FUNCTION cehub_product.guard_quiet_adoption() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE e cehub_product.engineering_change_requests%ROWTYPE;
 policy cehub_product.change_quiet_policies%ROWTYPE; prior_version integer; actual_window
jsonb;
BEGIN
 PERFORM 1 FROM cehub_project.projects WHERE tenant_id=NEW.tenant_id AND id=NEW.project_id
 FOR UPDATE;
 SELECT * INTO e FROM cehub_product.engineering_change_requests
 WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.ecr_id FOR UPDATE;
 SELECT * INTO policy FROM cehub_product.change_quiet_policies
 WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id ORDER BY version DESC LIMIT 1;
 SELECT version INTO prior_version FROM cehub_product.change_quiet_policies
 WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.old_policy_id;
 SELECT w INTO actual_window FROM jsonb_array_elements(policy.body->'windows') w
 WHERE w->>'key'=NEW.window_key;
 IF e.id IS NULL OR e.status<>'impact_analysis'
 OR coalesce(NEW.analysis_snapshot,'null'::jsonb) IS DISTINCT FROM
 coalesce(e.impact_analysis,'null'::jsonb)
 OR policy.id IS DISTINCT FROM NEW.new_policy_id OR NOT (policy.body->>'enabled')::boolean
 OR prior_version IS NULL OR policy.version<=prior_version
 OR NEW.new_policy_version<>policy.version OR actual_window IS DISTINCT FROM NEW.new_window
 OR actual_window IS NULL OR jsonb_array_length(NEW.new_window->'approver_ids')<
 jsonb_array_length(NEW.old_window->'approver_ids')
 OR NOT EXISTS(SELECT 1 FROM cehub_product.quiet_requirements(
 NEW.tenant_id,NEW.project_id,e.impact_analysis,e.id) r WHERE r.policy_id=NEW.old_policy_id
 AND r.window_body=NEW.old_window AND r.window_body->>'key'=NEW.window_key)
 OR NOT cehub_product.quiet_source_current(NEW.tenant_id,NEW.project_id,
 NEW.new_policy_id,NEW.window_key)
 OR NOT cehub_product.quiet_approver(NEW.tenant_id,NEW.project_id,NEW.created_by_user_id)
 OR NEW.created_by_user_id=e.requested_by_user_id
 OR NEW.created_by_user_id IS NOT DISTINCT FROM e.analyzed_by_user_id
 OR (NEW.new_window->'approver_ids') ? NEW.created_by_user_id::text
 OR coalesce(length(btrim(NEW.body->>'reason')),0)=0
 THEN RAISE EXCEPTION 'quiet policy adoption requires current independent evidence'
 USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_quiet_adoption BEFORE INSERT ON cehub_product.change_quiet_adoptions
FOR EACH ROW EXECUTE FUNCTION cehub_product.guard_quiet_adoption();
REVOKE ALL ON FUNCTION cehub_product.capture_quiet_origin() FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_product.guard_quiet_adoption() FROM PUBLIC;
"""
OLD_REQUIREMENTS = """
CREATE OR REPLACE FUNCTION cehub_product.quiet_requirements(t uuid,p uuid,analysis jsonb,e uuid)
RETURNS TABLE(policy_id uuid,window_body jsonb) LANGUAGE sql SET search_path=pg_catalog AS $$
 WITH latest AS (SELECT * FROM cehub_product.change_quiet_policies
 WHERE tenant_id=t AND project_id=p ORDER BY version DESC LIMIT 1)
 SELECT (v->>'policy_id')::uuid,v->'window'
 FROM jsonb_array_elements(coalesce(analysis->'quiet_period','[]'::jsonb)) v
 UNION
 SELECT r.policy_id,r.window FROM cehub_product.change_quiet_requests r
 WHERE r.tenant_id=t AND r.project_id=p AND r.ecr_id=e AND r.analysis_snapshot=analysis
 UNION
 SELECT l.id,w FROM latest l CROSS JOIN LATERAL jsonb_array_elements(l.body->'windows') w
 WHERE (l.body->>'enabled')::boolean AND clock_timestamp()>=(w->>'starts_at')::timestamptz
 AND clock_timestamp()<(w->>'ends_at')::timestamptz
$$;

"""


def upgrade() -> None:
    op.execute(sa.text(DDL))
    op.execute(sa.text(GUARDS))


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM cehub_product.change_quiet_origins) "
                "OR EXISTS(SELECT 1 FROM cehub_product.change_quiet_adoptions)"
            )
        )
        .scalar()
    ):
        raise RuntimeError("Refusing to discard creation or policy adoption evidence")
    op.execute("DROP TRIGGER capture_quiet_origin ON cehub_product.engineering_change_requests")
    op.execute("DROP FUNCTION cehub_product.capture_quiet_origin()")
    op.execute(sa.text(OLD_REQUIREMENTS))
    op.execute("DROP TABLE cehub_product.change_quiet_adoptions")
    op.execute("DROP TABLE cehub_product.change_quiet_origins")
    op.execute("DROP FUNCTION cehub_product.guard_quiet_adoption()")
