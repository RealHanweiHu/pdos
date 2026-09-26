"""Versioned quiet windows and actual independent escalation decisions."""

import sqlalchemy as sa
from alembic import op

revision = "0203_change_quiet_periods"
down_revision = "0202_conversation_quality_work"
branch_labels = None
depends_on = None

DDL = """


CREATE TABLE cehub_product.change_quiet_policies (
        id UUID NOT NULL,
        tenant_id UUID NOT NULL,
        project_id UUID NOT NULL,
        created_by_user_id UUID NOT NULL,
        request_id UUID NOT NULL,
        body JSONB NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
        version INTEGER NOT NULL,
        CONSTRAINT pk_change_quiet_policies PRIMARY KEY (id),
        CONSTRAINT uq_change_quiet_policies_scope UNIQUE (tenant_id, project_id, id),
        CONSTRAINT uq_change_quiet_policies_request UNIQUE (tenant_id, project_id,
created_by_user_id, request_id),
        CONSTRAINT fk_change_quiet_policies_tenant_id_projects FOREIGN KEY(tenant_id,
project_id) REFERENCES cehub_project.projects (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_change_quiet_policies_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT uq_change_quiet_policy_version UNIQUE (tenant_id, project_id, version),
        CONSTRAINT ck_change_quiet_policies_shape CHECK (version>0 AND
jsonb_typeof(body)='object')
)

;

CREATE TABLE cehub_product.change_quiet_requests (
        id UUID NOT NULL,
        tenant_id UUID NOT NULL,
        project_id UUID NOT NULL,
        created_by_user_id UUID NOT NULL,
        request_id UUID NOT NULL,
        body JSONB NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
        ecr_id UUID NOT NULL,
        policy_id UUID NOT NULL,
        window_key VARCHAR(8) NOT NULL,
        "window" JSONB NOT NULL,
        analysis_snapshot JSONB NOT NULL,
        analysis_digest VARCHAR(64) NOT NULL,
        CONSTRAINT pk_change_quiet_requests PRIMARY KEY (id),
        CONSTRAINT uq_change_quiet_requests_scope UNIQUE (tenant_id, project_id, id),
        CONSTRAINT uq_change_quiet_requests_request UNIQUE (tenant_id, project_id,
created_by_user_id, request_id),
        CONSTRAINT fk_change_quiet_requests_tenant_id_projects FOREIGN KEY(tenant_id,
project_id) REFERENCES cehub_project.projects (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_change_quiet_requests_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_change_quiet_requests_tenant_id_engineering_change_requests FOREIGN
KEY(tenant_id, project_id, ecr_id) REFERENCES cehub_product.engineering_change_requests
(tenant_id, project_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_change_quiet_requests_tenant_id_change_quiet_policies FOREIGN
KEY(tenant_id, project_id, policy_id) REFERENCES cehub_product.change_quiet_policies
(tenant_id, project_id, id) ON DELETE RESTRICT,
        CONSTRAINT uq_change_quiet_request_analysis UNIQUE (tenant_id, ecr_id, analysis_digest,
policy_id, window_key),
        CONSTRAINT ck_change_quiet_requests_shape CHECK (window_key IN ('pvt','mp') AND
analysis_digest ~ '^[a-f0-9]{64}$' AND jsonb_typeof(analysis_snapshot)='object')
)

;

CREATE TABLE cehub_product.change_quiet_votes (
        id UUID NOT NULL,
        tenant_id UUID NOT NULL,
        project_id UUID NOT NULL,
        created_by_user_id UUID NOT NULL,
        request_id UUID NOT NULL,
        body JSONB NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
        exception_id UUID NOT NULL,
        step INTEGER NOT NULL,
        outcome VARCHAR(12) NOT NULL,
        CONSTRAINT pk_change_quiet_votes PRIMARY KEY (id),
        CONSTRAINT uq_change_quiet_votes_scope UNIQUE (tenant_id, project_id, id),
        CONSTRAINT uq_change_quiet_votes_request UNIQUE (tenant_id, project_id,
created_by_user_id, request_id),
        CONSTRAINT fk_change_quiet_votes_tenant_id_projects FOREIGN KEY(tenant_id, project_id)
REFERENCES cehub_project.projects (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_change_quiet_votes_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_change_quiet_votes_tenant_id_change_quiet_requests FOREIGN KEY(tenant_id,
project_id, exception_id) REFERENCES cehub_product.change_quiet_requests (tenant_id,
project_id, id) ON DELETE RESTRICT,
        CONSTRAINT uq_change_quiet_vote_step UNIQUE (tenant_id, exception_id, step),
        CONSTRAINT ck_change_quiet_votes_shape CHECK (step>0 AND outcome IN
('approved','rejected'))
)

;
CREATE TRIGGER protect_change_quiet_policies BEFORE UPDATE OR DELETE ON
cehub_product.change_quiet_policies FOR EACH ROW EXECUTE FUNCTION
cehub_ai.protect_checkpoint_history();
REVOKE ALL ON cehub_product.change_quiet_policies FROM PUBLIC;

CREATE TRIGGER protect_change_quiet_requests BEFORE UPDATE OR DELETE ON
cehub_product.change_quiet_requests FOR EACH ROW EXECUTE FUNCTION
cehub_ai.protect_checkpoint_history();
REVOKE ALL ON cehub_product.change_quiet_requests FROM PUBLIC;

CREATE TRIGGER protect_change_quiet_votes BEFORE UPDATE OR DELETE ON
cehub_product.change_quiet_votes FOR EACH ROW EXECUTE FUNCTION
cehub_ai.protect_checkpoint_history();
REVOKE ALL ON cehub_product.change_quiet_votes FROM PUBLIC;

"""
GUARDS = """

CREATE FUNCTION cehub_product.quiet_requirements(t uuid,p uuid,analysis jsonb,e uuid)
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
CREATE FUNCTION cehub_product.quiet_approver(t uuid,p uuid,u uuid) RETURNS boolean
LANGUAGE sql SET search_path=pg_catalog AS $$
 SELECT EXISTS(SELECT 1 FROM cehub_core.users x WHERE x.tenant_id=t AND x.id=u AND x.is_active
 AND (x.role IN ('owner','admin') OR (x.role='project_manager' AND EXISTS(
 SELECT 1 FROM cehub_project.project_members m WHERE m.tenant_id=t AND m.project_id=p AND
m.user_id=u))))
$$;
CREATE FUNCTION cehub_product.guard_quiet_request() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE e cehub_product.engineering_change_requests%ROWTYPE;
BEGIN
 SELECT * INTO e FROM cehub_product.engineering_change_requests WHERE tenant_id=NEW.tenant_id
 AND project_id=NEW.project_id AND id=NEW.ecr_id;
 IF e.status IS DISTINCT FROM 'approval' OR NEW.analysis_snapshot IS DISTINCT FROM
e.impact_analysis
 OR NEW.window->>'key' IS DISTINCT FROM NEW.window_key
 OR NOT EXISTS(SELECT 1 FROM cehub_product.change_quiet_policies p,
 jsonb_array_elements(p.body->'windows') w WHERE p.tenant_id=NEW.tenant_id
 AND p.project_id=NEW.project_id AND p.id=NEW.policy_id AND w=NEW.window)
 OR NOT EXISTS(SELECT 1 FROM
cehub_product.quiet_requirements(NEW.tenant_id,NEW.project_id,e.impact_analysis,e.id) r
 WHERE r.policy_id=NEW.policy_id AND r.window_body=NEW.window)
 THEN RAISE EXCEPTION 'Quiet exception must bind actual policy and pending analysis'
 USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION cehub_product.guard_quiet_vote() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE r cehub_product.change_quiet_requests%ROWTYPE;
 e cehub_product.engineering_change_requests%ROWTYPE; n integer;
BEGIN
 SELECT * INTO r FROM cehub_product.change_quiet_requests WHERE tenant_id=NEW.tenant_id
 AND project_id=NEW.project_id AND id=NEW.exception_id FOR UPDATE;
 SELECT * INTO e FROM cehub_product.engineering_change_requests WHERE tenant_id=NEW.tenant_id
 AND project_id=NEW.project_id AND id=r.ecr_id;
 SELECT count(*) INTO n FROM cehub_product.change_quiet_votes WHERE exception_id=r.id;
 IF e.status IS DISTINCT FROM 'approval' OR e.impact_analysis IS DISTINCT FROM
r.analysis_snapshot
 OR NEW.step<>n+1 OR r.window->'approver_ids'->>n IS DISTINCT FROM NEW.created_by_user_id::text
 OR NEW.created_by_user_id IN
(e.requested_by_user_id,e.analyzed_by_user_id,r.created_by_user_id)
 OR NOT cehub_product.quiet_approver(NEW.tenant_id,NEW.project_id,NEW.created_by_user_id)
 OR EXISTS(SELECT 1 FROM cehub_product.change_quiet_votes WHERE exception_id=r.id AND
outcome<>'approved')
 THEN RAISE EXCEPTION 'Quiet approval requires current independent named sequence'
 USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION cehub_product.guard_quiet_ecr_approval() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE needed record;
BEGIN
 IF NEW.status='approved' AND OLD.status<>'approved' THEN
 FOR needed IN SELECT * FROM
cehub_product.quiet_requirements(NEW.tenant_id,NEW.project_id,NEW.impact_analysis,NEW.id)
 LOOP
 IF NOT EXISTS(SELECT 1 FROM cehub_product.change_quiet_requests r
 WHERE r.tenant_id=NEW.tenant_id AND r.project_id=NEW.project_id AND r.ecr_id=NEW.id
 AND r.policy_id=needed.policy_id AND r.window=needed.window_body
 AND r.analysis_snapshot=NEW.impact_analysis
 AND (SELECT count(*) FROM cehub_product.change_quiet_votes v WHERE v.exception_id=r.id
 AND v.outcome='approved')=jsonb_array_length(r.window->'approver_ids')
 AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements_text(r.window->'approver_ids') a
 WHERE NOT cehub_product.quiet_approver(NEW.tenant_id,NEW.project_id,a::uuid)
 OR a::uuid IN (NEW.requested_by_user_id,NEW.analyzed_by_user_id,r.created_by_user_id)))
 THEN RAISE EXCEPTION 'Quiet period escalation approval required' USING ERRCODE='23514'; END
IF;
 END LOOP;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_quiet_request BEFORE INSERT ON cehub_product.change_quiet_requests
 FOR EACH ROW EXECUTE FUNCTION cehub_product.guard_quiet_request();
CREATE TRIGGER guard_quiet_vote BEFORE INSERT ON cehub_product.change_quiet_votes
 FOR EACH ROW EXECUTE FUNCTION cehub_product.guard_quiet_vote();
CREATE TRIGGER guard_quiet_ecr_approval BEFORE UPDATE ON
cehub_product.engineering_change_requests
 FOR EACH ROW EXECUTE FUNCTION cehub_product.guard_quiet_ecr_approval();

REVOKE ALL ON FUNCTION cehub_product.quiet_requirements(uuid,uuid,jsonb,uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_product.quiet_approver(uuid,uuid,uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_product.guard_quiet_request() FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_product.guard_quiet_vote() FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_product.guard_quiet_ecr_approval() FROM PUBLIC;
"""


def upgrade() -> None:
    op.execute(sa.text(DDL))
    op.execute(sa.text(GUARDS))


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS(SELECT 1 FROM cehub_product.change_quiet_policies)"))
        .scalar()
    ):
        raise RuntimeError("Refusing to discard quiet policy and approval history")
    op.execute("DROP TRIGGER guard_quiet_ecr_approval ON cehub_product.engineering_change_requests")
    op.execute("DROP FUNCTION cehub_product.guard_quiet_ecr_approval()")
    op.execute("DROP TABLE cehub_product.change_quiet_votes")
    op.execute("DROP TABLE cehub_product.change_quiet_requests")
    op.execute("DROP FUNCTION cehub_product.guard_quiet_vote()")
    op.execute("DROP FUNCTION cehub_product.guard_quiet_request()")
    op.execute("DROP FUNCTION cehub_product.quiet_approver(uuid,uuid,uuid)")
    op.execute("DROP FUNCTION cehub_product.quiet_requirements(uuid,uuid,jsonb,uuid)")
    op.execute("DROP TABLE cehub_product.change_quiet_policies")
