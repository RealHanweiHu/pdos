"""Existing private feedback table gains one exact native Change origin, no new audience."""

from migrations.schema_s0_0833 import HUMAN as ISSUE_HUMAN

CHANGE_HUMAN = """tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid
 AND owner_id=scope_requester() AND scope_actor()=scope_requester()
 AND category_access(tenant_id,category_id)
 AND EXISTS(SELECT 1 FROM public.principals p
   WHERE p.tenant_id=similar_history_feedback.tenant_id
   AND p.id=scope_actor() AND p.kind='human' AND p.active)
 AND (EXISTS(SELECT 1 FROM public.quality_issue_versions q
   WHERE q.tenant_id=similar_history_feedback.tenant_id
   AND q.category_id=similar_history_feedback.category_id
   AND q.product_id=similar_history_feedback.product_id
   AND q.project_id=similar_history_feedback.project_id
   AND q.issue_id=similar_history_feedback.issue_id
   AND q.id=similar_history_feedback.issue_version_id
   AND q.revision=similar_history_feedback.issue_revision)
 OR EXISTS(SELECT 1 FROM public.change_request_versions c
   WHERE c.tenant_id=similar_history_feedback.tenant_id
   AND c.category_id=similar_history_feedback.category_id
   AND c.product_id=similar_history_feedback.product_id
   AND c.project_id=similar_history_feedback.project_id
   AND c.change_id=similar_history_feedback.change_id
   AND c.id=similar_history_feedback.change_version_id
   AND c.revision=similar_history_feedback.change_revision))"""

ORIGIN_CHECK = """(
 (issue_id IS NOT NULL AND issue_version_id IS NOT NULL
  AND issue_revision IS NOT NULL AND issue_revision>0
  AND change_id IS NULL AND change_version_id IS NULL AND change_revision IS NULL)
 OR
 (change_id IS NOT NULL AND change_version_id IS NOT NULL
  AND change_revision IS NOT NULL AND change_revision>0
  AND issue_id IS NULL AND issue_version_id IS NULL AND issue_revision IS NULL
  AND action<>'merge_prepared')
)"""

SCHEMA_SQL = [
    "LOCK TABLE public.similar_history_feedback IN ACCESS EXCLUSIVE MODE",
    "ALTER TABLE public.similar_history_feedback "
    "ADD COLUMN change_id UUID, ADD COLUMN change_version_id UUID, "
    "ADD COLUMN change_revision INTEGER, "
    "ALTER COLUMN issue_id DROP NOT NULL, ALTER COLUMN issue_version_id DROP NOT NULL, "
    "ALTER COLUMN issue_revision DROP NOT NULL",
    "ALTER TABLE public.similar_history_feedback "
    "ADD CONSTRAINT similar_history_feedback_change_version_fk "
    "FOREIGN KEY(tenant_id,product_id,change_id,change_version_id,change_revision) "
    "REFERENCES public.change_request_versions(tenant_id,product_id,change_id,id,revision)",
    "ALTER TABLE public.similar_history_feedback "
    f"ADD CONSTRAINT similar_history_feedback_origin_exact CHECK({ORIGIN_CHECK})",
    "ALTER POLICY similar_history_read ON public.similar_history_feedback "
    f"USING({CHANGE_HUMAN})",
    "ALTER POLICY similar_history_append ON public.similar_history_feedback "
    f"WITH CHECK({CHANGE_HUMAN})",
]

# The table owner must see all private rows for a loss-prevention check. Restore
# FORCE before ordinary policy/column DDL; any refusal rolls this whole UOW back.
EMPTY_HISTORY_SQL = [
    "LOCK TABLE public.similar_history_feedback IN ACCESS EXCLUSIVE MODE",
    "ALTER TABLE public.similar_history_feedback NO FORCE ROW LEVEL SECURITY",
    """DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM public.similar_history_feedback WHERE change_id IS NOT NULL) THEN
  RAISE EXCEPTION 'Change-origin similar history feedback requires s0_0851';
 END IF;
END $$""",
    "ALTER TABLE public.similar_history_feedback FORCE ROW LEVEL SECURITY",
]

DOWNGRADE_SQL = [
    *EMPTY_HISTORY_SQL,
    "ALTER POLICY similar_history_read ON public.similar_history_feedback "
    f"USING({ISSUE_HUMAN})",
    "ALTER POLICY similar_history_append ON public.similar_history_feedback "
    f"WITH CHECK({ISSUE_HUMAN})",
    "ALTER TABLE public.similar_history_feedback "
    "DROP CONSTRAINT similar_history_feedback_origin_exact, "
    "DROP CONSTRAINT similar_history_feedback_change_version_fk, "
    "DROP COLUMN change_revision, DROP COLUMN change_version_id, DROP COLUMN change_id, "
    "ALTER COLUMN issue_id SET NOT NULL, ALTER COLUMN issue_version_id SET NOT NULL, "
    "ALTER COLUMN issue_revision SET NOT NULL",
]
