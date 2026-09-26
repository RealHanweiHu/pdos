"""Fixed baseline references and authorized approval-chain replacement history."""

import sqlalchemy as sa
from alembic import op

revision = "0204_quiet_baseline_and_replacements"
down_revision = "0203_change_quiet_periods"
branch_labels = None
depends_on = None

DDL = """

CREATE TABLE cehub_product.change_quiet_policy_anchors (
        id UUID NOT NULL,
        tenant_id UUID NOT NULL,
        project_id UUID NOT NULL,
        policy_id UUID NOT NULL,
        window_key VARCHAR(8) NOT NULL,
        baseline_id UUID NOT NULL,
        node_id UUID NOT NULL,
        source_digest VARCHAR(64) NOT NULL,
        snapshot JSONB NOT NULL,
        CONSTRAINT pk_change_quiet_policy_anchors PRIMARY KEY (id),
        CONSTRAINT uq_quiet_policy_anchor UNIQUE (tenant_id, project_id, policy_id,
window_key),
        CONSTRAINT fk_change_quiet_policy_anchors_tenant_id_change_quiet_policies FOREIGN
KEY(tenant_id, project_id, policy_id) REFERENCES cehub_product.change_quiet_policies
(tenant_id, project_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_change_quiet_policy_anchors_tenant_id_schedule_time_records FOREIGN
KEY(tenant_id, project_id, baseline_id) REFERENCES cehub_project.schedule_time_records
(tenant_id, project_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_change_quiet_policy_anchors_tenant_id_schedule_nodes FOREIGN
KEY(tenant_id, project_id, node_id) REFERENCES cehub_project.schedule_nodes (tenant_id,
project_id, id) ON DELETE RESTRICT,
        CONSTRAINT ck_change_quiet_policy_anchors_shape CHECK (window_key IN ('pvt','mp') AND
source_digest ~ '^[a-f0-9]{64}$')
)

;

CREATE TABLE cehub_product.change_quiet_replacements (
        id UUID NOT NULL,
        tenant_id UUID NOT NULL,
        project_id UUID NOT NULL,
        exception_id UUID NOT NULL,
        revision INTEGER NOT NULL,
        body JSONB NOT NULL,
        created_by_user_id UUID NOT NULL,
        request_id UUID NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
        CONSTRAINT pk_change_quiet_replacements PRIMARY KEY (id),
        CONSTRAINT uq_quiet_replacement_revision UNIQUE (tenant_id, exception_id, revision),
        CONSTRAINT uq_quiet_replacement_request UNIQUE (tenant_id, project_id,
created_by_user_id, request_id),
        CONSTRAINT fk_change_quiet_replacements_tenant_id_change_quiet_requests FOREIGN
KEY(tenant_id, project_id, exception_id) REFERENCES cehub_product.change_quiet_requests
(tenant_id, project_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_change_quiet_replacements_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT ck_change_quiet_replacements_shape CHECK (revision>0 AND
jsonb_typeof(body)='object')
)

;
CREATE TRIGGER protect_change_quiet_policy_anchors BEFORE UPDATE OR DELETE ON
cehub_product.change_quiet_policy_anchors FOR EACH ROW EXECUTE FUNCTION
cehub_ai.protect_checkpoint_history();
REVOKE ALL ON cehub_product.change_quiet_policy_anchors FROM PUBLIC;

CREATE TRIGGER protect_change_quiet_replacements BEFORE UPDATE OR DELETE ON
cehub_product.change_quiet_replacements FOR EACH ROW EXECUTE FUNCTION
cehub_ai.protect_checkpoint_history();
REVOKE ALL ON cehub_product.change_quiet_replacements FROM PUBLIC;
"""
GUARDS = """
CREATE FUNCTION cehub_product.quiet_source_current(t uuid,p uuid,policy uuid,k text)
RETURNS boolean LANGUAGE sql SET search_path=pg_catalog AS $$
 SELECT EXISTS(SELECT 1 FROM cehub_product.change_quiet_policy_anchors a
 JOIN cehub_project.schedule_time_records b ON b.tenant_id=a.tenant_id
 AND b.project_id=a.project_id AND b.id=a.baseline_id
 JOIN cehub_project.schedule_time_nodes n ON n.tenant_id=a.tenant_id
 AND n.project_id=a.project_id AND n.record_id=a.baseline_id AND n.node_id=a.node_id
 WHERE a.tenant_id=t AND a.project_id=p AND a.policy_id=policy AND a.window_key=k
 AND b.time_kind='baseline' AND n.start IS NOT NULL AND n.end IS NOT NULL
 AND NOT EXISTS(SELECT 1 FROM cehub_project.schedule_time_records newer
 WHERE newer.tenant_id=t AND newer.project_id=p AND newer.time_kind='baseline'
 AND newer.version>b.version))
$$;
CREATE FUNCTION cehub_product.quiet_chain(r uuid) RETURNS jsonb
LANGUAGE sql SET search_path=pg_catalog AS $$
 SELECT coalesce((SELECT body->'approver_ids' FROM cehub_product.change_quiet_replacements
 WHERE exception_id=r ORDER BY revision DESC LIMIT 1),
 (SELECT req.window->'approver_ids' FROM cehub_product.change_quiet_requests req WHERE req.id=r))
$$;
CREATE FUNCTION cehub_product.quiet_chain_revision(r uuid) RETURNS integer
LANGUAGE sql SET search_path=pg_catalog AS $$
 SELECT coalesce(max(revision),0) FROM cehub_product.change_quiet_replacements WHERE
exception_id=r
$$;
CREATE FUNCTION cehub_product.guard_quiet_anchor() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM cehub_product.change_quiet_policies p,
 jsonb_array_elements(p.body->'windows') w WHERE p.tenant_id=NEW.tenant_id
 AND p.project_id=NEW.project_id AND p.id=NEW.policy_id AND w->>'key'=NEW.window_key
 AND w->'anchor'->>'baseline_id'=NEW.baseline_id::text
 AND w->'anchor'->>'node_id'=NEW.node_id::text
 AND w->'anchor'->>'expected_digest'=NEW.source_digest)
 OR NOT EXISTS(SELECT 1 FROM cehub_project.schedule_time_records b
 JOIN cehub_project.schedule_time_nodes n ON n.record_id=b.id AND n.tenant_id=b.tenant_id
 AND n.project_id=b.project_id WHERE b.id=NEW.baseline_id AND b.tenant_id=NEW.tenant_id
 AND b.project_id=NEW.project_id AND b.time_kind='baseline' AND n.node_id=NEW.node_id
 AND n.start IS NOT NULL AND n.end IS NOT NULL AND NOT EXISTS(
 SELECT 1 FROM cehub_project.schedule_time_records newer WHERE newer.tenant_id=b.tenant_id
 AND newer.project_id=b.project_id AND newer.time_kind='baseline' AND newer.version>b.version))
 THEN RAISE EXCEPTION 'Quiet policy requires current actual baseline node' USING
ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION cehub_product.guard_quiet_replacement() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE r cehub_product.change_quiet_requests%ROWTYPE;
 e cehub_product.engineering_change_requests%ROWTYPE; chain jsonb; revision integer;
BEGIN
 SELECT * INTO r FROM cehub_product.change_quiet_requests WHERE tenant_id=NEW.tenant_id
 AND project_id=NEW.project_id AND id=NEW.exception_id FOR UPDATE;
 SELECT * INTO e FROM cehub_product.engineering_change_requests WHERE tenant_id=NEW.tenant_id
 AND project_id=NEW.project_id AND id=r.ecr_id;
 chain:=cehub_product.quiet_chain(r.id); revision:=cehub_product.quiet_chain_revision(r.id);
 IF e.status IS DISTINCT FROM 'approval' OR e.impact_analysis IS DISTINCT FROM
r.analysis_snapshot
 OR NOT
cehub_product.quiet_source_current(NEW.tenant_id,NEW.project_id,r.policy_id,r.window_key)
 OR NEW.revision<>revision+1 OR NEW.body->'approver_ids'=chain
 OR jsonb_array_length(NEW.body->'approver_ids')<>jsonb_array_length(chain)
 OR (SELECT count(DISTINCT a) FROM jsonb_array_elements_text(NEW.body->'approver_ids') a)
 <>jsonb_array_length(chain)
 OR NOT cehub_product.quiet_approver(NEW.tenant_id,NEW.project_id,NEW.created_by_user_id)
 OR NEW.created_by_user_id IN
(e.requested_by_user_id,e.analyzed_by_user_id,r.created_by_user_id)
 OR EXISTS(SELECT 1 FROM jsonb_array_elements_text(NEW.body->'approver_ids') a
 WHERE a::uuid IN
(NEW.created_by_user_id,e.requested_by_user_id,e.analyzed_by_user_id,r.created_by_user_id)
 OR NOT cehub_product.quiet_approver(NEW.tenant_id,NEW.project_id,a::uuid))
 OR EXISTS(SELECT 1 FROM cehub_product.change_quiet_votes WHERE exception_id=r.id
 AND chain_revision=revision AND outcome='rejected')
 THEN RAISE EXCEPTION 'Quiet replacement requires independent authorization and complete chain'
 USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE OR REPLACE FUNCTION cehub_product.guard_quiet_vote() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE r cehub_product.change_quiet_requests%ROWTYPE;
 e cehub_product.engineering_change_requests%ROWTYPE; n integer; chain jsonb; revision integer;
BEGIN
 SELECT * INTO r FROM cehub_product.change_quiet_requests WHERE tenant_id=NEW.tenant_id
 AND project_id=NEW.project_id AND id=NEW.exception_id FOR UPDATE;
 SELECT * INTO e FROM cehub_product.engineering_change_requests WHERE tenant_id=NEW.tenant_id
 AND project_id=NEW.project_id AND id=r.ecr_id;
 chain:=cehub_product.quiet_chain(r.id); revision:=cehub_product.quiet_chain_revision(r.id);
 SELECT count(*) INTO n FROM cehub_product.change_quiet_votes
 WHERE exception_id=r.id AND chain_revision=revision;
 IF e.status IS DISTINCT FROM 'approval' OR e.impact_analysis IS DISTINCT FROM
r.analysis_snapshot
 OR NOT
cehub_product.quiet_source_current(NEW.tenant_id,NEW.project_id,r.policy_id,r.window_key)
 OR NEW.chain_revision<>revision OR NEW.step<>n+1
 OR chain->>n IS DISTINCT FROM NEW.created_by_user_id::text
 OR NEW.created_by_user_id IN
(e.requested_by_user_id,e.analyzed_by_user_id,r.created_by_user_id)
 OR NOT cehub_product.quiet_approver(NEW.tenant_id,NEW.project_id,NEW.created_by_user_id)
 OR EXISTS(SELECT 1 FROM cehub_product.change_quiet_votes WHERE exception_id=r.id
 AND chain_revision=revision AND outcome<>'approved')
 THEN RAISE EXCEPTION 'Quiet approval requires current independent named sequence'
 USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE OR REPLACE FUNCTION cehub_product.guard_quiet_ecr_approval() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE needed record;
BEGIN
 IF NEW.status='approved' AND OLD.status<>'approved' THEN
 FOR needed IN SELECT * FROM cehub_product.quiet_requirements(
 NEW.tenant_id,NEW.project_id,NEW.impact_analysis,NEW.id) LOOP
 IF NOT cehub_product.quiet_source_current(NEW.tenant_id,NEW.project_id,
 needed.policy_id,needed.window_body->>'key') OR NOT EXISTS(
 SELECT 1 FROM cehub_product.change_quiet_requests r WHERE r.tenant_id=NEW.tenant_id
 AND r.project_id=NEW.project_id AND r.ecr_id=NEW.id AND r.policy_id=needed.policy_id
 AND r.window=needed.window_body AND r.analysis_snapshot=NEW.impact_analysis
 AND (SELECT count(*) FROM cehub_product.change_quiet_votes v WHERE v.exception_id=r.id
 AND v.chain_revision=cehub_product.quiet_chain_revision(r.id) AND v.outcome='approved')
 =jsonb_array_length(cehub_product.quiet_chain(r.id))
 AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements_text(cehub_product.quiet_chain(r.id)) a
 WHERE NOT cehub_product.quiet_approver(NEW.tenant_id,NEW.project_id,a::uuid)
 OR a::uuid IN (NEW.requested_by_user_id,NEW.analyzed_by_user_id,r.created_by_user_id)))
 THEN RAISE EXCEPTION 'Current baseline and quiet escalation approvals required' USING
ERRCODE='23514'; END IF;
 END LOOP;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_quiet_anchor BEFORE INSERT ON cehub_product.change_quiet_policy_anchors
 FOR EACH ROW EXECUTE FUNCTION cehub_product.guard_quiet_anchor();
CREATE TRIGGER guard_quiet_replacement BEFORE INSERT ON cehub_product.change_quiet_replacements
 FOR EACH ROW EXECUTE FUNCTION cehub_product.guard_quiet_replacement();

REVOKE ALL ON FUNCTION cehub_product.quiet_source_current(uuid,uuid,uuid,text) FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_product.quiet_chain(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_product.quiet_chain_revision(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_product.guard_quiet_anchor() FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_product.guard_quiet_replacement() FROM PUBLIC;
"""
OLD_GUARDS = """
CREATE OR REPLACE FUNCTION cehub_product.guard_quiet_vote() RETURNS trigger
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
CREATE OR REPLACE FUNCTION cehub_product.guard_quiet_ecr_approval() RETURNS trigger
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
"""


def upgrade() -> None:
    op.execute(sa.text(DDL))
    op.add_column(
        "change_quiet_votes",
        sa.Column("chain_revision", sa.Integer(), nullable=False, server_default="0"),
        schema="cehub_product",
    )
    op.drop_constraint("uq_change_quiet_vote_step", "change_quiet_votes", schema="cehub_product")
    op.create_unique_constraint(
        "uq_change_quiet_vote_step",
        "change_quiet_votes",
        ["tenant_id", "exception_id", "chain_revision", "step"],
        schema="cehub_product",
    )
    op.drop_constraint(
        op.f("ck_change_quiet_votes_shape"), "change_quiet_votes", schema="cehub_product"
    )
    op.create_check_constraint(
        op.f("ck_change_quiet_votes_shape"),
        "change_quiet_votes",
        "chain_revision>=0 AND step>0 AND outcome IN ('approved','rejected')",
        schema="cehub_product",
    )
    op.execute(sa.text(GUARDS))


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM cehub_product.change_quiet_policy_anchors) "
                "OR EXISTS(SELECT 1 FROM cehub_product.change_quiet_replacements)"
            )
        )
        .scalar()
    ):
        raise RuntimeError("Refusing to discard baseline bindings or named replacement history")
    op.execute(sa.text(OLD_GUARDS))
    op.execute("DROP TABLE cehub_product.change_quiet_replacements")
    op.execute("DROP TABLE cehub_product.change_quiet_policy_anchors")
    op.execute("DROP FUNCTION cehub_product.guard_quiet_replacement()")
    op.execute("DROP FUNCTION cehub_product.guard_quiet_anchor()")
    op.execute("DROP FUNCTION cehub_product.quiet_chain(uuid)")
    op.execute("DROP FUNCTION cehub_product.quiet_chain_revision(uuid)")
    op.execute("DROP FUNCTION cehub_product.quiet_source_current(uuid,uuid,uuid,text)")
    op.drop_constraint("uq_change_quiet_vote_step", "change_quiet_votes", schema="cehub_product")
    op.create_unique_constraint(
        "uq_change_quiet_vote_step",
        "change_quiet_votes",
        ["tenant_id", "exception_id", "step"],
        schema="cehub_product",
    )
    op.drop_constraint(
        op.f("ck_change_quiet_votes_shape"), "change_quiet_votes", schema="cehub_product"
    )
    op.create_check_constraint(
        op.f("ck_change_quiet_votes_shape"),
        "change_quiet_votes",
        "step>0 AND outcome IN ('approved','rejected')",
        schema="cehub_product",
    )
    op.drop_column("change_quiet_votes", "chain_revision", schema="cehub_product")
