"""Source-bound human meeting review and independent atomic meeting creation."""

from alembic import op

revision = "0281_meeting_planning_review"
down_revision = "0280_meeting_planning_runs"
branch_labels = None
depends_on = None

REVIEW = (
    "CREATE OR REPLACE FUNCTION cehub_ai.guard_meeting_planning_findin"
    "g() RETURNS trigger LANGUAGE plpgsql AS $$\nDECLARE r cehub_ai.age"
    "nt_runs; cp cehub_ai.application_result_checkpoints; m cehub_proj"
    "ect.meetings;\nBEGIN\n IF TG_OP='UPDATE' AND OLD.finding_type='meet"
    "ing_plan' THEN\n  IF NEW IS NOT DISTINCT FROM OLD THEN RETURN NEW;"
    " END IF;\n  SELECT * INTO r FROM cehub_ai.agent_runs WHERE tenant_"
    "id=OLD.tenant_id AND id=OLD.run_id;\n  IF OLD.status='accepted' AN"
    "D NEW.status='applied' THEN\n   IF (to_jsonb(NEW)-ARRAY['status','"
    "applied_by_user_id','applied_at','updated_at',\n       'applied_en"
    "tity_type','applied_entity_id']) IS DISTINCT FROM\n      (to_jsonb"
    "(OLD)-ARRAY['status','applied_by_user_id','applied_at','updated_a"
    "t',\n       'applied_entity_type','applied_entity_id'])\n    OR NEW"
    ".applied_by_user_id IS DISTINCT FROM OLD.reviewed_by_user_id\n    "
    "OR NEW.applied_by_user_id IS DISTINCT FROM r.requested_by_user_id"
    "\n    OR NEW.applied_entity_type IS DISTINCT FROM 'meeting' THEN\n "
    "   RAISE EXCEPTION 'Meeting application must preserve the accepte"
    "d human plan'; END IF;\n   SELECT * INTO m FROM cehub_project.meet"
    "ings WHERE tenant_id=NEW.tenant_id\n    AND project_id=NEW.project"
    "_id AND id=NEW.applied_entity_id;\n   IF m.id IS NULL OR m.source<"
    ">'agent_drafted' OR m.status<>'scheduled'\n    OR m.deleted_at IS "
    "NOT NULL OR m.organizer_user_id IS DISTINCT FROM NEW.applied_by_u"
    "ser_id\n    OR m.title IS DISTINCT FROM NEW.accepted_payload->'pla"
    "n'->>'title'\n    OR m.meeting_type IS DISTINCT FROM NEW.accepted_"
    "payload->'plan'->>'meeting_type'\n    OR m.scheduled_start_at IS D"
    "ISTINCT FROM\n      (NEW.accepted_payload->'plan'->>'scheduled_sta"
    "rt_at')::timestamptz\n    OR m.scheduled_end_at IS DISTINCT FROM\n "
    "     (NEW.accepted_payload->'plan'->>'scheduled_end_at')::timesta"
    "mptz\n    OR m.scheduled_start_at<=NEW.applied_at\n    OR (SELECT c"
    "ount(*) FROM cehub_project.meeting_agenda_items a\n      WHERE a.t"
    "enant_id=NEW.tenant_id AND a.meeting_id=m.id) IS DISTINCT FROM\n  "
    "     (jsonb_array_length(NEW.accepted_payload->'plan'->'agenda')+"
    "1)::bigint\n    OR NOT EXISTS(SELECT 1 FROM cehub_project.meeting_"
    "agenda_items a\n      WHERE a.tenant_id=NEW.tenant_id AND a.meetin"
    "g_id=m.id AND a.position=1\n       AND a.title='会议目的' AND a.item_k"
    "ind='information'\n       AND a.detail=NEW.accepted_payload->'plan"
    "'->>'purpose')\n    OR EXISTS(SELECT 1 FROM jsonb_array_elements(N"
    "EW.accepted_payload->'plan'->'agenda')\n      WITH ORDINALITY AS x"
    "(item,n) WHERE NOT EXISTS(\n       SELECT 1 FROM cehub_project.mee"
    "ting_agenda_items a\n       WHERE a.tenant_id=NEW.tenant_id AND a."
    "meeting_id=m.id AND a.position=x.n+1\n        AND a.title=x.item->"
    ">'title' AND a.item_kind='topic'\n        AND a.detail=(x.item->>'"
    "detail')||E'\\n\\n期望产出：'||(x.item->>'expected_output')\n        AND "
    "a.owner_user_id IS NOT DISTINCT FROM (x.item->>'owner_user_id')::"
    "uuid)) THEN\n    RAISE EXCEPTION 'Meeting application requires the"
    " actual meeting and exact human agenda'; END IF;\n   IF (SELECT js"
    "onb_object_agg(p.user_id::text,p.participation)\n       FROM cehub"
    "_project.meeting_participants p\n       WHERE p.tenant_id=NEW.tena"
    "nt_id AND p.meeting_id=m.id) IS DISTINCT FROM\n      (coalesce((SE"
    "LECT jsonb_object_agg(p->>'user_id',p->>'participation')\n        "
    "FROM jsonb_array_elements(NEW.accepted_payload->'plan'->'particip"
    "ants') p),'{}'::jsonb)\n       ||jsonb_build_object(NEW.applied_by"
    "_user_id::text,'organizer')) THEN\n    RAISE EXCEPTION 'Meeting ap"
    "plication requires the exact accepted roster'; END IF;\n   RETURN "
    "NEW;\n  END IF;\n  IF OLD.status<>'pending_review' OR NEW.status NO"
    "T IN ('accepted','rejected')\n   OR (to_jsonb(NEW)-ARRAY['status',"
    "'reviewed_by_user_id','reviewed_at',\n      'review_comment','acce"
    "pted_payload','updated_at']) IS DISTINCT FROM\n      (to_jsonb(OLD"
    ")-ARRAY['status','reviewed_by_user_id','reviewed_at',\n      'revi"
    "ew_comment','accepted_payload','updated_at'])\n   OR NEW.reviewed_"
    "by_user_id IS DISTINCT FROM r.requested_by_user_id\n   OR coalesce"
    "(btrim(NEW.review_comment),'')='' THEN\n   RAISE EXCEPTION 'Meetin"
    "g original result and completed human review are immutable'; END "
    "IF;\n  IF NEW.status='accepted' AND (\n   NEW.accepted_payload->>'v"
    "ersion' IS DISTINCT FROM 'meeting-plan-human-v1'\n   OR NEW.accept"
    "ed_payload->>'brief_id' IS DISTINCT FROM\n      r.run_context->>'m"
    "eeting_planning_brief_id'\n   OR NEW.accepted_payload->>'source_di"
    "gest' IS DISTINCT FROM\n      r.run_context->>'meeting_planning_so"
    "urce_digest'\n   OR NEW.accepted_payload->>'organizer_user_id' IS "
    "DISTINCT FROM r.requested_by_user_id::text\n   OR jsonb_typeof(NEW"
    ".accepted_payload->'plan') IS DISTINCT FROM 'object'\n   OR jsonb_"
    "typeof(NEW.accepted_payload->'changes') IS DISTINCT FROM 'array'\n"
    "  ) THEN RAISE EXCEPTION 'Meeting acceptance requires its source-"
    "bound human plan'; END IF;\n  RETURN NEW;\n END IF;\n IF NEW.finding"
    "_type<>'meeting_plan' THEN RETURN NEW; END IF;\n SELECT * INTO r F"
    "ROM cehub_ai.agent_runs WHERE tenant_id=NEW.tenant_id AND id=NEW."
    "run_id\n  AND project_id=NEW.project_id AND context_version='meeti"
    "ng-planning-request-v1';\n SELECT * INTO cp FROM cehub_ai.applicat"
    "ion_result_checkpoints WHERE tenant_id=NEW.tenant_id\n  AND run_id"
    "=NEW.run_id AND invocation_id=NEW.model_invocation_id;\n IF r.id I"
    "S NULL OR NEW.agent_key<>'knowledge_lite' OR NEW.status<>'pending"
    "_review'\n  OR NEW.origin_key IS DISTINCT FROM 'meeting-plan:'||(r"
    ".run_context->>'meeting_planning_root_brief_id')\n  OR NEW.propose"
    "d_payload->>'brief_id' IS DISTINCT FROM r.run_context->>'meeting_"
    "planning_brief_id'\n  OR cp.id IS NULL OR cp.body->'output' IS DIS"
    "TINCT FROM NEW.proposed_payload->'assessment'\n  OR NOT cehub_ai.a"
    "pplication_result_receipt_valid(cp.tenant_id,cp.run_id,cp.model_c"
    "all_id,\n    cp.observation_id,cp.manifest_id,cp.invocation_id,cp."
    "owner_lease_id) THEN\n  RAISE EXCEPTION 'Meeting planning Finding "
    "needs its actual successful model receipt'; END IF;\n RETURN NEW;\n"
    "END $$;\n"
)
OLD = (
    "CREATE OR REPLACE FUNCTION cehub_ai.guard_meeting_planning_findin"
    "g() RETURNS trigger LANGUAGE plpgsql AS $$\nDECLARE r cehub_ai.age"
    "nt_runs; cp cehub_ai.application_result_checkpoints;\nBEGIN\n IF TG"
    "_OP='UPDATE' AND OLD.finding_type='meeting_plan' THEN\n  IF NEW IS"
    " DISTINCT FROM OLD THEN\n   RAISE EXCEPTION 'Meeting planning revi"
    "ew and application are not yet enabled'; END IF;\n  RETURN NEW;\n E"
    "ND IF;\n IF NEW.finding_type<>'meeting_plan' THEN RETURN NEW; END "
    "IF;\n SELECT * INTO r FROM cehub_ai.agent_runs WHERE tenant_id=NEW"
    ".tenant_id AND id=NEW.run_id\n  AND project_id=NEW.project_id AND "
    "context_version='meeting-planning-request-v1';\n SELECT * INTO cp "
    "FROM cehub_ai.application_result_checkpoints WHERE tenant_id=NEW."
    "tenant_id\n  AND run_id=NEW.run_id AND invocation_id=NEW.model_inv"
    "ocation_id;\n IF r.id IS NULL OR NEW.agent_key<>'knowledge_lite' O"
    "R NEW.status<>'pending_review'\n  OR NEW.origin_key IS DISTINCT FR"
    "OM 'meeting-plan:'||(r.run_context->>'meeting_planning_root_brief"
    "_id')\n  OR NEW.proposed_payload->>'brief_id' IS DISTINCT FROM r.r"
    "un_context->>'meeting_planning_brief_id'\n  OR cp.id IS NULL OR cp"
    ".body->'output' IS DISTINCT FROM NEW.proposed_payload->'assessmen"
    "t'\n  OR NOT cehub_ai.application_result_receipt_valid(cp.tenant_i"
    "d,cp.run_id,cp.model_call_id,\n    cp.observation_id,cp.manifest_i"
    "d,cp.invocation_id,cp.owner_lease_id) THEN\n  RAISE EXCEPTION 'Mee"
    "ting planning Finding needs its actual successful model receipt';"
    " END IF;\n RETURN NEW;\nEND $$;\n"
)
CONSTRAINT = (
    "(status <> 'applied' AND applied_by_user_id IS NULL AND applied_a"
    "t IS NULL AND applied_entity_type IS NULL AND applied_entity_id I"
    "S NULL) OR (status = 'applied' AND applied_by_user_id IS NOT NULL"
    " AND applied_at IS NOT NULL AND applied_entity_type IN ('risk', '"
    "memory', 'issue', 'task', 'test_run', 'sample_build_configuration"
    "', 'knowledge_candidate', 'schedule_change_proposal', 'material_e"
    "xception', 'test_plan', 'meeting_minutes', 'decision', 'ecr', 'ch"
    "ange_impact_scope', 'quality_work_package', 'process_template_rev"
    "ision', 'project_intake_proposal', 'meeting') AND applied_entity_"
    "id IS NOT NULL AND reviewed_at < applied_at)"
)
OLD_CONSTRAINT = (
    "(status <> 'applied' AND applied_by_user_id IS NULL AND applied_a"
    "t IS NULL AND applied_entity_type IS NULL AND applied_entity_id I"
    "S NULL) OR (status = 'applied' AND applied_by_user_id IS NOT NULL"
    " AND applied_at IS NOT NULL AND applied_entity_type IN ('risk', '"
    "memory', 'issue', 'task', 'test_run', 'sample_build_configuration"
    "', 'knowledge_candidate', 'schedule_change_proposal', 'material_e"
    "xception', 'test_plan', 'meeting_minutes', 'decision', 'ecr', 'ch"
    "ange_impact_scope', 'quality_work_package', 'process_template_rev"
    "ision', 'project_intake_proposal') AND applied_entity_id IS NOT N"
    "ULL AND reviewed_at < applied_at)"
)


def upgrade() -> None:
    op.execute(
        "ALTER TABLE cehub_ai.findings DROP CONSTRAINT ck_findings_apply_lifecycle_consistent"
    )
    op.execute(
        "ALTER TABLE cehub_ai.findings ADD CONSTRAINT "
        "ck_findings_apply_lifecycle_consistent CHECK (" + CONSTRAINT + ")"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_meeting_plan_applied_origin "
        "ON cehub_ai.findings (tenant_id,project_id,origin_key) "
        "WHERE finding_type='meeting_plan' AND status='applied'"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_meeting_plan_applied_meeting "
        "ON cehub_ai.findings (tenant_id,applied_entity_id) "
        "WHERE finding_type='meeting_plan' AND status='applied'"
    )
    op.execute(REVIEW)


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
    IF EXISTS(SELECT 1 FROM cehub_ai.findings WHERE finding_type='meeting_plan'
      AND status<>'pending_review') THEN
      RAISE EXCEPTION 'Meeting review and creation history must be retained'; END IF;
    END $$;
    DROP INDEX cehub_ai.uq_meeting_plan_applied_meeting;
    DROP INDEX cehub_ai.uq_meeting_plan_applied_origin;
    ALTER TABLE cehub_ai.findings DROP CONSTRAINT ck_findings_apply_lifecycle_consistent;
    """)
    op.execute(
        "ALTER TABLE cehub_ai.findings ADD CONSTRAINT "
        "ck_findings_apply_lifecycle_consistent CHECK (" + OLD_CONSTRAINT + ")"
    )
    op.execute(OLD)
