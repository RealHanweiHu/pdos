"""Meeting Issue/Risk/ECR findings and source-linked business applications.

Revision ID: 0175_meeting_business_findings
Revises: 0174_meeting_decision_findings
"""

import sqlalchemy as sa
from alembic import op

revision = "0175_meeting_business_findings"
down_revision = "0174_meeting_decision_findings"
branch_labels = None
depends_on = None
TARGETS = (
    ("issues", "cehub_project"),
    ("risks", "cehub_project"),
    ("engineering_change_requests", "cehub_product"),
)
CHANGES = [
    (
        "agent_runs",
        "ck_agent_runs_event_bounds_consistent",
        """
(((agent_key = 'ai_chat' OR (agent_key = 'quality_intelligence' AND context_version =
'report-mapping-request-v1') OR (agent_key='knowledge_lite' AND context_version IN
('meeting-reading-request-v1','meeting-minutes-request-v1','meeting-actions-request-v1','meeting-decisions-request-v1')))
AND subscription_id IS NULL AND first_event_row_id IS NULL AND last_event_row_id IS NULL
AND event_count = 0 AND event_row_ids = '[]'::jsonb AND request_id IS NOT NULL AND
btrim(request_id) <> '' AND requested_by_user_id IS NOT NULL AND (status IN ('running',
'succeeded', 'degraded', 'failed') OR (agent_key IN ('ai_chat','quality_intelligence') AND
status = 'queued'))) OR (agent_key <> 'ai_chat' AND subscription_id IS NOT NULL AND
((request_id IS NULL AND requested_by_user_id IS NULL) OR
((agent_key='project_intelligence' AND context_version='risk-suggestion-request-v1' OR
agent_key='quality_intelligence' AND context_version='test-plan-request-v1') AND
request_id IS NOT NULL AND btrim(request_id)<>'' AND requested_by_user_id IS NOT NULL))
AND first_event_row_id IS NOT NULL AND last_event_row_id IS NOT NULL AND CASE WHEN
jsonb_typeof(event_row_ids) = 'array' THEN event_count > 0 AND first_event_row_id > 0 AND
last_event_row_id >= first_event_row_id AND jsonb_array_length(event_row_ids) =
event_count AND (event_row_ids->>0)::bigint = first_event_row_id AND
(event_row_ids->>(event_count - 1))::bigint = last_event_row_id ELSE false END)) IS TRUE
""",
        """
(((agent_key = 'ai_chat' OR (agent_key = 'quality_intelligence' AND context_version =
'report-mapping-request-v1') OR (agent_key='knowledge_lite' AND context_version IN
('meeting-reading-request-v1','meeting-minutes-request-v1','meeting-actions-request-v1','meeting-decisions-request-v1','meeting-business-request-v1')))
AND subscription_id IS NULL AND first_event_row_id IS NULL AND last_event_row_id IS NULL
AND event_count = 0 AND event_row_ids = '[]'::jsonb AND request_id IS NOT NULL AND
btrim(request_id) <> '' AND requested_by_user_id IS NOT NULL AND (status IN ('running',
'succeeded', 'degraded', 'failed') OR (agent_key IN ('ai_chat','quality_intelligence') AND
status = 'queued'))) OR (agent_key <> 'ai_chat' AND subscription_id IS NOT NULL AND
((request_id IS NULL AND requested_by_user_id IS NULL) OR
((agent_key='project_intelligence' AND context_version='risk-suggestion-request-v1' OR
agent_key='quality_intelligence' AND context_version='test-plan-request-v1') AND
request_id IS NOT NULL AND btrim(request_id)<>'' AND requested_by_user_id IS NOT NULL))
AND first_event_row_id IS NOT NULL AND last_event_row_id IS NOT NULL AND CASE WHEN
jsonb_typeof(event_row_ids) = 'array' THEN event_count > 0 AND first_event_row_id > 0 AND
last_event_row_id >= first_event_row_id AND jsonb_array_length(event_row_ids) =
event_count AND (event_row_ids->>0)::bigint = first_event_row_id AND
(event_row_ids->>(event_count - 1))::bigint = last_event_row_id ELSE false END)) IS TRUE
""",
    ),
    (
        "findings",
        "ck_findings_type_allowed",
        """
(agent_key = 'project_intelligence' AND finding_type IN ('risk_suggestion',
'blocker_alert', 'gate_readiness_anomaly')) OR (agent_key = 'knowledge_lite' AND
finding_type IN ('knowledge_draft', 'meeting_minutes', 'meeting_action',
'meeting_decision')) OR (agent_key = 'engineering_intelligence' AND finding_type IN
('bom_impact_suggestion', 'change_impact_suggestion')) OR (agent_key =
'quality_intelligence' AND finding_type IN ('quality_cluster_alert', 'capa_suggestion',
'test_plan_change')) OR (agent_key = 'supplier_intelligence' AND finding_type =
'supplier_delay_risk') OR (agent_key = 'executive_intelligence' AND finding_type =
'executive_portfolio_brief')
""",
        """
(agent_key = 'project_intelligence' AND finding_type IN ('risk_suggestion',
'blocker_alert', 'gate_readiness_anomaly')) OR (agent_key = 'knowledge_lite' AND
finding_type IN ('knowledge_draft', 'meeting_minutes', 'meeting_action',
'meeting_decision', 'meeting_issue', 'meeting_risk', 'meeting_change')) OR (agent_key =
'engineering_intelligence' AND finding_type IN ('bom_impact_suggestion',
'change_impact_suggestion')) OR (agent_key = 'quality_intelligence' AND finding_type IN
('quality_cluster_alert', 'capa_suggestion', 'test_plan_change')) OR (agent_key =
'supplier_intelligence' AND finding_type = 'supplier_delay_risk') OR (agent_key =
'executive_intelligence' AND finding_type = 'executive_portfolio_brief')
""",
    ),
    (
        "findings",
        "ck_findings_evidence_event_ids_array",
        """
jsonb_typeof(evidence_event_ids) = 'array' AND (jsonb_array_length(evidence_event_ids) > 0
OR (finding_type IN ('meeting_minutes','meeting_action','meeting_decision') AND
evidence_event_ids='[]'::jsonb))
""",
        """
jsonb_typeof(evidence_event_ids) = 'array' AND (jsonb_array_length(evidence_event_ids) > 0
OR (finding_type IN
('meeting_minutes','meeting_action','meeting_decision','meeting_issue','meeting_risk','meeting_change')
AND evidence_event_ids='[]'::jsonb))
""",
    ),
    (
        "findings",
        "ck_findings_apply_lifecycle_consistent",
        """
(status <> 'applied' AND applied_by_user_id IS NULL AND applied_at IS NULL AND
applied_entity_type IS NULL AND applied_entity_id IS NULL) OR (status = 'applied' AND
applied_by_user_id IS NOT NULL AND applied_at IS NOT NULL AND applied_entity_type IN
('risk', 'memory', 'issue', 'task', 'test_run', 'sample_build_configuration',
'knowledge_candidate', 'schedule_change_proposal', 'material_exception', 'test_plan',
'meeting_minutes', 'decision') AND applied_entity_id IS NOT NULL AND reviewed_at <
applied_at)
""",
        """
(status <> 'applied' AND applied_by_user_id IS NULL AND applied_at IS NULL AND
applied_entity_type IS NULL AND applied_entity_id IS NULL) OR (status = 'applied' AND
applied_by_user_id IS NOT NULL AND applied_at IS NOT NULL AND applied_entity_type IN
('risk', 'memory', 'issue', 'task', 'test_run', 'sample_build_configuration',
'knowledge_candidate', 'schedule_change_proposal', 'material_exception', 'test_plan',
'meeting_minutes', 'decision', 'ecr') AND applied_entity_id IS NOT NULL AND reviewed_at <
applied_at)
""",
    ),
    (
        "finding_quality_controls",
        "ck_finding_quality_controls_type_allowed",
        """
(agent_key = 'project_intelligence' AND finding_type IN ('risk_suggestion',
'blocker_alert', 'gate_readiness_anomaly')) OR (agent_key = 'knowledge_lite' AND
finding_type IN ('knowledge_draft', 'meeting_minutes', 'meeting_action',
'meeting_decision')) OR (agent_key = 'engineering_intelligence' AND finding_type IN
('bom_impact_suggestion', 'change_impact_suggestion')) OR (agent_key =
'quality_intelligence' AND finding_type IN ('quality_cluster_alert', 'capa_suggestion',
'test_plan_change')) OR (agent_key = 'supplier_intelligence' AND finding_type =
'supplier_delay_risk') OR (agent_key = 'executive_intelligence' AND finding_type =
'executive_portfolio_brief')
""",
        """
(agent_key = 'project_intelligence' AND finding_type IN ('risk_suggestion',
'blocker_alert', 'gate_readiness_anomaly')) OR (agent_key = 'knowledge_lite' AND
finding_type IN ('knowledge_draft', 'meeting_minutes', 'meeting_action',
'meeting_decision', 'meeting_issue', 'meeting_risk', 'meeting_change')) OR (agent_key =
'engineering_intelligence' AND finding_type IN ('bom_impact_suggestion',
'change_impact_suggestion')) OR (agent_key = 'quality_intelligence' AND finding_type IN
('quality_cluster_alert', 'capa_suggestion', 'test_plan_change')) OR (agent_key =
'supplier_intelligence' AND finding_type = 'supplier_delay_risk') OR (agent_key =
'executive_intelligence' AND finding_type = 'executive_portfolio_brief')
""",
    ),
]


def constraints(up: bool) -> None:
    for table, name, old, new in CHANGES:
        op.drop_constraint(op.f(name), table, schema="cehub_ai", type_="check")
        op.create_check_constraint(op.f(name), table, new if up else old, schema="cehub_ai")


def upgrade() -> None:
    constraints(True)
    for table, schema in TARGETS:
        op.add_column(table, sa.Column("source_finding_id", sa.Uuid()), schema=schema)
        op.create_foreign_key(
            f"fk_{table}_finding",
            table,
            "findings",
            ["tenant_id", "project_id", "source_finding_id"],
            ["tenant_id", "project_id", "id"],
            source_schema=schema,
            referent_schema="cehub_ai",
            ondelete="RESTRICT",
        )
        op.create_unique_constraint(
            f"uq_{table}_finding", table, ["tenant_id", "source_finding_id"], schema=schema
        )
    op.create_index(
        "uq_applied_meeting_business_origin",
        "findings",
        ["tenant_id", "project_id", "origin_key"],
        unique=True,
        schema="cehub_ai",
        postgresql_where=sa.text(
            "finding_type IN ('meeting_issue','meeting_risk','meeting_change') AND status='applied'"
        ),
    )
    op.execute(GUARDS)
    for table, schema in TARGETS:
        op.execute(
            f"CREATE TRIGGER guard_meeting_business_origin BEFORE INSERT OR UPDATE "
            f"ON {schema}.{table} FOR EACH ROW "
            "EXECUTE FUNCTION cehub_project.guard_meeting_business_origin()"
        )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text("""
        SELECT EXISTS(SELECT 1 FROM cehub_ai.findings
            WHERE finding_type IN ('meeting_issue','meeting_risk','meeting_change'))
        OR EXISTS(SELECT 1 FROM cehub_ai.agent_runs
            WHERE context_version='meeting-business-request-v1')
        OR EXISTS(SELECT 1 FROM cehub_ai.finding_quality_controls
            WHERE finding_type IN ('meeting_issue','meeting_risk','meeting_change'))
    """)
        )
        .scalar_one()
    ):
        raise RuntimeError("Refusing to remove meeting business candidate history")
    for table, schema in TARGETS:
        op.execute(f"DROP TRIGGER guard_meeting_business_origin ON {schema}.{table}")
        op.drop_constraint(f"uq_{table}_finding", table, schema=schema, type_="unique")
        op.drop_constraint(f"fk_{table}_finding", table, schema=schema, type_="foreignkey")
        op.drop_column(table, "source_finding_id", schema=schema)
    op.execute("""
        DROP TRIGGER guard_business_finding_source ON cehub_ai.findings;
        DROP FUNCTION cehub_ai.guard_business_finding_source();
        DROP FUNCTION cehub_project.guard_meeting_business_origin();
    """)
    op.drop_index("uq_applied_meeting_business_origin", table_name="findings", schema="cehub_ai")
    constraints(False)


GUARDS = r"""
CREATE FUNCTION cehub_ai.guard_business_finding_source() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_OP='UPDATE' AND OLD.finding_type IN ('meeting_issue','meeting_risk','meeting_change') AND
  (NEW.finding_type<>OLD.finding_type OR NEW.origin_key<>OLD.origin_key
   OR NEW.proposed_payload IS DISTINCT FROM OLD.proposed_payload
   OR NEW.run_id<>OLD.run_id OR NEW.model_invocation_id<>OLD.model_invocation_id) THEN
  RAISE EXCEPTION 'Meeting proposal origin is immutable' USING ERRCODE='23514';
 END IF;
 IF NEW.finding_type NOT IN ('meeting_issue','meeting_risk','meeting_change') THEN
  RETURN NEW;
 END IF;
 IF NEW.evidence_event_ids<>'[]'::jsonb OR NOT EXISTS(
  SELECT 1 FROM cehub_ai.agent_runs r JOIN cehub_ai.model_invocations i
   ON i.tenant_id=r.tenant_id AND i.project_id=r.project_id AND i.run_id=r.id
  WHERE r.tenant_id=NEW.tenant_id AND r.project_id=NEW.project_id AND r.id=NEW.run_id
   AND r.agent_key='knowledge_lite' AND r.context_version='meeting-business-request-v1'
   AND r.run_context->>'reading_propose_business'='true'
   AND i.id=NEW.model_invocation_id AND i.agent_key=r.agent_key AND i.status='succeeded'
   AND NEW.finding_type='meeting_' || (NEW.proposed_payload->>'kind')
   AND NEW.proposed_payload->>'meeting_id'=r.run_context->'reading_source'->>'meeting_id'
   AND NEW.proposed_payload->>'transcript_id'=r.run_context->'reading_source'->>'transcript_id'
   AND NEW.proposed_payload->>'source_digest'=r.run_context->'reading_source'->>'transcript_digest'
   AND NEW.proposed_payload->'member_options'=r.run_context->'reading_source'->'business_options'
 ) THEN
  RAISE EXCEPTION 'Business proposal must bind its actual model run and source'
   USING ERRCODE='23514';
 END IF;
 IF NEW.accepted_payload IS NOT NULL AND (
  NEW.accepted_payload->>'details_confirmed' IS DISTINCT FROM 'true'
  OR EXISTS(SELECT 1 FROM
   unnest(ARRAY['kind','meeting_id','transcript_id','source_digest','member_options','citations',
                'suggested_response']) k
   WHERE NEW.accepted_payload->k IS DISTINCT FROM NEW.proposed_payload->k)) THEN
  RAISE EXCEPTION 'Business review must retain the original evidence' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION cehub_ai.guard_business_finding_source() FROM PUBLIC;
CREATE TRIGGER guard_business_finding_source BEFORE INSERT OR UPDATE ON cehub_ai.findings
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.guard_business_finding_source();

CREATE FUNCTION cehub_project.guard_meeting_business_origin() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE f cehub_ai.findings%ROWTYPE; n jsonb; p jsonb; kind text; k text;
BEGIN
 IF TG_OP='UPDATE' THEN
  IF NEW.source_finding_id IS DISTINCT FROM OLD.source_finding_id THEN
   RAISE EXCEPTION 'Business source cannot be replaced' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
 END IF;
 IF NEW.source_finding_id IS NULL THEN RETURN NEW; END IF;
 kind := CASE TG_TABLE_NAME WHEN 'issues' THEN 'issue' WHEN 'risks' THEN 'risk'
         WHEN 'engineering_change_requests' THEN 'change' END;
 SELECT * INTO f FROM cehub_ai.findings
 WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.source_finding_id;
 IF NOT FOUND OR f.finding_type IS DISTINCT FROM 'meeting_' || kind OR f.status<>'accepted' THEN
  RAISE EXCEPTION 'Business write requires its independently accepted proposal'
   USING ERRCODE='23514';
 END IF;
 n:=to_jsonb(NEW); p:=f.accepted_payload;
 IF n->>'title' IS DISTINCT FROM p->>'title'
  OR n->>'status' IS DISTINCT FROM (CASE WHEN kind='change' THEN 'request' ELSE 'open' END)
  OR (kind='change' AND (n->>'reason' IS DISTINCT FROM p->>'description'
                        OR n->>'code' IS DISTINCT FROM p->>'code'))
  OR (kind<>'change' AND (n->>'description' IS DISTINCT FROM p->>'description'
      OR n->>'owner_user_id' IS DISTINCT FROM p->>'owner_id'
      OR n->>'target_date' IS DISTINCT FROM p->>'target_date')) THEN
  RAISE EXCEPTION 'Initial business content must match the accepted proposal' USING ERRCODE='23514';
 END IF;
 IF kind='issue' THEN
  FOREACH k IN ARRAY ARRAY['issue_type','severity','closure_criteria'] LOOP
   IF n->k IS DISTINCT FROM p->k THEN
    RAISE EXCEPTION 'Issue details differ from accepted proposal' USING ERRCODE='23514';
   END IF;
  END LOOP;
  IF n->>'verifier_user_id' IS DISTINCT FROM p->>'verifier_id'
   OR n->>'root_cause' IS NOT NULL OR n->>'resolution' IS NOT NULL THEN
   RAISE EXCEPTION 'Issue verification or analysis is not an approved completion'
    USING ERRCODE='23514';
  END IF;
 ELSIF kind='risk' THEN
  FOREACH k IN ARRAY ARRAY['likelihood','impact','mitigation_plan','contingency_plan'] LOOP
   IF n->k IS DISTINCT FROM p->k THEN
    RAISE EXCEPTION 'Risk details differ from accepted proposal' USING ERRCODE='23514';
   END IF;
  END LOOP;
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION cehub_project.guard_meeting_business_origin() FROM PUBLIC;
"""
