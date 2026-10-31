"""Frozen private retrieval feedback extension for a real Change fixed version."""

ISSUE_HUMAN = ("tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid\n"
 ' AND owner_id=scope_requester() AND scope_actor()=scope_requester()\n'
 ' AND category_access(tenant_id,category_id)\n'
 ' AND EXISTS(SELECT 1 FROM public.principals p\n'
 '   WHERE p.tenant_id=similar_history_feedback.tenant_id\n'
 "   AND p.id=scope_actor() AND p.kind='human' AND p.active)\n"
 ' AND EXISTS(SELECT 1 FROM public.quality_issue_versions q\n'
 '   WHERE q.tenant_id=similar_history_feedback.tenant_id\n'
 '   AND q.category_id=similar_history_feedback.category_id\n'
 '   AND q.product_id=similar_history_feedback.product_id\n'
 '   AND q.project_id=similar_history_feedback.project_id\n'
 '   AND q.issue_id=similar_history_feedback.issue_id\n'
 '   AND q.id=similar_history_feedback.issue_version_id\n'
 '   AND q.revision=similar_history_feedback.issue_revision)')

CHANGE_HUMAN = ("tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid\n"
 ' AND owner_id=scope_requester() AND scope_actor()=scope_requester()\n'
 ' AND category_access(tenant_id,category_id)\n'
 ' AND EXISTS(SELECT 1 FROM public.principals p\n'
 '   WHERE p.tenant_id=similar_history_feedback.tenant_id\n'
 "   AND p.id=scope_actor() AND p.kind='human' AND p.active)\n"
 ' AND (EXISTS(SELECT 1 FROM public.quality_issue_versions q\n'
 '   WHERE q.tenant_id=similar_history_feedback.tenant_id\n'
 '   AND q.category_id=similar_history_feedback.category_id\n'
 '   AND q.product_id=similar_history_feedback.product_id\n'
 '   AND q.project_id=similar_history_feedback.project_id\n'
 '   AND q.issue_id=similar_history_feedback.issue_id\n'
 '   AND q.id=similar_history_feedback.issue_version_id\n'
 '   AND q.revision=similar_history_feedback.issue_revision)\n'
 ' OR EXISTS(SELECT 1 FROM public.change_request_versions c\n'
 '   WHERE c.tenant_id=similar_history_feedback.tenant_id\n'
 '   AND c.category_id=similar_history_feedback.category_id\n'
 '   AND c.product_id=similar_history_feedback.product_id\n'
 '   AND c.project_id=similar_history_feedback.project_id\n'
 '   AND c.change_id=similar_history_feedback.change_id\n'
 '   AND c.id=similar_history_feedback.change_version_id\n'
 '   AND c.revision=similar_history_feedback.change_revision))')

ORIGIN_CHECK = ('(\n'
 ' (issue_id IS NOT NULL AND issue_version_id IS NOT NULL\n'
 '  AND issue_revision IS NOT NULL AND issue_revision>0\n'
 '  AND change_id IS NULL AND change_version_id IS NULL AND change_revision IS NULL)\n'
 ' OR\n'
 ' (change_id IS NOT NULL AND change_version_id IS NOT NULL\n'
 '  AND change_revision IS NOT NULL AND change_revision>0\n'
 '  AND issue_id IS NULL AND issue_version_id IS NULL AND issue_revision IS NULL\n'
 "  AND action<>'merge_prepared')\n"
 ')')

SCHEMA_SQL = ['LOCK TABLE public.similar_history_feedback IN ACCESS EXCLUSIVE MODE',
 'ALTER TABLE public.similar_history_feedback ADD COLUMN change_id UUID, ADD COLUMN '
 'change_version_id UUID, ADD COLUMN change_revision INTEGER, ALTER COLUMN issue_id DROP NOT '
 'NULL, ALTER COLUMN issue_version_id DROP NOT NULL, ALTER COLUMN issue_revision DROP NOT NULL',
 'ALTER TABLE public.similar_history_feedback ADD CONSTRAINT '
 'similar_history_feedback_change_version_fk FOREIGN '
 'KEY(tenant_id,product_id,change_id,change_version_id,change_revision) REFERENCES '
 'public.change_request_versions(tenant_id,product_id,change_id,id,revision)',
 'ALTER TABLE public.similar_history_feedback ADD CONSTRAINT '
 'similar_history_feedback_origin_exact CHECK((\n'
 ' (issue_id IS NOT NULL AND issue_version_id IS NOT NULL\n'
 '  AND issue_revision IS NOT NULL AND issue_revision>0\n'
 '  AND change_id IS NULL AND change_version_id IS NULL AND change_revision IS NULL)\n'
 ' OR\n'
 ' (change_id IS NOT NULL AND change_version_id IS NOT NULL\n'
 '  AND change_revision IS NOT NULL AND change_revision>0\n'
 '  AND issue_id IS NULL AND issue_version_id IS NULL AND issue_revision IS NULL\n'
 "  AND action<>'merge_prepared')\n"
 '))',
 'ALTER POLICY similar_history_read ON public.similar_history_feedback '
 "USING(tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid\n"
 ' AND owner_id=scope_requester() AND scope_actor()=scope_requester()\n'
 ' AND category_access(tenant_id,category_id)\n'
 ' AND EXISTS(SELECT 1 FROM public.principals p\n'
 '   WHERE p.tenant_id=similar_history_feedback.tenant_id\n'
 "   AND p.id=scope_actor() AND p.kind='human' AND p.active)\n"
 ' AND (EXISTS(SELECT 1 FROM public.quality_issue_versions q\n'
 '   WHERE q.tenant_id=similar_history_feedback.tenant_id\n'
 '   AND q.category_id=similar_history_feedback.category_id\n'
 '   AND q.product_id=similar_history_feedback.product_id\n'
 '   AND q.project_id=similar_history_feedback.project_id\n'
 '   AND q.issue_id=similar_history_feedback.issue_id\n'
 '   AND q.id=similar_history_feedback.issue_version_id\n'
 '   AND q.revision=similar_history_feedback.issue_revision)\n'
 ' OR EXISTS(SELECT 1 FROM public.change_request_versions c\n'
 '   WHERE c.tenant_id=similar_history_feedback.tenant_id\n'
 '   AND c.category_id=similar_history_feedback.category_id\n'
 '   AND c.product_id=similar_history_feedback.product_id\n'
 '   AND c.project_id=similar_history_feedback.project_id\n'
 '   AND c.change_id=similar_history_feedback.change_id\n'
 '   AND c.id=similar_history_feedback.change_version_id\n'
 '   AND c.revision=similar_history_feedback.change_revision)))',
 'ALTER POLICY similar_history_append ON public.similar_history_feedback WITH '
 "CHECK(tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid\n"
 ' AND owner_id=scope_requester() AND scope_actor()=scope_requester()\n'
 ' AND category_access(tenant_id,category_id)\n'
 ' AND EXISTS(SELECT 1 FROM public.principals p\n'
 '   WHERE p.tenant_id=similar_history_feedback.tenant_id\n'
 "   AND p.id=scope_actor() AND p.kind='human' AND p.active)\n"
 ' AND (EXISTS(SELECT 1 FROM public.quality_issue_versions q\n'
 '   WHERE q.tenant_id=similar_history_feedback.tenant_id\n'
 '   AND q.category_id=similar_history_feedback.category_id\n'
 '   AND q.product_id=similar_history_feedback.product_id\n'
 '   AND q.project_id=similar_history_feedback.project_id\n'
 '   AND q.issue_id=similar_history_feedback.issue_id\n'
 '   AND q.id=similar_history_feedback.issue_version_id\n'
 '   AND q.revision=similar_history_feedback.issue_revision)\n'
 ' OR EXISTS(SELECT 1 FROM public.change_request_versions c\n'
 '   WHERE c.tenant_id=similar_history_feedback.tenant_id\n'
 '   AND c.category_id=similar_history_feedback.category_id\n'
 '   AND c.product_id=similar_history_feedback.product_id\n'
 '   AND c.project_id=similar_history_feedback.project_id\n'
 '   AND c.change_id=similar_history_feedback.change_id\n'
 '   AND c.id=similar_history_feedback.change_version_id\n'
 '   AND c.revision=similar_history_feedback.change_revision)))']

EMPTY_HISTORY_SQL = ['LOCK TABLE public.similar_history_feedback IN ACCESS EXCLUSIVE MODE',
 'ALTER TABLE public.similar_history_feedback NO FORCE ROW LEVEL SECURITY',
 'DO $$ BEGIN\n'
 ' IF EXISTS(SELECT 1 FROM public.similar_history_feedback WHERE change_id IS NOT NULL) THEN\n'
 "  RAISE EXCEPTION 'Change-origin similar history feedback requires s0_0851';\n"
 ' END IF;\n'
 'END $$',
 'ALTER TABLE public.similar_history_feedback FORCE ROW LEVEL SECURITY']

DOWNGRADE_SQL = ['LOCK TABLE public.similar_history_feedback IN ACCESS EXCLUSIVE MODE',
 'ALTER TABLE public.similar_history_feedback NO FORCE ROW LEVEL SECURITY',
 'DO $$ BEGIN\n'
 ' IF EXISTS(SELECT 1 FROM public.similar_history_feedback WHERE change_id IS NOT NULL) THEN\n'
 "  RAISE EXCEPTION 'Change-origin similar history feedback requires s0_0851';\n"
 ' END IF;\n'
 'END $$',
 'ALTER TABLE public.similar_history_feedback FORCE ROW LEVEL SECURITY',
 'ALTER POLICY similar_history_read ON public.similar_history_feedback '
 "USING(tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid\n"
 ' AND owner_id=scope_requester() AND scope_actor()=scope_requester()\n'
 ' AND category_access(tenant_id,category_id)\n'
 ' AND EXISTS(SELECT 1 FROM public.principals p\n'
 '   WHERE p.tenant_id=similar_history_feedback.tenant_id\n'
 "   AND p.id=scope_actor() AND p.kind='human' AND p.active)\n"
 ' AND EXISTS(SELECT 1 FROM public.quality_issue_versions q\n'
 '   WHERE q.tenant_id=similar_history_feedback.tenant_id\n'
 '   AND q.category_id=similar_history_feedback.category_id\n'
 '   AND q.product_id=similar_history_feedback.product_id\n'
 '   AND q.project_id=similar_history_feedback.project_id\n'
 '   AND q.issue_id=similar_history_feedback.issue_id\n'
 '   AND q.id=similar_history_feedback.issue_version_id\n'
 '   AND q.revision=similar_history_feedback.issue_revision))',
 'ALTER POLICY similar_history_append ON public.similar_history_feedback WITH '
 "CHECK(tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid\n"
 ' AND owner_id=scope_requester() AND scope_actor()=scope_requester()\n'
 ' AND category_access(tenant_id,category_id)\n'
 ' AND EXISTS(SELECT 1 FROM public.principals p\n'
 '   WHERE p.tenant_id=similar_history_feedback.tenant_id\n'
 "   AND p.id=scope_actor() AND p.kind='human' AND p.active)\n"
 ' AND EXISTS(SELECT 1 FROM public.quality_issue_versions q\n'
 '   WHERE q.tenant_id=similar_history_feedback.tenant_id\n'
 '   AND q.category_id=similar_history_feedback.category_id\n'
 '   AND q.product_id=similar_history_feedback.product_id\n'
 '   AND q.project_id=similar_history_feedback.project_id\n'
 '   AND q.issue_id=similar_history_feedback.issue_id\n'
 '   AND q.id=similar_history_feedback.issue_version_id\n'
 '   AND q.revision=similar_history_feedback.issue_revision))',
 'ALTER TABLE public.similar_history_feedback DROP CONSTRAINT '
 'similar_history_feedback_origin_exact, DROP CONSTRAINT '
 'similar_history_feedback_change_version_fk, DROP COLUMN change_revision, DROP COLUMN '
 'change_version_id, DROP COLUMN change_id, ALTER COLUMN issue_id SET NOT NULL, ALTER COLUMN '
 'issue_version_id SET NOT NULL, ALTER COLUMN issue_revision SET NOT NULL']
