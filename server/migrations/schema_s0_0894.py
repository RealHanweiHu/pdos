"""Assigned s0_0894 on s0_0893 at the 11-16 memory integration (placeholder s0_0910).

占位号 s0_0910，集成时按真实 head 重排（写成时接 s0_0892；revision、down_revision、
本快照文件名和降级守卫文字一起改，不可协商项 3）。

D504 (P87 第 4 项): the scope-note review period is a tenant setting, 90 days by
default. It is one more column on the existing append-only tenant memory policy
versions, changed by a current human administrator exactly like the other
switches. A new or revised scope-note version takes the period in force when it
is written; versions already written keep the review date they were given.
"""

SCHEMA_SQL = (
    "ALTER TABLE public.memory_tenant_policies "
    "ADD COLUMN scope_note_review_days INTEGER DEFAULT 90 NOT NULL",
    "ALTER TABLE public.memory_tenant_policies ADD CONSTRAINT memory_policy_review_days "
    "CHECK (scope_note_review_days BETWEEN 1 AND 365)",
)

DOWNGRADE_SQL = (
    "ALTER TABLE public.memory_tenant_policies NO FORCE ROW LEVEL SECURITY",
    """DO $$ BEGIN IF EXISTS(SELECT 1 FROM public.memory_tenant_policies
       WHERE scope_note_review_days<>90) THEN
     RAISE EXCEPTION 'A tenant scope-note review period requires s0_0894'; END IF; END $$""",
    "ALTER TABLE public.memory_tenant_policies FORCE ROW LEVEL SECURITY",
    "ALTER TABLE public.memory_tenant_policies DROP CONSTRAINT memory_policy_review_days",
    "ALTER TABLE public.memory_tenant_policies DROP COLUMN scope_note_review_days",
)
