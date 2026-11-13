"""T2 ``evidence.source.withdraw`` and the shared use check (P120 第 1–2 项, D310).

The T1 ``evidence.original.withdraw`` keeps one's own originals that no business
record uses yet. A source already used by business records, or shared to the
category, is withdrawn here by its owner or the category owner as a named
decision. Withdrawal stops new use and marks dependents for recheck (derived on
read); nothing is deleted. Registered artifacts are covered; public research
snapshots are immutable public references and are not.
"""

# ruff: noqa: E501 -- finite SQL functions stay readable as complete statements.

from sqlalchemy import select, text

from pdos_next.core.models import Artifact, Category
from pdos_next.domain.projects.work.rules import require

# Command plumbing and the source's own storage, scans and search index are not use.
PLUMBING = frozenset(
    {
        "uploaded_originals",
        "artifact_versions",
        "action_receipts",
        "request_keys",
        "confirmations",
        "outbox_events",
        "audit_entries",
    }
)
PLUMBING_PREFIXES = ("original_", "upload_", "lifecycle_", "enterprise_search_")


EFFECT = (
    "撤回后停止下载、解析、检索与新的业务引用，并清理企业检索中的内容；已使用它的结果保留，"
    "改为“需重核”，不级联删除。原件字节、历史决定与回执保留。"
)


from .source_withdraw_schemas import OPERATION, PAYLOADS, SourceWithdrawPayload  # noqa: E402,F401


def dependents(s, ctx, product_id, source_id):
    """Business tables that use this source (counts only); empty when nothing uses it."""
    rows = s.execute(
        text("SELECT table_name, reference_count FROM d47_source_dependents(:t,:c,:p,:root)"),
        {"t": ctx.tenant_id, "c": ctx.category_id, "p": product_id, "root": source_id},
    ).all()
    return [
        {"table": name, "count": count}
        for name, count in rows
        if name not in PLUMBING and not name.startswith(PLUMBING_PREFIXES)
    ]


def signed(s, ctx, product_id, source_id):
    """P9: used by a signed decision (sealed/published definition, or a consumed claim)."""
    return bool(
        s.scalar(
            text("SELECT d47_source_signed(:t,:c,:p,:root)"),
            {"t": ctx.tenant_id, "c": ctx.category_id, "p": product_id, "root": source_id},
        )
    )


def semantic(payload):
    return payload.model_dump(mode="json", exclude={"approval_token"})


def _source(s, ctx, product, payload):
    from pdos_next.originals.access import require_original
    from pdos_next.originals.security import security_row

    product_id = product.id
    if payload.kind == "original":
        original = require_original(s, ctx, product_id, payload.source_id, lock=True)
        state = security_row(s, original)
        require(state.source_state == "active", "来源已撤回。", "VERSION_CONFLICT")
        require(
            state.epoch == payload.expected_revision,
            "原件安全状态已变化，请重新预览。",
            "VERSION_CONFLICT",
        )
        return original, state, original.owner_id, original.visibility, original.title
    artifact = s.scalar(
        select(Artifact)
        .where(
            Artifact.tenant_id == ctx.tenant_id,
            Artifact.category_id == ctx.category_id,
            Artifact.id == payload.source_id,
            Artifact.product_id.is_(None) | (Artifact.product_id == product_id),
        )
        .with_for_update()
    )
    require(artifact is not None, "来源不在当前授权范围。", "SOURCE_UNAVAILABLE", 403)
    require(artifact.original_id is None, "由原件生成的资料请按原件撤回。", "VALIDATION_FAILED")
    require(artifact.status == "active", "来源已撤回。", "VERSION_CONFLICT")
    require(
        artifact.revision == payload.expected_revision,
        "登记资料已变化，请重新预览。",
        "VERSION_CONFLICT",
    )
    return artifact, None, artifact.owner_id, artifact.visibility, artifact.title


def validate(s, ctx, command, product, payload):
    from pdos_next.domain.named_records.service import human_only

    human_only(s, ctx)
    require(
        command.expected_revision == product.revision,
        "型号范围已变化，请刷新后重新预览。",
        "VERSION_CONFLICT",
    )
    require(not command.source_read_set, "撤回来源不接受额外来源输入。", "INVALID_PAYLOAD", 422)
    row, state, owner_id, visibility, title = _source(s, ctx, product, payload)
    category = s.get(Category, ctx.category_id)
    authority = (
        "source_owner"
        if owner_id == ctx.requester_id
        else "category_owner"
        if category is not None and category.owner_id == ctx.requester_id
        else None
    )
    require(
        authority is not None, "只有来源负责人或品类负责人可以具名撤回。", "FORBIDDEN_SCOPE", 403
    )
    used = dependents(s, ctx, product.id, payload.source_id)
    decided = signed(s, ctx, product.id, payload.source_id)
    shared = visibility in {"category", "audience"}
    require(
        decided or shared,
        "本人未被使用、也未共享的原件请用一次确认撤回（evidence.original.withdraw）。",
        "VALIDATION_FAILED",
    )
    review = {
        "operation": OPERATION,
        "source": {
            "id": str(payload.source_id),
            "kind": payload.kind,
            "title": title,
            "visibility": visibility,
            "revision": payload.expected_revision,
        },
        "authority": authority,
        "shared": shared,
        "signed_use": decided,
        "dependents": used,
        "after": {"state": "withdrawn", "reason": payload.reason},
        "effect": EFFECT,
    }
    return row, state, review


def preview_view(s, ctx, command, product, payload):
    return validate(s, ctx, command, product, payload)[2]


def apply(s, ctx, command, product, payload):
    row, state, review = validate(s, ctx, command, product, payload)
    if payload.kind == "original":
        state.epoch += 1
        state.source_state = "withdrawn"
        row.revision += 1
        linked = s.scalar(select(Artifact).where(Artifact.original_id == row.id).with_for_update())
        if linked and linked.status == "active":
            linked.status = "withdrawn"
            linked.revision += 1
        subject_type = "uploaded_original"
    else:
        row.status = "withdrawn"
        row.revision += 1
        subject_type = "artifact"
    row.action_result = {
        "source_state": "withdrawn",
        "kind": payload.kind,
        "authority": review["authority"],
        "dependents": review["dependents"],
        "needs_recheck": bool(review["dependents"]),
        "reason": payload.reason,
    }
    return row, subject_type, row.visibility


def check_t1(s, ctx, product_id, original):
    """P120 第 1 项 / P9: the one-confirmation path is for one's own unused originals."""
    require(
        original.owner_id == ctx.requester_id,
        "非本人上传的原件，请由来源负责人或品类负责人具名撤回（evidence.source.withdraw）。",
        "FORBIDDEN_SCOPE",
        403,
    )
    require(
        not signed(s, ctx, product_id, original.id),
        "原件已被签署决定使用，不能一次确认撤回；请走具名撤回（evidence.source.withdraw）。",
        "UNDO_BLOCKED_BY_DEPENDENCY",
    )


FUNCTION = """CREATE FUNCTION public.d47_source_dependents(t uuid, c uuid, p uuid, root uuid)
 RETURNS TABLE(table_name text, reference_count integer)
 LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $source_use$
DECLARE graph jsonb[]='{}'; reached uuid[]; selected integer[]; node jsonb; links uuid[]; row_id uuid; i integer; changed boolean;
BEGIN
 IF NOT category_access(t,c,false) THEN RETURN; END IF;
 IF NOT (
  EXISTS(SELECT 1 FROM public.uploaded_originals WHERE tenant_id=t AND category_id=c AND id=root
   AND product_id IS NOT DISTINCT FROM p AND (owner_id=scope_requester() OR visibility IN ('category','audience'))) OR
  EXISTS(SELECT 1 FROM public.artifact_versions WHERE tenant_id=t AND category_id=c AND id=root
   AND product_id IS NOT DISTINCT FROM p AND (owner_id=scope_requester() OR visibility IN ('category','audience')))
 ) THEN RETURN; END IF;
 SELECT coalesce(array_agg(jsonb_build_object('table',n.table_name,'id',n.node_id,'links',n.links)),'{}')
  INTO graph FROM public.m3_lifecycle_nodes(t,c) n;
 reached=ARRAY[root]; selected='{}'; changed=true;
 WHILE changed LOOP
  changed=false;
  IF cardinality(graph)>0 THEN
   FOR i IN 1..cardinality(graph) LOOP
    IF i=ANY(selected) THEN CONTINUE; END IF;
    node=graph[i]; row_id=(node->>'id')::uuid;
    SELECT coalesce(array_agg(v::uuid),'{}') INTO links FROM jsonb_array_elements_text(node->'links') AS x(v);
    IF row_id=root OR links && reached THEN
     selected=array_append(selected,i);
     IF row_id IS NOT NULL AND NOT row_id=ANY(reached) THEN reached=array_append(reached,row_id); END IF;
     changed=true;
    END IF;
   END LOOP;
  END IF;
 END LOOP;
 RETURN QUERY SELECT graph[k]->>'table', count(*)::integer FROM unnest(selected) AS u(k) GROUP BY 1 ORDER BY 1;
END
$source_use$"""


SIGNED = """CREATE FUNCTION public.d47_source_signed(t uuid, c uuid, p uuid, root uuid)
 RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $source_signed$
 WITH artifacts AS (
  SELECT a.id FROM public.artifact_versions a WHERE a.tenant_id=t AND a.category_id=c
   AND (a.id=root OR a.original_id=root) AND a.product_id IS NOT DISTINCT FROM p
 )
 SELECT category_access(t,c,false) AND (
  EXISTS(SELECT 1 FROM public.definition_sources ds JOIN public.definition_revisions d
   ON d.tenant_id=ds.tenant_id AND d.id=ds.definition_id
   WHERE ds.tenant_id=t AND ds.category_id=c AND ds.artifact_id IN (SELECT id FROM artifacts)
    AND (d.sealed OR d.status='published'))
  OR EXISTS(SELECT 1 FROM public.claims cl WHERE cl.tenant_id=t AND cl.category_id=c
   AND cl.artifact_id IN (SELECT id FROM artifacts) AND public.m3_evidence_signed_consumed(t,c,cl.id)))
$source_signed$"""


def upgrade_sql():
    return (
        SIGNED,
        "REVOKE ALL ON FUNCTION public.d47_source_signed(uuid,uuid,uuid,uuid) FROM PUBLIC,pdos_agent,pdos_next_auth,pdos_next_dispatch",
        "GRANT EXECUTE ON FUNCTION public.d47_source_signed(uuid,uuid,uuid,uuid) TO pdos_next_app",
        FUNCTION,
        "REVOKE ALL ON FUNCTION public.d47_source_dependents(uuid,uuid,uuid,uuid) FROM PUBLIC,pdos_agent,pdos_next_auth,pdos_next_dispatch",
        "GRANT EXECUTE ON FUNCTION public.d47_source_dependents(uuid,uuid,uuid,uuid) TO pdos_next_app",
    )


def downgrade_sql():
    return (
        "DROP FUNCTION public.d47_source_dependents(uuid,uuid,uuid,uuid)",
        "DROP FUNCTION public.d47_source_signed(uuid,uuid,uuid,uuid)",
    )
