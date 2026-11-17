"""占位号 s0_0920（接真实 head s0_0892），集成时按真实 head 重排：revision、down_revision、
本快照文件名与降级守卫文字 'Memory M3 requires s0_0920' 一起改（不可协商项 3）。

记忆 M3 沉淀与改进 (memory design §6.4, §7.5, §14.6–§14.9; P88; target architecture §6.9).

Six append-only tables (pdos_next.agent.memory.m3_models) and the deterministic
system-rule functions that write the only rows no person writes:

* ``memory_review_items``: a person writes a correction route only for
  themself (actor = requester = a human), from a correction mark they own on
  an episode of the same Run. 待复核 flags after an object revision and review
  hand-overs after an author left are inserted only by
  ``memory_flag_object_update`` (from a verified outbox event) and
  ``memory_flag_departed_authors``. Nothing an AI identity does satisfies the
  insert policy. Readers: the assignee and the person who raised it.
* ``memory_review_decisions``: the assignee, for themself, once per item.
* ``skill_revision_candidates``: only ``memory_summarize_procedural`` (counts
  over the last 30 days, threshold, sample Runs; no text). Read by tenant
  administrators only.
* ``skill_revision_decisions``: a tenant administrator, named. A decision row
  can never say it activated anything.
* ``memory_system_rule_settings``: a tenant administrator stopping or
  restarting a preset rule. Read through ``memory_system_rule_enabled``.
* ``memory_maintenance_ledger``: through ``memory_ledger_record`` only, for a
  closed list of tasks; read by administrators.

No function here calls a model or reads text it would copy: items carry
references, versions and the person's own words only.
"""

# ruff: noqa: E501 -- Reviewed applied SQL literals remain byte-identical.

# Filled from the exact reviewed ORM tables (pdos_next.agent.memory.m3_models).
TABLE_SQL = (
    "\nCREATE TABLE memory_review_items (\n\tsource VARCHAR(16) NOT NULL, \n\tkind VARCHAR(16) NOT NULL, \n\tassignee_id UUID NOT NULL, \n\traised_by UUID, \n\trun_id UUID, \n\tmark_id UUID, \n\tparent_id UUID, \n\tscope_kind VARCHAR(16) NOT NULL, \n\tcategory_id UUID, \n\tscope_id UUID, \n\tobject_kind VARCHAR(24), \n\tobject_id UUID, \n\trecorded_version INTEGER, \n\tcurrent_version INTEGER, \n\tnote_kind VARCHAR(16), \n\tnote_id UUID, \n\tnote_revision INTEGER, \n\ttarget_kind VARCHAR(16), \n\ttarget_key VARCHAR(80), \n\ttarget_version VARCHAR(40), \n\treasons JSONB NOT NULL, \n\ttext TEXT, \n\tproposed_kind VARCHAR(24), \n\tevent_id UUID, \n\tdedupe_key VARCHAR(64) NOT NULL, \n\trequest_key UUID, \n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (tenant_id, id), \n\tUNIQUE (tenant_id, dedupe_key), \n\tFOREIGN KEY(tenant_id, assignee_id) REFERENCES principals (tenant_id, id), \n\tFOREIGN KEY(tenant_id, raised_by) REFERENCES principals (tenant_id, id), \n\tFOREIGN KEY(tenant_id, run_id) REFERENCES agent_runs (tenant_id, id), \n\tFOREIGN KEY(tenant_id, parent_id) REFERENCES memory_review_items (tenant_id, id), \n\tCONSTRAINT memory_review_item_source CHECK (source IN ('correction','staleness','departure') AND kind IN ('fact','skill','personal','team','object_updated','author_departed') AND ((source='correction') = (kind IN ('fact','skill','personal','team'))) AND ((source='staleness') = (kind='object_updated')) AND ((source='departure') = (kind='author_departed')) AND ((source='correction') = (raised_by IS NOT NULL AND run_id IS NOT NULL AND mark_id IS NOT NULL AND request_key IS NOT NULL))), \n\tCONSTRAINT memory_review_item_scope CHECK (scope_kind IN ('global','category','product','proposal','project') AND ((scope_kind='global') = (scope_id IS NULL)) AND ((scope_kind='global') = (category_id IS NULL))), \n\tCONSTRAINT memory_review_item_refs CHECK ((object_kind IS NULL OR object_kind IN ('category','product','proposal','project','proposal_decision')) AND ((object_id IS NULL) = (object_kind IS NULL)) AND (note_kind IS NULL OR note_kind IN ('scope_note','personal_note')) AND ((note_id IS NULL) = (note_kind IS NULL)) AND ((note_id IS NULL) = (note_revision IS NULL)) AND (target_kind IS NULL OR target_kind IN ('skill_package','prompt')) AND ((target_kind IS NULL) = (target_key IS NULL))), \n\tCONSTRAINT memory_review_item_shape CHECK ((kind<>'skill' OR target_kind IS NOT NULL) AND (kind NOT IN ('personal','team') OR (text IS NOT NULL AND proposed_kind IS NOT NULL)) AND (kind<>'personal' OR (char_length(text) BETWEEN 1 AND 200 AND proposed_kind IN ('convention','background') AND assignee_id=raised_by)) AND (kind<>'team' OR (char_length(text) BETWEEN 1 AND 300 AND scope_kind<>'global' AND proposed_kind IN ('convention','concern','decision_context','observation'))) AND (kind NOT IN ('fact','skill') OR proposed_kind IS NULL) AND (text IS NULL OR char_length(text) BETWEEN 1 AND 300) AND (kind NOT IN ('object_updated','author_departed') OR (note_id IS NOT NULL AND text IS NULL)) AND (kind<>'object_updated' OR (object_id IS NOT NULL AND current_version IS NOT NULL AND event_id IS NOT NULL))), \n\tCONSTRAINT memory_review_item_json CHECK (jsonb_typeof(reasons)='array' AND dedupe_key ~ '^[0-9a-f]{64}$')\n)\n\n",
    'CREATE INDEX ix_memory_review_items_assignee ON memory_review_items (tenant_id, assignee_id, created_at)',
    'CREATE INDEX ix_memory_review_items_note ON memory_review_items (tenant_id, note_kind, note_id)',
    'CREATE INDEX ix_memory_review_items_raised ON memory_review_items (tenant_id, raised_by, created_at)',
    'CREATE INDEX ix_memory_review_items_tenant_id ON memory_review_items (tenant_id)',
    "\nCREATE TABLE memory_review_decisions (\n\titem_id UUID NOT NULL, \n\tdecided_by UUID NOT NULL, \n\tdecision VARCHAR(16) NOT NULL, \n\tresult JSONB NOT NULL, \n\trequest_key UUID NOT NULL, \n\trequest_sha256 VARCHAR(64) NOT NULL, \n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (tenant_id, id), \n\tUNIQUE (tenant_id, item_id), \n\tUNIQUE (tenant_id, decided_by, request_key), \n\tFOREIGN KEY(tenant_id, item_id) REFERENCES memory_review_items (tenant_id, id), \n\tFOREIGN KEY(tenant_id, decided_by) REFERENCES principals (tenant_id, id), \n\tCONSTRAINT memory_review_decision_kind CHECK (decision IN ('adopted','forwarded','dismissed','resolved')), \n\tCONSTRAINT memory_review_decision_json CHECK (jsonb_typeof(result)='object' AND request_sha256 ~ '^[0-9a-f]{64}$')\n)\n\n",
    'CREATE INDEX ix_memory_review_decisions_tenant_id ON memory_review_decisions (tenant_id)',
    "\nCREATE TABLE skill_revision_candidates (\n\ttarget_kind VARCHAR(16) NOT NULL, \n\ttarget_key VARCHAR(80) NOT NULL, \n\ttarget_version VARCHAR(40) NOT NULL, \n\ttool VARCHAR(80) NOT NULL, \n\treason VARCHAR(40) NOT NULL, \n\twindow_start TIMESTAMP WITH TIME ZONE NOT NULL, \n\twindow_end TIMESTAMP WITH TIME ZONE NOT NULL, \n\tsignal_count INTEGER NOT NULL, \n\tthreshold INTEGER NOT NULL, \n\tsample_run_ids JSONB NOT NULL, \n\tsignal_sources JSONB NOT NULL, \n\tsignals_sha256 VARCHAR(64) NOT NULL, \n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (tenant_id, id), \n\tUNIQUE (tenant_id, signals_sha256), \n\tCONSTRAINT skill_revision_candidate_shape CHECK (target_kind IN ('skill_package','prompt') AND signal_count >= threshold AND threshold > 0 AND window_end > window_start AND jsonb_typeof(sample_run_ids)='array' AND jsonb_array_length(sample_run_ids) BETWEEN 1 AND 10 AND jsonb_typeof(signal_sources)='object' AND signals_sha256 ~ '^[0-9a-f]{64}$')\n)\n\n",
    'CREATE INDEX ix_skill_revision_candidates_target ON skill_revision_candidates (tenant_id, target_kind, target_key, target_version, tool, reason)',
    'CREATE INDEX ix_skill_revision_candidates_tenant_id ON skill_revision_candidates (tenant_id)',
    "\nCREATE TABLE skill_revision_decisions (\n\tcandidate_id UUID NOT NULL, \n\tdecided_by UUID NOT NULL, \n\tdecision VARCHAR(16) NOT NULL, \n\tnote TEXT, \n\tdraft JSONB NOT NULL, \n\trequest_key UUID NOT NULL, \n\trequest_sha256 VARCHAR(64) NOT NULL, \n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (tenant_id, id), \n\tUNIQUE (tenant_id, candidate_id), \n\tUNIQUE (tenant_id, decided_by, request_key), \n\tFOREIGN KEY(tenant_id, candidate_id) REFERENCES skill_revision_candidates (tenant_id, id), \n\tFOREIGN KEY(tenant_id, decided_by) REFERENCES principals (tenant_id, id), \n\tCONSTRAINT skill_revision_decision_shape CHECK (decision IN ('adopt','reject') AND jsonb_typeof(draft)='object' AND ((decision='adopt') = (draft ? 'draft_version')) AND (draft->>'activated') IS NULL AND (note IS NULL OR char_length(note) BETWEEN 1 AND 500) AND request_sha256 ~ '^[0-9a-f]{64}$')\n)\n\n",
    'CREATE INDEX ix_skill_revision_decisions_tenant_id ON skill_revision_decisions (tenant_id)',
    "\nCREATE TABLE memory_system_rule_settings (\n\trule_key VARCHAR(40) NOT NULL, \n\trevision INTEGER NOT NULL, \n\tenabled BOOLEAN NOT NULL, \n\tset_by UUID NOT NULL, \n\trequest_key UUID NOT NULL, \n\trequest_sha256 VARCHAR(64) NOT NULL, \n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (tenant_id, id), \n\tUNIQUE (tenant_id, rule_key, revision), \n\tUNIQUE (tenant_id, set_by, request_key), \n\tFOREIGN KEY(tenant_id, set_by) REFERENCES principals (tenant_id, id), \n\tCONSTRAINT memory_system_rule_setting_shape CHECK (revision > 0 AND rule_key ~ '^[a-z][a-z0-9_]{2,39}$' AND request_sha256 ~ '^[0-9a-f]{64}$')\n)\n\n",
    'CREATE INDEX ix_memory_system_rule_settings_tenant_id ON memory_system_rule_settings (tenant_id)',
    "\nCREATE TABLE memory_maintenance_ledger (\n\ttask VARCHAR(40) NOT NULL, \n\tsubject_key VARCHAR(120) NOT NULL, \n\twatermark VARCHAR(64) NOT NULL, \n\toutcome VARCHAR(16) NOT NULL, \n\tdetail JSONB NOT NULL, \n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (tenant_id, id), \n\tUNIQUE (tenant_id, task, subject_key, watermark), \n\tCONSTRAINT memory_maintenance_ledger_shape CHECK (task ~ '^[a-z][a-z0-9_.:]{2,39}$' AND watermark ~ '^[0-9a-f]{64}$' AND outcome IN ('done','held','skipped') AND jsonb_typeof(detail)='object')\n)\n\n",
    'CREATE INDEX ix_memory_maintenance_ledger_task ON memory_maintenance_ledger (tenant_id, task, created_at)',
    'CREATE INDEX ix_memory_maintenance_ledger_tenant_id ON memory_maintenance_ledger (tenant_id)',
)

TABLES = (
    "memory_review_items", "memory_review_decisions", "skill_revision_candidates",
    "skill_revision_decisions", "memory_system_rule_settings", "memory_maintenance_ledger",
)

_TENANT = "tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid"
_OWNER = "SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp"
_REVOKED = "PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch"


def _self(table):
    """An active human acting for themself; the AI writer identity never satisfies this."""
    return f"""{_TENANT}
 AND public.scope_actor()=public.scope_requester()
 AND EXISTS(SELECT 1 FROM public.principals p WHERE p.tenant_id={table}.tenant_id
   AND p.id=public.scope_requester() AND p.kind='human' AND p.active)"""


_ADMIN = f"{_TENANT} AND public.account_administrator()"

_ITEM_READ = f"""{_self('memory_review_items')}
 AND (assignee_id=public.scope_requester() OR raised_by=public.scope_requester())"""

# A correction route: the person's own correction mark on the episode of this Run;
# the assignee is an active person; only a team route or a forwarded fact route may
# name someone else (the code checks who: the scope's owner or the object's owner).
_ITEM_ADMIT = f"""{_self('memory_review_items')}
 AND source='correction' AND raised_by=public.scope_requester()
 AND EXISTS(SELECT 1 FROM public.memory_episode_marks m JOIN public.memory_episodes e
   ON e.tenant_id=m.tenant_id AND e.id=m.episode_id
   WHERE m.tenant_id=memory_review_items.tenant_id AND m.id=memory_review_items.mark_id
   AND m.kind='correction' AND m.owner_id=memory_review_items.raised_by
   AND e.run_id=memory_review_items.run_id)
 AND EXISTS(SELECT 1 FROM public.principals p WHERE p.tenant_id=memory_review_items.tenant_id
   AND p.id=memory_review_items.assignee_id AND p.kind='human' AND p.active)
 AND (assignee_id=raised_by OR kind='team' OR (kind='fact' AND parent_id IS NOT NULL))
 AND (parent_id IS NULL OR public.memory_review_parent(tenant_id, parent_id, raised_by, mark_id))"""

_DECISION_READ = f"""{_self('memory_review_decisions')}
 AND (decided_by=public.scope_requester() OR EXISTS(SELECT 1 FROM public.memory_review_items i
   WHERE i.tenant_id=memory_review_decisions.tenant_id AND i.id=memory_review_decisions.item_id))"""

_DECISION_ADMIT = f"""{_self('memory_review_decisions')}
 AND decided_by=public.scope_requester()
 AND EXISTS(SELECT 1 FROM public.memory_review_items i
   WHERE i.tenant_id=memory_review_decisions.tenant_id AND i.id=memory_review_decisions.item_id
   AND i.assignee_id=memory_review_decisions.decided_by)"""

# ---------------------------------------------------------------------------
# Deterministic system-rule functions (no model, no copied text).

ANCHOR_OWNER_SQL = f"""
CREATE FUNCTION public.memory_anchor_owner(t uuid, kind text, c uuid, product uuid, proposal uuid, project uuid) RETURNS uuid
 LANGUAGE sql STABLE {_OWNER} AS $m3$
 SELECT CASE kind
  WHEN 'category' THEN (SELECT x.owner_id FROM public.categories x WHERE x.tenant_id=t AND x.id=c)
  WHEN 'product' THEN (SELECT x.owner_id FROM public.products x WHERE x.tenant_id=t AND x.id=product)
  WHEN 'proposal' THEN (SELECT x.owner_id FROM public.proposals x WHERE x.tenant_id=t AND x.id=proposal)
  ELSE (SELECT x.owner_id FROM public.projects x WHERE x.tenant_id=t AND x.id=project) END
$m3$
"""

# Same rule as scope_notes.reads.departed (P87 第 5 项): account stopped, category grant
# gone, or every project stint of a non-owner author has ended.
DEPARTED_SQL = f"""
CREATE FUNCTION public.memory_author_departed(t uuid, note uuid) RETURNS boolean
 LANGUAGE sql STABLE {_OWNER} AS $m3$
 SELECT EXISTS(SELECT 1 FROM public.scope_notes n JOIN public.principals p
   ON p.tenant_id=n.tenant_id AND p.id=n.author_id
  WHERE n.tenant_id=t AND n.id=note AND p.kind='human' AND (
   NOT p.active
   OR NOT EXISTS(SELECT 1 FROM public.grants g WHERE g.tenant_id=n.tenant_id
     AND g.category_id=n.category_id AND g.principal_id=n.author_id
     AND (g.expires_at IS NULL OR g.expires_at>now()))
   OR (n.anchor_kind='project'
     AND n.author_id IS DISTINCT FROM (SELECT j.owner_id FROM public.projects j
       WHERE j.tenant_id=n.tenant_id AND j.id=n.project_id)
     AND EXISTS(SELECT 1 FROM public.project_members m WHERE m.tenant_id=n.tenant_id
       AND m.project_id=n.project_id AND m.principal_id=n.author_id)
     AND NOT EXISTS(SELECT 1 FROM public.project_members m WHERE m.tenant_id=n.tenant_id
       AND m.project_id=n.project_id AND m.principal_id=n.author_id AND m.left_at IS NULL))))
$m3$
"""

_SCOPE_ID = ("CASE {v}.anchor_kind WHEN 'category' THEN {v}.category_id WHEN 'product' THEN {v}.product_id "
             "WHEN 'proposal' THEN {v}.proposal_id ELSE {v}.project_id END")

_REVIEW_OWNER = ("CASE WHEN h.generated_by='xiaopai' OR public.memory_author_departed(t, h.note_id) "
                 "THEN public.memory_anchor_owner(t, h.anchor_kind, h.category_id, h.product_id, h.proposal_id, h.project_id) "
                 "ELSE (SELECT n.author_id FROM public.scope_notes n WHERE n.tenant_id=t AND n.id=h.note_id) END")

_COLUMNS = ("id, tenant_id, created_at, source, kind, assignee_id, raised_by, run_id, mark_id, parent_id, "
            "scope_kind, category_id, scope_id, object_kind, object_id, recorded_version, current_version, "
            "note_kind, note_id, note_revision, target_kind, target_key, target_version, reasons, text, "
            "proposed_kind, event_id, dedupe_key, request_key")

# 改版标待复核 (§7.5, §14.6, §14.9 记忆失效检查): every active note whose current version
# references the event's object at an older version is flagged for its review owner.
FLAG_OBJECT_SQL = f"""
CREATE FUNCTION public.memory_flag_object_update(t uuid, event uuid) RETURNS integer
 LANGUAGE plpgsql {_OWNER} AS $m3$
DECLARE subject uuid; rev integer; ev_type text; ev_at timestamptz; product uuid; exact boolean := true;
 scoped integer; personal integer;
BEGIN
 SELECT o.subject_id, o.subject_revision, o.type, o.created_at, r.product_id
  INTO subject, rev, ev_type, ev_at, product
  FROM public.outbox_events o LEFT JOIN public.action_receipts r ON r.tenant_id=o.tenant_id AND r.id=o.receipt_id
  WHERE o.tenant_id=t AND o.id=event;
 IF ev_type='change.effectivity_recorded' THEN
  -- 变更生效: the change order itself is never a note's object; its product is. Its
  -- effective configuration changed even when the product row kept its revision, so
  -- every reference written before the event is an older version.
  subject := product;
  rev := (SELECT x.revision FROM public.products x WHERE x.tenant_id=t AND x.id=product);
  exact := false;
 END IF;
 IF subject IS NULL OR rev IS NULL THEN RETURN 0; END IF;
 WITH latest AS (
  SELECT DISTINCT ON (v.note_id) v.* FROM public.scope_note_versions v
  WHERE v.tenant_id=t ORDER BY v.note_id, v.revision DESC),
 hit AS (
  SELECT l.*, x.ref_kind, x.recorded FROM latest l
  CROSS JOIN LATERAL (
   SELECT q.ref_kind, q.recorded FROM (
    SELECT l.subject_kind::text AS ref_kind, l.subject_version AS recorded
     WHERE l.subject_id=subject AND (l.subject_version<rev OR (NOT exact AND l.created_at<ev_at))
    UNION ALL SELECT l.formal_kind::text, l.formal_version
     WHERE l.formal_id=subject AND (l.formal_version<rev OR (NOT exact AND l.created_at<ev_at))
    UNION ALL SELECT e.source_kind::text, e.source_version FROM public.scope_note_evidence e
     WHERE e.tenant_id=t AND e.note_id=l.note_id AND e.source_type='business_object'
      AND e.source_id=subject AND (e.source_version<rev OR (NOT exact AND e.created_at<ev_at)) AND e.retracts_id IS NULL
      AND NOT EXISTS(SELECT 1 FROM public.scope_note_evidence r WHERE r.tenant_id=t AND r.retracts_id=e.id)
   ) q ORDER BY q.recorded LIMIT 1) x
  WHERE l.lifecycle='active')
 INSERT INTO public.memory_review_items({_COLUMNS})
 SELECT gen_random_uuid(), t, now(), 'staleness', 'object_updated', o.owner, NULL, NULL, NULL, NULL,
  h.anchor_kind, h.category_id, {_SCOPE_ID.format(v='h')}, h.ref_kind, subject, h.recorded, rev,
  'scope_note', h.note_id, h.revision, NULL, NULL, NULL, '[]'::jsonb, NULL, NULL, event,
  encode(sha256(convert_to(concat_ws(':', 'object_updated', 'scope_note', h.note_id, h.revision, subject, rev, CASE WHEN exact THEN '' ELSE event::text END), 'UTF8')), 'hex'),
  NULL
 FROM hit h CROSS JOIN LATERAL (SELECT {_REVIEW_OWNER} AS owner) o
 WHERE o.owner IS NOT NULL AND EXISTS(SELECT 1 FROM public.principals p WHERE p.tenant_id=t
  AND p.id=o.owner AND p.kind='human' AND p.active)
 ON CONFLICT (tenant_id, dedupe_key) DO NOTHING;
 GET DIAGNOSTICS scoped = ROW_COUNT;
 WITH latest AS (
  SELECT DISTINCT ON (v.note_id) v.* FROM public.memory_note_versions v
  WHERE v.tenant_id=t ORDER BY v.note_id, v.revision DESC)
 INSERT INTO public.memory_review_items({_COLUMNS})
 SELECT gen_random_uuid(), t, now(), 'staleness', 'object_updated', l.owner_id, NULL, NULL, NULL, NULL,
  l.scope_kind, l.category_id, l.scope_id, l.target_kind, subject, l.target_version, rev,
  'personal_note', l.note_id, l.revision, NULL, NULL, NULL, '[]'::jsonb, NULL, NULL, event,
  encode(sha256(convert_to(concat_ws(':', 'object_updated', 'personal_note', l.note_id, l.revision, subject, rev, CASE WHEN exact THEN '' ELSE event::text END), 'UTF8')), 'hex'),
  NULL
 FROM latest l WHERE l.status='active' AND l.target_id=subject
  AND (l.target_version<rev OR (NOT exact AND l.created_at<ev_at))
  AND EXISTS(SELECT 1 FROM public.principals p WHERE p.tenant_id=t AND p.id=l.owner_id
   AND p.kind='human' AND p.active)
 ON CONFLICT (tenant_id, dedupe_key) DO NOTHING;
 GET DIAGNOSTICS personal = ROW_COUNT;
 RETURN scoped + personal;
END
$m3$
"""

# 作者离开后的复核转交 (P87 第 5 项; D508): once per note, to the attached object's owner.
FLAG_DEPARTED_SQL = f"""
CREATE FUNCTION public.memory_flag_departed_authors(t uuid) RETURNS integer
 LANGUAGE plpgsql {_OWNER} AS $m3$
DECLARE added integer;
BEGIN
 WITH latest AS (
  SELECT DISTINCT ON (v.note_id) v.* FROM public.scope_note_versions v
  WHERE v.tenant_id=t ORDER BY v.note_id, v.revision DESC),
 gone AS (
  SELECT h.*, public.memory_anchor_owner(t, h.anchor_kind, h.category_id, h.product_id, h.proposal_id, h.project_id) AS owner,
   n.author_id FROM latest h JOIN public.scope_notes n ON n.tenant_id=t AND n.id=h.note_id
  WHERE h.lifecycle='active' AND h.generated_by<>'xiaopai' AND public.memory_author_departed(t, h.note_id))
 INSERT INTO public.memory_review_items({_COLUMNS})
 SELECT gen_random_uuid(), t, now(), 'departure', 'author_departed', g.owner, NULL, NULL, NULL, NULL,
  g.anchor_kind, g.category_id, {_SCOPE_ID.format(v='g')}, NULL, NULL, NULL, NULL,
  'scope_note', g.note_id, g.revision, NULL, NULL, NULL, '[]'::jsonb, NULL, NULL, NULL,
  encode(sha256(convert_to(concat_ws(':', 'author_departed', g.note_id, g.owner), 'UTF8')), 'hex'), NULL
 FROM gone g WHERE g.owner IS NOT NULL AND g.owner<>g.author_id
  AND EXISTS(SELECT 1 FROM public.principals p WHERE p.tenant_id=t AND p.id=g.owner
   AND p.kind='human' AND p.active)
 ON CONFLICT (tenant_id, dedupe_key) DO NOTHING;
 GET DIAGNOSTICS added = ROW_COUNT;
 RETURN added;
END
$m3$
"""

# 程序性信号 (§6.4, §14.8): run feedback by category and explicit source exclusions, per
# loaded skill version (or the main prompt version when no skill was loaded). The tool
# dimension stays '' until tool failures carry a reason class (D246).
SIGNALS_SQL = f"""
CREATE FUNCTION public.memory_procedural_signals(t uuid, as_of timestamptz)
 RETURNS TABLE(run_id uuid, event_id uuid, created_at timestamptz, source text, reason text,
  target_kind text, target_key text, target_version text)
 LANGUAGE sql STABLE {_OWNER} AS $m3$
 WITH feedback AS (
  SELECT e.run_id, e.id AS event_id, e.created_at, 'run_feedback'::text AS source, c.reason,
   e.body#>'{{versions,skills}}' AS skills
  FROM public.agent_run_events e
  CROSS JOIN LATERAL jsonb_array_elements_text(CASE WHEN jsonb_typeof(e.body#>'{{request,categories}}')='array'
   THEN e.body#>'{{request,categories}}' ELSE '[]'::jsonb END) AS c(reason)
  WHERE e.tenant_id=t AND e.body->>'type'='run_feedback'
   AND e.created_at>as_of-interval '30 days' AND e.created_at<=as_of
  UNION ALL
  SELECT e.run_id, e.id, e.created_at, 'retrieval_feedback', 'excluded_source',
   (SELECT coalesce(jsonb_agg(DISTINCT jsonb_build_object('key', s.body->>'key', 'version', s.body->>'version')), '[]'::jsonb)
    FROM public.agent_run_events s WHERE s.tenant_id=t AND s.run_id=e.run_id AND s.body->>'type'='skill_loaded')
  FROM public.agent_run_events e
  WHERE e.tenant_id=t AND e.body->>'type'='retrieval_feedback'
   AND e.created_at>as_of-interval '30 days' AND e.created_at<=as_of)
 SELECT DISTINCT f.run_id, f.event_id, f.created_at, f.source, f.reason,
  'skill_package'::text, s->>'key', s->>'version'
 FROM feedback f CROSS JOIN LATERAL jsonb_array_elements(CASE WHEN jsonb_typeof(f.skills)='array'
  THEN f.skills ELSE '[]'::jsonb END) s
 WHERE coalesce(s->>'key','')<>'' AND coalesce(s->>'version','')<>''
 UNION ALL
 SELECT f.run_id, f.event_id, f.created_at, f.source, f.reason, 'prompt', 'xiaopai.main',
  coalesce(r.versions#>>'{{prompt_identities,main,version}}', 'unversioned')
 FROM feedback f JOIN public.agent_runs r ON r.tenant_id=t AND r.id=f.run_id
 WHERE jsonb_typeof(f.skills) IS DISTINCT FROM 'array' OR NOT EXISTS(
  SELECT 1 FROM jsonb_array_elements(f.skills) s WHERE coalesce(s->>'key','')<>'')
$m3$
"""

# Daily summary: a group with an undecided candidate gets no new one; after a decision
# only signals newer than that candidate's window count again.
SUMMARIZE_SQL = f"""
CREATE FUNCTION public.memory_summarize_procedural(t uuid, as_of timestamptz, threshold integer) RETURNS integer
 LANGUAGE plpgsql {_OWNER} AS $m3$
DECLARE added integer;
BEGIN
 IF threshold IS NULL OR threshold < 1 OR threshold > 1000 THEN
  RAISE EXCEPTION 'Procedural threshold out of range';
 END IF;
 WITH signals AS (SELECT * FROM public.memory_procedural_signals(t, as_of)),
 eligible AS (
  SELECT s.* FROM signals s
  WHERE NOT EXISTS(SELECT 1 FROM public.skill_revision_candidates c
    WHERE c.tenant_id=t AND c.target_kind=s.target_kind AND c.target_key=s.target_key
     AND c.target_version=s.target_version AND c.tool='' AND c.reason=s.reason
     AND NOT EXISTS(SELECT 1 FROM public.skill_revision_decisions d WHERE d.tenant_id=t AND d.candidate_id=c.id))
   AND s.created_at > coalesce((SELECT max(c.window_end) FROM public.skill_revision_candidates c
    WHERE c.tenant_id=t AND c.target_kind=s.target_kind AND c.target_key=s.target_key
     AND c.target_version=s.target_version AND c.tool='' AND c.reason=s.reason), '-infinity'::timestamptz)),
 grouped AS (
  SELECT target_kind, target_key, target_version, reason, count(*)::integer AS n,
   (array_agg(DISTINCT run_id::text))[1:5] AS samples,
   count(*) FILTER (WHERE source='run_feedback')::integer AS feedback,
   count(*) FILTER (WHERE source='retrieval_feedback')::integer AS exclusions
  FROM eligible GROUP BY 1, 2, 3, 4 HAVING count(*) >= threshold)
 INSERT INTO public.skill_revision_candidates(id, tenant_id, created_at, target_kind, target_key,
  target_version, tool, reason, window_start, window_end, signal_count, threshold, sample_run_ids,
  signal_sources, signals_sha256)
 SELECT gen_random_uuid(), t, now(), g.target_kind, g.target_key, g.target_version, '', g.reason,
  as_of-interval '30 days', as_of, g.n, threshold, to_jsonb(g.samples),
  jsonb_build_object('run_feedback', g.feedback, 'retrieval_feedback', g.exclusions, 'tool_errors', 0),
  encode(sha256(convert_to(concat_ws(':', 'skill-revision/v1', g.target_kind, g.target_key, g.target_version,
   '', g.reason, as_of::date), 'UTF8')), 'hex')
 FROM grouped g
 ON CONFLICT (tenant_id, signals_sha256) DO NOTHING;
 GET DIAGNOSTICS added = ROW_COUNT;
 RETURN added;
END
$m3$
"""

# 纠正汇总 for the review page: counts only, administrators only.
OVERVIEW_SQL = f"""
CREATE FUNCTION public.memory_procedural_overview(t uuid, as_of timestamptz)
 RETURNS TABLE(target_kind text, target_key text, target_version text, reason text,
  signal_count integer, run_count integer)
 LANGUAGE plpgsql STABLE {_OWNER} AS $m3$
BEGIN
 IF t IS DISTINCT FROM nullif(current_setting('pdos.tenant_id',true),'')::uuid
  OR NOT public.account_administrator() THEN
  RAISE EXCEPTION 'Procedural overview requires a current tenant administrator' USING ERRCODE='42501';
 END IF;
 RETURN QUERY SELECT s.target_kind, s.target_key, s.target_version, s.reason,
  count(*)::integer, count(DISTINCT s.run_id)::integer
 FROM public.memory_procedural_signals(t, as_of) s GROUP BY 1, 2, 3, 4 ORDER BY 5 DESC, 1, 2, 3, 4;
END
$m3$
"""

RULE_ENABLED_SQL = f"""
CREATE FUNCTION public.memory_system_rule_enabled(t uuid, rule text) RETURNS boolean
 LANGUAGE sql STABLE {_OWNER} AS $m3$
 SELECT coalesce((SELECT s.enabled FROM public.memory_system_rule_settings s
  WHERE s.tenant_id=t AND s.rule_key=rule ORDER BY s.revision DESC LIMIT 1), true)
$m3$
"""

LEDGER_TASKS = ("fanout.staleness", "fanout.distillation", "fanout.scope_recent", "fanout.index",
                "daily.departure", "daily.procedural")

LEDGER_SQL = f"""
CREATE FUNCTION public.memory_ledger_record(t uuid, task_key text, subject text, mark text,
 result text, extra jsonb) RETURNS boolean
 LANGUAGE plpgsql {_OWNER} AS $m3$
DECLARE added integer;
BEGIN
 IF task_key NOT IN ({",".join(repr(task) for task in LEDGER_TASKS)}) THEN
  RAISE EXCEPTION 'Unknown memory maintenance task';
 END IF;
 INSERT INTO public.memory_maintenance_ledger(id, tenant_id, created_at, task, subject_key, watermark, outcome, detail)
 VALUES (gen_random_uuid(), t, now(), task_key, subject, mark, result, extra)
 ON CONFLICT (tenant_id, task, subject_key, watermark) DO NOTHING;
 GET DIAGNOSTICS added = ROW_COUNT;
 RETURN added = 1;
END
$m3$
"""

# A further route hangs on an earlier route of the same correction by the same person.
# (A policy cannot query its own table; this reads it as the owner.)
PARENT_SQL = f"""
CREATE FUNCTION public.memory_review_parent(t uuid, parent uuid, raiser uuid, mark uuid) RETURNS boolean
 LANGUAGE sql STABLE {_OWNER} AS $m3$
 SELECT EXISTS(SELECT 1 FROM public.memory_review_items i WHERE i.tenant_id=t AND i.id=parent
  AND i.source='correction' AND i.raised_by=raiser AND i.mark_id=mark)
$m3$
"""

FUNCTIONS = (
    ("memory_review_parent(uuid,uuid,uuid,uuid)", PARENT_SQL, True),
    ("memory_anchor_owner(uuid,text,uuid,uuid,uuid,uuid)", ANCHOR_OWNER_SQL, False),
    ("memory_author_departed(uuid,uuid)", DEPARTED_SQL, False),
    ("memory_flag_object_update(uuid,uuid)", FLAG_OBJECT_SQL, True),
    ("memory_flag_departed_authors(uuid)", FLAG_DEPARTED_SQL, True),
    ("memory_procedural_signals(uuid,timestamptz)", SIGNALS_SQL, False),
    ("memory_summarize_procedural(uuid,timestamptz,integer)", SUMMARIZE_SQL, True),
    ("memory_procedural_overview(uuid,timestamptz)", OVERVIEW_SQL, True),
    ("memory_system_rule_enabled(uuid,text)", RULE_ENABLED_SQL, True),
    ("memory_ledger_record(uuid,text,text,text,text,jsonb)", LEDGER_SQL, True),
)

SECURITY_SQL = (
    *(statement for table in TABLES for statement in (
        f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY",
        f"CREATE POLICY owner_internal ON public.{table} TO pdos_next_owner USING(true) WITH CHECK(true)",
        f"REVOKE ALL ON public.{table} FROM {_REVOKED}",
        f"CREATE TRIGGER {table}_no_update BEFORE UPDATE ON public.{table} "
        "FOR EACH ROW EXECUTE FUNCTION public.kernel_append_only()",
        f"CREATE TRIGGER {table}_no_delete BEFORE DELETE ON public.{table} "
        "FOR EACH ROW EXECUTE FUNCTION public.kernel_append_only()",
    )),
    *(statement for signature, body, granted in FUNCTIONS for statement in (
        body,
        f"REVOKE ALL ON FUNCTION public.{signature} FROM PUBLIC",
        *((f"GRANT EXECUTE ON FUNCTION public.{signature} TO pdos_next_app",) if granted else ()),
    )),
    f"CREATE POLICY memory_review_items_read ON public.memory_review_items FOR SELECT TO pdos_next_app USING({_ITEM_READ})",
    f"CREATE POLICY memory_review_items_admit ON public.memory_review_items FOR INSERT TO pdos_next_app WITH CHECK({_ITEM_ADMIT})",
    "GRANT SELECT,INSERT ON public.memory_review_items TO pdos_next_app",
    f"CREATE POLICY memory_review_decisions_read ON public.memory_review_decisions FOR SELECT TO pdos_next_app USING({_DECISION_READ})",
    f"CREATE POLICY memory_review_decisions_admit ON public.memory_review_decisions FOR INSERT TO pdos_next_app WITH CHECK({_DECISION_ADMIT})",
    "GRANT SELECT,INSERT ON public.memory_review_decisions TO pdos_next_app",
    f"CREATE POLICY skill_revision_candidates_read ON public.skill_revision_candidates FOR SELECT TO pdos_next_app USING({_ADMIN})",
    "GRANT SELECT ON public.skill_revision_candidates TO pdos_next_app",
    f"CREATE POLICY skill_revision_decisions_read ON public.skill_revision_decisions FOR SELECT TO pdos_next_app USING({_ADMIN})",
    f"CREATE POLICY skill_revision_decisions_admit ON public.skill_revision_decisions FOR INSERT TO pdos_next_app "
    f"WITH CHECK({_ADMIN} AND decided_by=public.scope_actor())",
    "GRANT SELECT,INSERT ON public.skill_revision_decisions TO pdos_next_app",
    f"CREATE POLICY memory_system_rule_settings_read ON public.memory_system_rule_settings FOR SELECT TO pdos_next_app USING({_ADMIN})",
    f"CREATE POLICY memory_system_rule_settings_admit ON public.memory_system_rule_settings FOR INSERT TO pdos_next_app "
    f"WITH CHECK({_ADMIN} AND set_by=public.scope_actor())",
    "GRANT SELECT,INSERT ON public.memory_system_rule_settings TO pdos_next_app",
    f"CREATE POLICY memory_maintenance_ledger_read ON public.memory_maintenance_ledger FOR SELECT TO pdos_next_app USING({_ADMIN})",
    "GRANT SELECT ON public.memory_maintenance_ledger TO pdos_next_app",
)

SCHEMA_SQL = (*TABLE_SQL, *SECURITY_SQL)

DOWNGRADE_SQL = (
    *(f"ALTER TABLE public.{table} NO FORCE ROW LEVEL SECURITY" for table in TABLES),
    """DO $$ BEGIN IF EXISTS(SELECT 1 FROM public.memory_review_items)
     OR EXISTS(SELECT 1 FROM public.skill_revision_candidates)
     OR EXISTS(SELECT 1 FROM public.memory_system_rule_settings)
     OR EXISTS(SELECT 1 FROM public.memory_maintenance_ledger) THEN
     RAISE EXCEPTION 'Memory M3 requires s0_0920'; END IF; END $$""",
    *(f"DROP TABLE public.{table}" for table in reversed(TABLES)),
    *(f"DROP FUNCTION public.{signature}" for signature, _body, _granted in reversed(FUNCTIONS)),
)
