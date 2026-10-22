"""Frozen SQL: unambiguous receipt operation and explicit critical-review watermark."""

# ruff: noqa: E501

ATOM_SQL = """CREATE OR REPLACE FUNCTION kernel_skill_review_atom() RETURNS trigger LANGUAGE plpgsql
      SECURITY DEFINER SET search_path=public,pg_temp AS $$
      DECLARE review_operation text; person uuid; event_type text;
      BEGIN
        review_operation=CASE WHEN TG_TABLE_NAME='agent_skill_review_batches' THEN 'ai.skill.review.record' ELSE 'ai.skill.qualify' END;
        person=COALESCE((to_jsonb(NEW)->>'reviewed_by')::uuid,(to_jsonb(NEW)->>'decided_by')::uuid);
        event_type=CASE WHEN TG_TABLE_NAME='agent_skill_review_batches' THEN 'ai.skill_review_recorded' ELSE 'ai.skill_qualified' END;
        IF NOT EXISTS(SELECT 1 FROM action_receipts r JOIN audit_entries a ON a.receipt_id=r.id AND a.tenant_id=r.tenant_id
          JOIN outbox_events o ON o.receipt_id=r.id AND o.tenant_id=r.tenant_id
          JOIN confirmations c ON c.id=r.confirmation_id AND c.tenant_id=r.tenant_id
          WHERE r.tenant_id=NEW.tenant_id AND r.id=NEW.receipt_id AND r.operation=review_operation
          AND r.actor_id=person AND r.requester_id=person AND r.agent_run_id IS NULL AND r.run_id IS NULL
          AND r.subject_id=NEW.id AND r.subject_revision=1 AND c.consumed AND c.actor_id=person
          AND c.operation=review_operation AND o.type=event_type)
        THEN RAISE EXCEPTION 'Human skill review/decision receipt atom required'; END IF;
        RETURN NEW;
      END $$"""

GUARD_SQL = """CREATE OR REPLACE FUNCTION kernel_skill_qualification_guard() RETURNS trigger LANGUAGE plpgsql
      SECURITY DEFINER SET search_path=public,pg_temp AS $$
      BEGIN
        IF scope_actor() IS NULL OR pg_has_role(session_user,'pdos_next_owner','MEMBER') THEN RETURN NEW; END IF;
        IF TG_OP='UPDATE' AND NOT (NEW.pilot IS DISTINCT FROM OLD.pilot OR NEW.qualification_revoked IS DISTINCT FROM OLD.qualification_revoked OR NEW.qualified_skill_version IS DISTINCT FROM OLD.qualified_skill_version OR NEW.qualified_model_version IS DISTINCT FROM OLD.qualified_model_version OR NEW.qualified_skill_digest IS DISTINCT FROM OLD.qualified_skill_digest OR NEW.qualified_tool_digest IS DISTINCT FROM OLD.qualified_tool_digest OR NEW.qualified_model_digest IS DISTINCT FROM OLD.qualified_model_digest OR NEW.review_case_refs IS DISTINCT FROM OLD.review_case_refs OR NEW.quality_paused IS DISTINCT FROM OLD.quality_paused OR NEW.reviewed_by IS DISTINCT FROM OLD.reviewed_by OR NEW.qualification_id IS DISTINCT FROM OLD.qualification_id OR NEW.quality_review_id IS DISTINCT FROM OLD.quality_review_id OR NEW.quality_paused_at IS DISTINCT FROM OLD.quality_paused_at) THEN RETURN NEW; END IF;
        IF TG_OP='INSERT' AND NEW.qualification_id IS NULL AND NEW.quality_review_id IS NULL
          AND NEW.reviewed_by IS NULL AND NOT NEW.pilot AND NOT NEW.quality_paused
          AND NEW.qualified_skill_digest IS NULL AND NEW.qualified_tool_digest IS NULL
          AND NEW.qualified_model_digest IS NULL AND NEW.qualified_skill_version IS NULL
          AND NEW.qualified_model_version IS NULL AND NEW.review_case_refs='[]'::jsonb
          AND NOT NEW.qualification_revoked THEN RETURN NEW; END IF;
        IF EXISTS(SELECT 1 FROM agent_skill_qualifications q WHERE q.tenant_id=NEW.tenant_id
          AND q.id=NEW.qualification_id AND q.decided_by=scope_actor() AND q.skill_key=NEW.skill_key
          AND q.receipt_id=NEW.receipt_id AND q.after_snapshot=jsonb_build_object('pilot',to_jsonb(NEW)->'pilot','qualification_revoked',to_jsonb(NEW)->'qualification_revoked','qualified_skill_version',to_jsonb(NEW)->'qualified_skill_version','qualified_model_version',to_jsonb(NEW)->'qualified_model_version','qualified_skill_digest',to_jsonb(NEW)->'qualified_skill_digest','qualified_tool_digest',to_jsonb(NEW)->'qualified_tool_digest','qualified_model_digest',to_jsonb(NEW)->'qualified_model_digest','review_case_refs',to_jsonb(NEW)->'review_case_refs','quality_paused',to_jsonb(NEW)->'quality_paused','reviewed_by',to_jsonb(NEW)->'reviewed_by','qualification_id',to_jsonb(NEW)->'qualification_id','quality_review_id',to_jsonb(NEW)->'quality_review_id','revision',to_jsonb(NEW)->'revision','quality_paused_at',to_jsonb(NEW)->'quality_paused_at'))
          THEN RETURN NEW; END IF;
        IF TG_OP='UPDATE' AND NEW.quality_paused AND NEW.quality_review_id IS DISTINCT FROM OLD.quality_review_id
          AND NEW.revision=OLD.revision+1 AND NEW.quality_paused_at IS NOT NULL
          AND (to_jsonb(NEW)-ARRAY['quality_paused','quality_review_id','quality_paused_at','revision','receipt_id'])=
              (to_jsonb(OLD)-ARRAY['quality_paused','quality_review_id','quality_paused_at','revision','receipt_id'])
          AND EXISTS(SELECT 1 FROM agent_skill_review_batches b WHERE b.tenant_id=NEW.tenant_id
            AND b.id=NEW.quality_review_id AND b.receipt_id=NEW.receipt_id AND b.reviewed_by=scope_actor()
            AND b.skill_key=NEW.skill_key AND b.skill_digest=NEW.qualified_skill_digest
            AND b.tool_digest=NEW.qualified_tool_digest AND b.model_digest=NEW.qualified_model_digest
            AND EXISTS(SELECT 1 FROM jsonb_array_elements(b.cases) c WHERE c->>'severity'='critical'))
          THEN RETURN NEW; END IF;
        RAISE EXCEPTION 'Named qualification or recorded critical review required';
      END $$"""

PREVIOUS_GUARD_SQL = """CREATE OR REPLACE FUNCTION kernel_skill_qualification_guard() RETURNS trigger LANGUAGE plpgsql
      SECURITY DEFINER SET search_path=public,pg_temp AS $$
      BEGIN
        IF scope_actor() IS NULL OR pg_has_role(session_user,'pdos_next_owner','MEMBER') THEN RETURN NEW; END IF;
        IF TG_OP='UPDATE' AND NOT (NEW.pilot IS DISTINCT FROM OLD.pilot OR NEW.qualification_revoked IS DISTINCT FROM OLD.qualification_revoked OR NEW.qualified_skill_version IS DISTINCT FROM OLD.qualified_skill_version OR NEW.qualified_model_version IS DISTINCT FROM OLD.qualified_model_version OR NEW.qualified_skill_digest IS DISTINCT FROM OLD.qualified_skill_digest OR NEW.qualified_tool_digest IS DISTINCT FROM OLD.qualified_tool_digest OR NEW.qualified_model_digest IS DISTINCT FROM OLD.qualified_model_digest OR NEW.review_case_refs IS DISTINCT FROM OLD.review_case_refs OR NEW.quality_paused IS DISTINCT FROM OLD.quality_paused OR NEW.reviewed_by IS DISTINCT FROM OLD.reviewed_by OR NEW.qualification_id IS DISTINCT FROM OLD.qualification_id OR NEW.quality_review_id IS DISTINCT FROM OLD.quality_review_id) THEN RETURN NEW; END IF;
        IF TG_OP='INSERT' AND NEW.qualification_id IS NULL AND NEW.quality_review_id IS NULL
          AND NEW.reviewed_by IS NULL AND NOT NEW.pilot AND NOT NEW.quality_paused
          AND NEW.qualified_skill_digest IS NULL AND NEW.qualified_tool_digest IS NULL
          AND NEW.qualified_model_digest IS NULL AND NEW.qualified_skill_version IS NULL
          AND NEW.qualified_model_version IS NULL AND NEW.review_case_refs='[]'::jsonb
          AND NOT NEW.qualification_revoked THEN RETURN NEW; END IF;
        IF EXISTS(SELECT 1 FROM agent_skill_qualifications q WHERE q.tenant_id=NEW.tenant_id
          AND q.id=NEW.qualification_id AND q.decided_by=scope_actor() AND q.skill_key=NEW.skill_key
          AND q.receipt_id=NEW.receipt_id AND q.after_snapshot=jsonb_build_object('pilot',to_jsonb(NEW)->'pilot','qualification_revoked',to_jsonb(NEW)->'qualification_revoked','qualified_skill_version',to_jsonb(NEW)->'qualified_skill_version','qualified_model_version',to_jsonb(NEW)->'qualified_model_version','qualified_skill_digest',to_jsonb(NEW)->'qualified_skill_digest','qualified_tool_digest',to_jsonb(NEW)->'qualified_tool_digest','qualified_model_digest',to_jsonb(NEW)->'qualified_model_digest','review_case_refs',to_jsonb(NEW)->'review_case_refs','quality_paused',to_jsonb(NEW)->'quality_paused','reviewed_by',to_jsonb(NEW)->'reviewed_by','qualification_id',to_jsonb(NEW)->'qualification_id','quality_review_id',to_jsonb(NEW)->'quality_review_id','revision',to_jsonb(NEW)->'revision'))
          THEN RETURN NEW; END IF;
        IF TG_OP='UPDATE' AND NEW.quality_paused AND NEW.quality_review_id IS DISTINCT FROM OLD.quality_review_id
          AND NEW.revision=OLD.revision+1
          AND (to_jsonb(NEW)-ARRAY['quality_paused','quality_review_id','revision','receipt_id'])=
              (to_jsonb(OLD)-ARRAY['quality_paused','quality_review_id','revision','receipt_id'])
          AND EXISTS(SELECT 1 FROM agent_skill_review_batches b WHERE b.tenant_id=NEW.tenant_id
            AND b.id=NEW.quality_review_id AND b.receipt_id=NEW.receipt_id AND b.reviewed_by=scope_actor()
            AND b.skill_key=NEW.skill_key AND b.skill_digest=NEW.qualified_skill_digest
            AND b.tool_digest=NEW.qualified_tool_digest AND b.model_digest=NEW.qualified_model_digest
            AND EXISTS(SELECT 1 FROM jsonb_array_elements(b.cases) c WHERE c->>'severity'='critical'))
          THEN RETURN NEW; END IF;
        RAISE EXCEPTION 'Named qualification or recorded critical review required';
      END $$"""
