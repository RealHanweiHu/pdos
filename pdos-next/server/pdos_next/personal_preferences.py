"""Self-owned settings and authorized navigation suggestions, never authority."""

from urllib.parse import urlencode
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import load_only

from pdos_next.clock import now
from pdos_next.database import require_context
from pdos_next.domain.projects.models import Project
from pdos_next.errors import DomainError
from pdos_next.models import Category, Principal
from pdos_next.personal_preference_models import PersonalPreference
from pdos_next.personal_preference_schemas import NavigationOptions, Preferences, PreferenceSave
from pdos_next.service import digest

ROLE_DEFAULTS = {
    "product": ["梳理产品需求中的待确认项", "整理品类资料并列出下一步"],
    "engineering": ["整理当前项目的技术待办", "比较资料版本并列出差异"],
    "quality": ["查找类似质量问题的处理记录", "整理待复验事项与负责人"],
    "manufacturing": ["查看试制准备与待办", "整理制造问题及下一步"],
    "supply": ["整理供应承诺与外部等待", "查看物料交付的待跟进项"],
    "management": ["汇总项目变化与待决定事项", "整理需要协调的工作"],
    "other": ["整理我的待办与下一步", "帮我解释或改写一段文字"],
}


def _identity(session, ctx, *, runtime=False):
    if runtime:
        from pdos_next.service import Context

        ctx = Context(ctx.tenant_id, ctx.writer_id, ctx.requester_id, category_id=ctx.category_id)
    require_context(session, ctx)
    if not runtime and (
        ctx.actor_id != ctx.requester_id or ctx.category_id is not None
        or ctx.run_id is not None or ctx.agent_run_id is not None
    ):
        raise DomainError("FORBIDDEN_SCOPE", "个人偏好须由本人账户显式设置。", 403)
    owner = session.scalar(select(Principal).where(
        Principal.tenant_id == ctx.tenant_id, Principal.id == ctx.requester_id,
        Principal.active.is_(True), Principal.kind == "human",
    ))
    if owner is None:
        raise DomainError("FORBIDDEN_SCOPE", "当前本人账户不可用。", 403)
    return ctx


def _row(session, ctx):
    return session.scalar(select(PersonalPreference).where(
        PersonalPreference.tenant_id == ctx.tenant_id,
        PersonalPreference.owner_id == ctx.requester_id,
    ))


def _options_query(ctx, kind):
    model = Category if kind == "category" else Project
    fields = [model.id, model.tenant_id, model.name]
    if kind == "project":
        fields.extend([model.category_id, model.product_id])
    return select(model).options(load_only(*fields)).where(
        model.tenant_id == ctx.tenant_id, model.status == "active",
    )


def _candidate(row, kind):
    category_id = row.id if kind == "category" else row.category_id
    params = {"area": "projects" if kind == "category" else "cockpit",
              "category": str(category_id)}
    if kind == "project":
        params.update(project=str(row.id), product=str(row.product_id), projectView="now")
    return {
        "kind": kind, "id": str(row.id), "label": row.name,
        "category_id": str(category_id),
        "product_id": None if kind == "category" else str(row.product_id),
        "href": "?" + urlencode(params),
    }


def navigation_candidates(session, ctx, preferences):
    """Batch recheck against authoritative RLS tables; no stored audience copies."""
    candidates = []
    for kind, identities in (("category", preferences.favorite_category_ids),
                             ("project", preferences.favorite_project_ids)):
        if not identities:
            continue
        model = Category if kind == "category" else Project
        rows = {row.id: row for row in session.scalars(
            _options_query(ctx, kind).where(model.id.in_(identities))
        )}
        candidates.extend(_candidate(rows[identity], kind) for identity in identities
                          if identity in rows)
    return candidates


def role_defaults(preferences):
    return {
        "welcome_examples": list(ROLE_DEFAULTS.get(preferences.role, [])),
        "summary_sections": ["变化", "与我何关", "谁做什么", "从哪继续"]
        if preferences.role else [],
    }


def _view(session, ctx, row):
    preferences = Preferences.model_validate(row.body) if row else Preferences()
    return {
        "revision": row.revision if row else 0,
        "preferences": preferences.model_dump(mode="json"),
        "navigation_candidates": navigation_candidates(session, ctx, preferences),
        "role_defaults": role_defaults(preferences),
        "updated_at": row.updated_at.isoformat() if row else None,
    }


def read(session, ctx):
    _identity(session, ctx)
    return _view(session, ctx, _row(session, ctx))


def save(session, ctx, data: PreferenceSave):
    _identity(session, ctx)
    # Serialize first creation too, without granting write access to principals.
    key = int(digest(["personal-preferences", ctx.tenant_id, ctx.requester_id])[:16], 16)
    if key >= 2**63:
        key -= 2**64
    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
    row = _row(session, ctx)
    revision = row.revision if row else 0
    body = data.preferences.model_dump(mode="json")
    current = row.body if row else Preferences().model_dump(mode="json")
    # A retry after a lost response is a read when the exact values already won.
    if body == current:
        return _view(session, ctx, row)
    if data.expected_revision != revision:
        raise DomainError("VERSION_CONFLICT", "个人偏好已更新，请重新读取后再保存。", 409)
    visible = navigation_candidates(session, ctx, data.preferences)
    available = {(item["kind"], item["id"]) for item in visible}
    previous = Preferences.model_validate(current)
    for kind, identities, old in (
        ("category", data.preferences.favorite_category_ids, previous.favorite_category_ids),
        ("project", data.preferences.favorite_project_ids, previous.favorite_project_ids),
    ):
        if any((kind, str(identity)) not in available and identity not in old
               for identity in identities):
            raise DomainError("FORBIDDEN_SCOPE", "只能添加当前本人可读的常用范围。", 403)
    if row is None:
        row = PersonalPreference(tenant_id=ctx.tenant_id, owner_id=ctx.requester_id,
                                 revision=1, body=body, updated_at=now())
        session.add(row)
    else:
        row.body, row.revision, row.updated_at = body, revision + 1, now()
    session.flush()
    return _view(session, ctx, row)


def options(session, ctx, data: NavigationOptions):
    _identity(session, ctx)
    model = Category if data.kind == "category" else Project
    query = _options_query(ctx, data.kind)
    if data.query:
        query = query.where(model.name.icontains(data.query, autoescape=True))
    if data.cursor:
        query = query.where(model.id > data.cursor)
    rows = list(session.scalars(query.order_by(model.id).limit(data.page_size + 1)))
    return {"items": [_candidate(row, data.kind) for row in rows[:data.page_size]],
            "next_cursor": str(rows[data.page_size - 1].id)
            if len(rows) > data.page_size else None}


def context_preferences(session, scope):
    """Called only by the trusted host for its bound requester, read once per Run."""
    ctx = _identity(session, scope, runtime=True)
    row = _row(session, ctx)
    preferences = Preferences.model_validate(row.body) if row else Preferences()
    return {
        "revision": row.revision if row else 0,
        "source": "explicit_user_settings", "use": "personalization_only",
        **preferences.model_dump(exclude={"favorite_category_ids", "favorite_project_ids"}),
        "navigation_candidates": navigation_candidates(session, ctx, preferences),
        "role_defaults": role_defaults(preferences),
    }


def recheck_context_preferences(session, scope, frozen_value):
    """Recheck only frozen navigation identities; never reload explicit settings or names."""
    ctx = _identity(session, scope, runtime=True)
    if not isinstance(frozen_value, dict):
        return False
    candidates = frozen_value.get("navigation_candidates")
    if not isinstance(candidates, list) or len(candidates) > 20:
        return False
    expected = {"category": set(), "project": set()}
    try:
        for item in candidates:
            if not isinstance(item, dict) or item.get("kind") not in expected:
                return False
            expected[item["kind"]].add(UUID(item["id"]))
    except (KeyError, TypeError, ValueError, AttributeError):
        return False
    for kind, identities in expected.items():
        if not identities:
            continue
        model = Category if kind == "category" else Project
        visible = set(session.scalars(select(model.id).where(
            model.tenant_id == ctx.tenant_id, model.status == "active", model.id.in_(identities),
        )))
        if visible != identities:
            return False
    return True


CONTEXT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["revision", "source", "use", "answer_language", "response_detail", "role",
                 "department", "navigation_candidates", "role_defaults"],
    "properties": {
        "revision": {"type": "integer", "minimum": 0},
        "source": {"const": "explicit_user_settings"},
        "use": {"const": "personalization_only"},
        "answer_language": {"enum": ["auto", "zh-CN", "zh-TW", "en", "ja"]},
        "response_detail": {"enum": ["brief", "balanced", "detailed"]},
        "role": {"enum": [None, *ROLE_DEFAULTS]},
        "department": {"type": ["string", "null"], "maxLength": 80},
        "navigation_candidates": {"type": "array", "maxItems": 20, "items": {
            "type": "object", "additionalProperties": False,
            "required": ["kind", "id", "label", "category_id", "product_id", "href"],
            "properties": {
                "kind": {"enum": ["category", "project"]},
                "id": {"type": "string", "format": "uuid"},
                "label": {"type": "string"},
                "category_id": {"type": "string", "format": "uuid"},
                "product_id": {"type": ["string", "null"], "format": "uuid"},
                "href": {"type": "string"},
            },
        }},
        "role_defaults": {"type": "object", "additionalProperties": False,
                          "required": ["welcome_examples", "summary_sections"],
                          "properties": {
                              "welcome_examples": {"type": "array", "items": {"type": "string"},
                                                   "maxItems": 2},
                              "summary_sections": {"type": "array", "items": {"type": "string"},
                                                   "maxItems": 4},
                          }},
    },
}
