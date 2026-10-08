"""Lightweight investment proposals and bounded Office source formats."""

# ruff: noqa: E501
import json

from alembic import op
from sqlalchemy import text

revision = "0424_product_proposals"
down_revision = "0423_xiaopai_conversation_search"
branch_labels = None
depends_on = None

DDL = "\nCREATE TABLE cehub_product.product_proposals (\n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tmarket_space_id UUID NOT NULL, \n\tproduct_line_id UUID, \n\towner_user_id UUID NOT NULL, \n\trequest_id UUID NOT NULL, \n\trequest_digest VARCHAR(64) NOT NULL, \n\ttitle VARCHAR(512) NOT NULL, \n\tentry_kind VARCHAR(32) NOT NULL, \n\tbrief TEXT NOT NULL, \n\tbaseline_product_id UUID, \n\tsource_file_ids JSONB NOT NULL, \n\tevidence_ids JSONB NOT NULL, \n\tdocument JSONB NOT NULL, \n\tstate VARCHAR(32) DEFAULT 'draft' NOT NULL, \n\treviewer_user_id UUID, \n\tsubmitted_version INTEGER, \n\tversion INTEGER DEFAULT '1' NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, \n\tCONSTRAINT pk_product_proposals PRIMARY KEY (id), \n\tCONSTRAINT uq_product_proposals_space_id UNIQUE (tenant_id, market_space_id, id), \n\tCONSTRAINT uq_product_proposals_tenant_id UNIQUE (tenant_id, id), \n\tCONSTRAINT uq_product_proposals_request UNIQUE (tenant_id, owner_user_id, request_id), \n\tCONSTRAINT fk_product_proposals_tenant_id_market_spaces FOREIGN KEY(tenant_id, market_space_id) REFERENCES cehub_product.market_spaces (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_product_proposals_owner FOREIGN KEY(tenant_id, owner_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_product_proposals_reviewer FOREIGN KEY(tenant_id, reviewer_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_product_proposals_tenant_id_product_nodes FOREIGN KEY(tenant_id, market_space_id, product_line_id) REFERENCES cehub_product.product_nodes (tenant_id, market_space_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT ck_product_proposals_entry_kind CHECK (entry_kind IN ('odm','new_product','iteration')), \n\tCONSTRAINT ck_product_proposals_state CHECK (state IN ('draft','in_review','approved','returned','declined')), \n\tCONSTRAINT ck_product_proposals_bounds CHECK (version>0 AND btrim(title)<>'')\n)\n\n;\n\nCREATE TABLE cehub_product.product_proposal_revisions (\n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tproposal_id UUID NOT NULL, \n\tversion INTEGER NOT NULL, \n\tactor_user_id UUID NOT NULL, \n\tai_run_id UUID, \n\torigin VARCHAR(16) NOT NULL, \n\tdocument JSONB NOT NULL, \n\tsource_catalog JSONB NOT NULL, \n\tdocument_digest VARCHAR(64) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, \n\tCONSTRAINT pk_product_proposal_revisions PRIMARY KEY (id), \n\tCONSTRAINT uq_product_proposal_revisions_tenant_id UNIQUE (tenant_id, proposal_id, version), \n\tCONSTRAINT fk_product_proposal_revisions_tenant_id_product_proposals FOREIGN KEY(tenant_id, proposal_id) REFERENCES cehub_product.product_proposals (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_product_proposal_revisions_tenant_id_users FOREIGN KEY(tenant_id, actor_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_product_proposal_revisions_tenant_id_agent_runs FOREIGN KEY(tenant_id, ai_run_id) REFERENCES cehub_ai.agent_runs (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT ck_product_proposal_revisions_origin CHECK (origin IN ('human','ai_assisted') AND version>0)\n)\n\n;\n\nCREATE TABLE cehub_product.product_proposal_decisions (\n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tproposal_id UUID NOT NULL, \n\tproposal_version INTEGER NOT NULL, \n\tactor_user_id UUID NOT NULL, \n\toutcome VARCHAR(16) NOT NULL, \n\tselected_option VARCHAR(16), \n\trationale TEXT NOT NULL, \n\taccepted_unknowns TEXT NOT NULL, \n\tsnapshot JSONB NOT NULL, \n\tsnapshot_digest VARCHAR(64) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, \n\tCONSTRAINT pk_product_proposal_decisions PRIMARY KEY (id), \n\tCONSTRAINT uq_product_proposal_decisions_tenant_id UNIQUE (tenant_id, proposal_id, proposal_version), \n\tCONSTRAINT fk_product_proposal_decisions_tenant_id_product_proposals FOREIGN KEY(tenant_id, proposal_id) REFERENCES cehub_product.product_proposals (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_product_proposal_decisions_tenant_id_users FOREIGN KEY(tenant_id, actor_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT ck_product_proposal_decisions_outcome CHECK (outcome IN ('approved','returned','declined'))\n)\n\n;"
PRIOR_FILE_GUARD = "\nCREATE OR REPLACE FUNCTION cehub_product.guard_product_source_file() RETURNS trigger\nLANGUAGE plpgsql SET search_path=pg_catalog AS $$\nBEGIN\n IF TG_OP='DELETE' THEN RAISE EXCEPTION 'RFQ file history is retained; revoke the reference'; END IF;\n IF NEW.product_line_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM cehub_product.product_nodes WHERE tenant_id=NEW.tenant_id AND market_space_id=NEW.market_space_id AND id=NEW.product_line_id AND level='line')\n THEN RAISE EXCEPTION 'File line must belong to the market space'; END IF;\n IF NEW.object_key IS DISTINCT FROM 'tenants/'||NEW.tenant_id::text||'/private-product-files/'||NEW.market_space_id::text||'/'||NEW.id::text\n  OR NEW.parser_version<>'product-rfq-pdf-xlsx.v1'\n  OR NEW.media_type NOT IN ('application/pdf','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')\n THEN RAISE EXCEPTION 'File storage and parser identity must be server-bound'; END IF;\n IF TG_OP='INSERT' THEN\n  IF NEW.version<>1 OR NEW.status<>'awaiting_upload' OR NEW.fragments<>'[]'::jsonb OR NEW.extraction_metadata<>'{}'::jsonb OR NEW.revoked_at IS NOT NULL\n  THEN RAISE EXCEPTION 'File starts with metadata only'; END IF;\n ELSE\n  IF (NEW.id,NEW.tenant_id,NEW.market_space_id,NEW.product_line_id,NEW.uploaded_by_user_id,NEW.request_id,NEW.request_digest,NEW.filename,NEW.media_type,NEW.classification,NEW.size_bytes,NEW.sha256,NEW.object_key,NEW.parser_version,NEW.created_at,NEW.version)\n   IS DISTINCT FROM (OLD.id,OLD.tenant_id,OLD.market_space_id,OLD.product_line_id,OLD.uploaded_by_user_id,OLD.request_id,OLD.request_digest,OLD.filename,OLD.media_type,OLD.classification,OLD.size_bytes,OLD.sha256,OLD.object_key,OLD.parser_version,OLD.created_at,OLD.version+1)\n  THEN RAISE EXCEPTION 'File identity is immutable and version must advance once'; END IF;\n  IF OLD.revoked_at IS NOT NULL THEN RAISE EXCEPTION 'Revoked file cannot be changed'; END IF;\n  IF OLD.status IN ('extracted','ocr_required') AND (NEW.status,NEW.fragments,NEW.extraction_metadata,NEW.error_code) IS DISTINCT FROM (OLD.status,OLD.fragments,OLD.extraction_metadata,OLD.error_code)\n  THEN RAISE EXCEPTION 'Parsed source fragments are immutable'; END IF;\n  IF OLD.status='awaiting_upload' AND NEW.status NOT IN ('awaiting_upload','uploaded')\n   OR OLD.status IN ('uploaded','failed') AND NEW.status NOT IN ('uploaded','failed','extracted','ocr_required')\n  THEN RAISE EXCEPTION 'Invalid file state transition'; END IF;\n END IF;\n IF (NEW.status='extracted' AND jsonb_array_length(NEW.fragments)=0)\n  OR (NEW.status<>'extracted' AND NEW.fragments<>'[]'::jsonb)\n THEN RAISE EXCEPTION 'Extraction status must reflect actual parsed fragments'; END IF;\n RETURN NEW;\nEND $$;\n"
FILE_GUARD = "\nCREATE OR REPLACE FUNCTION cehub_product.guard_product_source_file() RETURNS trigger\nLANGUAGE plpgsql SET search_path=pg_catalog AS $$\nBEGIN\n IF TG_OP='DELETE' THEN RAISE EXCEPTION 'RFQ file history is retained; revoke the reference'; END IF;\n IF NEW.product_line_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM cehub_product.product_nodes WHERE tenant_id=NEW.tenant_id AND market_space_id=NEW.market_space_id AND id=NEW.product_line_id AND level='line')\n THEN RAISE EXCEPTION 'File line must belong to the market space'; END IF;\n IF NEW.object_key IS DISTINCT FROM 'tenants/'||NEW.tenant_id::text||'/private-product-files/'||NEW.market_space_id::text||'/'||NEW.id::text\n  OR NEW.parser_version NOT IN ('product-rfq-pdf-xlsx.v1','product-office.v2')\n  OR NEW.media_type NOT IN ('application/pdf','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','application/vnd.openxmlformats-officedocument.wordprocessingml.document','application/vnd.openxmlformats-officedocument.presentationml.presentation','application/msword','application/vnd.ms-powerpoint','application/vnd.ms-excel')\n THEN RAISE EXCEPTION 'File storage and parser identity must be server-bound'; END IF;\n IF TG_OP='INSERT' THEN\n  IF NEW.version<>1 OR NEW.status<>'awaiting_upload' OR NEW.fragments<>'[]'::jsonb OR NEW.extraction_metadata<>'{}'::jsonb OR NEW.revoked_at IS NOT NULL\n  THEN RAISE EXCEPTION 'File starts with metadata only'; END IF;\n ELSE\n  IF (NEW.id,NEW.tenant_id,NEW.market_space_id,NEW.product_line_id,NEW.uploaded_by_user_id,NEW.request_id,NEW.request_digest,NEW.filename,NEW.media_type,NEW.classification,NEW.size_bytes,NEW.sha256,NEW.object_key,NEW.parser_version,NEW.created_at,NEW.version)\n   IS DISTINCT FROM (OLD.id,OLD.tenant_id,OLD.market_space_id,OLD.product_line_id,OLD.uploaded_by_user_id,OLD.request_id,OLD.request_digest,OLD.filename,OLD.media_type,OLD.classification,OLD.size_bytes,OLD.sha256,OLD.object_key,OLD.parser_version,OLD.created_at,OLD.version+1)\n  THEN RAISE EXCEPTION 'File identity is immutable and version must advance once'; END IF;\n  IF OLD.revoked_at IS NOT NULL THEN RAISE EXCEPTION 'Revoked file cannot be changed'; END IF;\n  IF OLD.status IN ('extracted','ocr_required') AND (NEW.status,NEW.fragments,NEW.extraction_metadata,NEW.error_code) IS DISTINCT FROM (OLD.status,OLD.fragments,OLD.extraction_metadata,OLD.error_code)\n  THEN RAISE EXCEPTION 'Parsed source fragments are immutable'; END IF;\n  IF OLD.status='awaiting_upload' AND NEW.status NOT IN ('awaiting_upload','uploaded')\n   OR OLD.status IN ('uploaded','failed') AND NEW.status NOT IN ('uploaded','failed','extracted','ocr_required')\n  THEN RAISE EXCEPTION 'Invalid file state transition'; END IF;\n END IF;\n IF (NEW.status='extracted' AND jsonb_array_length(NEW.fragments)=0)\n  OR (NEW.status<>'extracted' AND NEW.fragments<>'[]'::jsonb)\n THEN RAISE EXCEPTION 'Extraction status must reflect actual parsed fragments'; END IF;\n RETURN NEW;\nEND $$;\n"

GUARD = r"""
CREATE FUNCTION cehub_product.guard_proposal_history() RETURNS trigger
 LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN RAISE EXCEPTION 'Proposal history is immutable'; END $$;
CREATE TRIGGER proposal_revision_immutable BEFORE UPDATE OR DELETE
 ON cehub_product.product_proposal_revisions FOR EACH ROW
 EXECUTE FUNCTION cehub_product.guard_proposal_history();
CREATE TRIGGER proposal_decision_immutable BEFORE UPDATE OR DELETE
 ON cehub_product.product_proposal_decisions FOR EACH ROW
 EXECUTE FUNCTION cehub_product.guard_proposal_history();
CREATE FUNCTION cehub_product.guard_proposal_current() RETURNS trigger
 LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Proposal history is retained'; END IF;
 IF NEW.product_line_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM cehub_product.product_nodes
  WHERE tenant_id=NEW.tenant_id AND market_space_id=NEW.market_space_id
  AND id=NEW.product_line_id AND level='line') THEN RAISE EXCEPTION 'Proposal line is invalid'; END IF;
 IF TG_OP='INSERT' THEN
  IF NEW.state<>'draft' OR NEW.version<>1 OR NEW.reviewer_user_id IS NOT NULL
   OR NEW.submitted_version IS NOT NULL THEN RAISE EXCEPTION 'Proposal starts as draft'; END IF;
 ELSE
  IF (NEW.id,NEW.tenant_id,NEW.market_space_id,NEW.product_line_id,NEW.owner_user_id,
    NEW.request_id,NEW.request_digest,NEW.entry_kind,NEW.brief,NEW.baseline_product_id,
    NEW.source_file_ids,NEW.evidence_ids,NEW.created_at,NEW.version)
   IS DISTINCT FROM (OLD.id,OLD.tenant_id,OLD.market_space_id,OLD.product_line_id,OLD.owner_user_id,
    OLD.request_id,OLD.request_digest,OLD.entry_kind,OLD.brief,OLD.baseline_product_id,
    OLD.source_file_ids,OLD.evidence_ids,OLD.created_at,OLD.version+1)
   THEN RAISE EXCEPTION 'Proposal identity is immutable and version advances once'; END IF;
  IF OLD.state IN ('approved','declined') THEN RAISE EXCEPTION 'Decided proposal is immutable'; END IF;
  IF OLD.state='in_review' AND (NEW.document IS DISTINCT FROM OLD.document
   OR NEW.state NOT IN ('approved','returned','declined')) THEN RAISE EXCEPTION 'Review input is fixed'; END IF;
  IF OLD.state IN ('draft','returned') AND NEW.state NOT IN ('draft','in_review')
   THEN RAISE EXCEPTION 'Proposal decision needs submitted review'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER proposal_current_guard BEFORE INSERT OR UPDATE OR DELETE
 ON cehub_product.product_proposals FOR EACH ROW
 EXECUTE FUNCTION cehub_product.guard_proposal_current();
REVOKE ALL ON cehub_product.product_proposals,cehub_product.product_proposal_revisions,
 cehub_product.product_proposal_decisions FROM PUBLIC,pdos_agent;
REVOKE ALL ON FUNCTION cehub_product.guard_proposal_current(),
 cehub_product.guard_proposal_history() FROM PUBLIC,pdos_agent;
"""


SHAPE = "context_version='product-proposal-v1' AND agent_key='ai_chat' AND scope_kind='tenant' AND project_id IS NULL AND market_space_id IS NULL AND subscription_id IS NULL AND first_event_row_id IS NULL AND last_event_row_id IS NULL AND event_count=0 AND event_row_ids='[]'::jsonb AND request_id IS NOT NULL AND requested_by_user_id IS NOT NULL AND status IN ('running','succeeded','degraded','failed')"

AI_GUARD = r"""
CREATE FUNCTION cehub_ai.guard_product_proposal_run() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE s jsonb; p cehub_product.product_proposals%ROWTYPE;
BEGIN
 IF TG_OP='UPDATE' AND OLD.context_version='product-proposal-v1'
  AND NEW.context_version IS DISTINCT FROM OLD.context_version THEN
  RAISE EXCEPTION 'Proposal run version is immutable'; END IF;
 IF NEW.context_version<>'product-proposal-v1' THEN RETURN NEW; END IF;
 s:=NEW.run_context->'proposal_source';
 SELECT * INTO p FROM cehub_product.product_proposals WHERE tenant_id=NEW.tenant_id
  AND id::text=s->'proposal'->>'id';
 IF p.id IS NULL OR NEW.requested_by_user_id IS DISTINCT FROM p.owner_user_id
  OR NEW.agent_key<>'ai_chat' OR NEW.project_id IS NOT NULL OR NEW.scope_kind<>'tenant'
  OR s->>'actor_id' IS DISTINCT FROM NEW.requested_by_user_id::text
  OR coalesce(s->>'digest','') !~ '^[a-f0-9]{64}$'
  THEN RAISE EXCEPTION 'Proposal run requires fixed actor and source'; END IF;
 IF TG_OP='INSERT' AND (p.state NOT IN ('draft','returned')
  OR p.version<>(s->'proposal'->>'version')::int)
  THEN RAISE EXCEPTION 'Proposal run input is stale'; END IF;
 IF TG_OP='UPDATE' AND (NEW.id,NEW.tenant_id,NEW.scope_kind,NEW.agent_key,
  NEW.requested_by_user_id,NEW.run_context->'proposal_source',NEW.run_context->'proposal_request_digest')
  IS DISTINCT FROM (OLD.id,OLD.tenant_id,OLD.scope_kind,OLD.agent_key,
  OLD.requested_by_user_id,OLD.run_context->'proposal_source',OLD.run_context->'proposal_request_digest')
  THEN RAISE EXCEPTION 'Proposal run source is immutable'; END IF;
 IF TG_OP='UPDATE' AND OLD.status<>'running' AND NEW IS DISTINCT FROM OLD
  THEN RAISE EXCEPTION 'Completed proposal run is immutable'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER product_proposal_run_guard BEFORE INSERT OR UPDATE ON cehub_ai.agent_runs
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.guard_product_proposal_run();
REVOKE ALL ON FUNCTION cehub_ai.guard_product_proposal_run() FROM PUBLIC,pdos_agent;
ALTER FUNCTION cehub_ai.application_authorization_is_current(uuid)
 RENAME TO application_pre_proposal_authorization_is_current;
CREATE FUNCTION cehub_ai.application_authorization_is_current(wanted_run uuid)
RETURNS boolean LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cehub_ai.agent_runs WHERE id=wanted_run
  AND context_version='product-proposal-v1') THEN EXISTS(
  SELECT 1 FROM cehub_ai.agent_runs r
  JOIN cehub_ai.application_authorizations a ON a.tenant_id=r.tenant_id AND a.run_id=r.id
  JOIN cehub_core.users u ON u.tenant_id=r.tenant_id AND u.id=a.principal_id
  JOIN cehub_core.tenants t ON t.id=r.tenant_id
  JOIN cehub_product.product_proposals p ON p.tenant_id=r.tenant_id
   AND p.id::text=r.run_context->'proposal_source'->'proposal'->>'id'
  WHERE r.id=wanted_run AND r.status='running' AND r.agent_key='ai_chat'
   AND r.requested_by_user_id=u.id AND p.owner_user_id=u.id
   AND p.state IN ('draft','returned')
   AND p.version=(r.run_context->'proposal_source'->'proposal'->>'version')::int
   AND a.expires_at>clock_timestamp() AND u.is_active AND t.status='active'
   AND u.role IN ('owner','admin','product_manager','project_manager','engineer','quality')
   AND u.role=a.pins->>'role' AND u.auth_version=(a.pins->>'auth_version')::int
   AND a.pins->>'action'='product_work.contribute'
   AND a.body->>'purpose'='product_proposal'
   AND a.body->>'principal_id'=u.id::text AND a.body->>'run_id'=r.id::text
   AND a.body->>'tenant_id'=r.tenant_id::text
   AND a.body->'scope'=jsonb_build_object('kind','tenant','ref_id',r.tenant_id::text)
   AND jsonb_array_length(a.body->'sources')=1
   AND a.body->'sources' @> jsonb_build_array(jsonb_build_object('kind','product_proposal',
    'ref_id',p.id::text,'tenant_id',r.tenant_id::text,
    'digest',r.run_context->'proposal_source'->>'digest'))
   AND cehub_ai.require_product_conversation_actor(p.tenant_id,p.market_space_id,p.product_line_id,u.id)
 ) ELSE cehub_ai.application_pre_proposal_authorization_is_current(wanted_run) END;
$$;
REVOKE ALL ON FUNCTION cehub_ai.application_authorization_is_current(uuid) FROM PUBLIC;
"""


def proposal_constraints(add: bool) -> None:
    c = op.get_bind()
    for name in ("ck_agent_runs_scope", "ck_agent_runs_event_bounds_consistent"):
        prior = c.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid='cehub_ai.agent_runs'::regclass AND conname=:name"
            ),
            {"name": name},
        ).scalar_one()
        comment = c.execute(
            text(
                "SELECT obj_description(oid,'pg_constraint') FROM pg_constraint WHERE conrelid='cehub_ai.agent_runs'::regclass AND conname=:name"
            ),
            {"name": name},
        ).scalar_one()
        if add:
            expression = "(" + prior[len("CHECK (") : -1] + ") OR (" + SHAPE + ") IS TRUE"
            new_comment = json.dumps({"definition": prior, "comment": comment})
        else:
            if not comment or not comment.startswith("{"):
                raise RuntimeError("Missing saved pre-proposal constraint")
            saved = json.loads(comment)
            expression = saved["definition"][len("CHECK (") : -1]
            new_comment = saved["comment"]
        op.drop_constraint(op.f(name), "agent_runs", schema="cehub_ai")
        op.create_check_constraint(op.f(name), "agent_runs", expression, schema="cehub_ai")
        if new_comment is not None:
            c.execute(
                text(
                    "COMMENT ON CONSTRAINT "
                    + name
                    + " ON cehub_ai.agent_runs IS '"
                    + new_comment.replace("'", "''")
                    + "'"
                )
            )


def template_guard(add: bool) -> None:
    definition = (
        op.get_bind()
        .execute(
            text("SELECT pg_get_functiondef('cehub_ai.guard_tenant_template_run()'::regprocedure)")
        )
        .scalar_one()
    )
    prior = "IF NEW.scope_kind<>'tenant' OR NEW.context_version='xiaopai-conversation-v1' THEN RETURN NEW; END IF;"
    updated = "IF NEW.scope_kind<>'tenant' OR NEW.context_version IN ('xiaopai-conversation-v1','product-proposal-v1') THEN RETURN NEW; END IF;"
    assert (prior if add else updated) in definition
    op.execute(definition.replace(prior if add else updated, updated if add else prior, 1))


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARD)
    op.execute(FILE_GUARD)
    proposal_constraints(True)
    op.execute(AI_GUARD)
    template_guard(True)


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM cehub_product.product_proposals) OR EXISTS(SELECT 1 FROM cehub_product.product_source_files WHERE parser_version='product-office.v2') THEN RAISE EXCEPTION 'Cannot discard proposal or Office source history'; END IF; END $$;"
    )
    op.execute(
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM cehub_ai.agent_runs WHERE context_version='product-proposal-v1') THEN RAISE EXCEPTION 'Cannot discard proposal run history'; END IF; END $$;"
    )
    op.execute(
        "DROP TRIGGER product_proposal_run_guard ON cehub_ai.agent_runs; DROP FUNCTION cehub_ai.guard_product_proposal_run();"
    )
    op.execute(
        "DROP FUNCTION cehub_ai.application_authorization_is_current(uuid); ALTER FUNCTION cehub_ai.application_pre_proposal_authorization_is_current(uuid) RENAME TO application_authorization_is_current;"
    )
    template_guard(False)
    proposal_constraints(False)
    for table in ("product_proposal_decisions", "product_proposal_revisions", "product_proposals"):
        op.execute("DROP TABLE cehub_product." + table)
    op.execute(
        "DROP FUNCTION cehub_product.guard_proposal_current(); DROP FUNCTION cehub_product.guard_proposal_history();"
    )
    op.execute(PRIOR_FILE_GUARD)
