"""Private explicit object-page search feedback, never business facts."""

TABLE_SQL = """CREATE TABLE public.similar_history_feedback (
 category_id UUID NOT NULL, product_id UUID NOT NULL, project_id UUID NOT NULL,
 owner_id UUID NOT NULL, issue_id UUID NOT NULL, issue_version_id UUID NOT NULL,
 issue_revision INTEGER NOT NULL, candidate_kind VARCHAR(16) NOT NULL,
 candidate_source_id UUID NOT NULL, candidate_revision INTEGER NOT NULL,
 ranking_version VARCHAR(160) NOT NULL, action VARCHAR(24) NOT NULL,
 request_key UUID NOT NULL, request_sha256 VARCHAR(64) NOT NULL,
 id UUID NOT NULL, tenant_id UUID NOT NULL, created_at TIMESTAMP WITH TIME ZONE NOT NULL,
 PRIMARY KEY(id), UNIQUE(tenant_id,owner_id,request_key),
 FOREIGN KEY(tenant_id,owner_id) REFERENCES public.principals(tenant_id,id),
 FOREIGN KEY(tenant_id,product_id,issue_version_id)
 REFERENCES public.quality_issue_versions(tenant_id,product_id,id),
 CHECK(issue_revision>0 AND candidate_revision>0),
 CHECK(candidate_kind IN ('issue','capa','change')),
 CHECK(action IN ('opened','not_relevant','merge_prepared')),
 CHECK(request_sha256 ~ '^[0-9a-f]{64}$')
)"""

HUMAN = """tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid
 AND owner_id=scope_requester() AND scope_actor()=scope_requester()
 AND category_access(tenant_id,category_id)
 AND EXISTS(SELECT 1 FROM public.principals p
   WHERE p.tenant_id=similar_history_feedback.tenant_id
   AND p.id=scope_actor() AND p.kind='human' AND p.active)
 AND EXISTS(SELECT 1 FROM public.quality_issue_versions q
   WHERE q.tenant_id=similar_history_feedback.tenant_id
   AND q.category_id=similar_history_feedback.category_id
   AND q.product_id=similar_history_feedback.product_id
   AND q.project_id=similar_history_feedback.project_id
   AND q.issue_id=similar_history_feedback.issue_id
   AND q.id=similar_history_feedback.issue_version_id
   AND q.revision=similar_history_feedback.issue_revision)"""

SCHEMA_SQL = [
    TABLE_SQL,
    "CREATE INDEX ix_similar_history_feedback_category_id "
    "ON public.similar_history_feedback(category_id)",
    "CREATE INDEX ix_similar_history_feedback_tenant_id "
    "ON public.similar_history_feedback(tenant_id)",
    "ALTER TABLE public.similar_history_feedback ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE public.similar_history_feedback FORCE ROW LEVEL SECURITY",
    "CREATE POLICY similar_history_read ON public.similar_history_feedback "
    f"FOR SELECT TO pdos_next_app USING({HUMAN})",
    "CREATE POLICY similar_history_append ON public.similar_history_feedback "
    f"FOR INSERT TO pdos_next_app WITH CHECK({HUMAN})",
    "REVOKE ALL ON public.similar_history_feedback "
    "FROM PUBLIC,pdos_agent,pdos_next_app,pdos_next_auth,pdos_next_dispatch",
    "GRANT SELECT,INSERT ON public.similar_history_feedback TO pdos_next_app",
    "CREATE TRIGGER similar_history_append_only BEFORE UPDATE OR DELETE "
    "ON public.similar_history_feedback FOR EACH ROW EXECUTE FUNCTION kernel_append_only()",
]
DOWNGRADE_SQL = [
    "ALTER TABLE public.similar_history_feedback NO FORCE ROW LEVEL SECURITY",
    """DO $$ BEGIN IF EXISTS(SELECT 1 FROM public.similar_history_feedback) THEN
     RAISE EXCEPTION 'Similar history feedback requires s0_0833'; END IF; END $$""",
    "DROP TABLE public.similar_history_feedback",
]
