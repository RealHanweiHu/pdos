"""Human-selected methods are requests; current tenant policy remains authoritative."""

from pydantic import Field, ValidationError
from sqlalchemy import select

from pdos_next.errors import DomainError
from pdos_next.models import Principal
from pdos_next.schema_base import StrictModel

from .models import AgentEvent
from .policy import skill_enabled
from .skills import SkillCatalog


class RequestedSkill(StrictModel):
    key: str = Field(min_length=1, max_length=160)
    version: str = Field(min_length=1, max_length=160)
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")


def _selection_error(code, reason, message, status=409):
    error = DomainError(code, message, status)
    error.detail["reason"] = reason
    raise error from None


def reading(session, scope):
    actor = session.get(Principal, scope.actor_id)
    if (
        scope.actor_id != scope.requester_id or scope.run_id or scope.agent_run_id
        or not actor or not actor.active or actor.kind != "human"
    ):
        raise DomainError("FORBIDDEN_SCOPE", "请由当前本人会话选择技能。", 403)
    catalog = SkillCatalog()
    items = []
    for entry in catalog.index:
        skill = catalog.configuration(entry["key"])
        if skill is not None:
            items.append({
                "skill_key": skill.key, "purpose": skill.purpose,
                "skill_version": skill.version, "skill_digest": skill.digest,
                "available": True, "enabled": skill_enabled(session, scope, skill),
            })
    return {"items": items, "can_edit": False}


def validate(session, scope, requested, *, catalog=None):
    if not requested:
        return []
    catalog = catalog or SkillCatalog()
    if len({item.key for item in requested}) != len(requested):
        raise DomainError("VALIDATION_FAILED", "同一技能只需选择一次。", 422)
    for item in requested:
        skill = catalog.configuration(item.key)
        if skill is None or not skill_enabled(session, scope, skill):
            _selection_error(
                "FORBIDDEN_SCOPE", "requested_skill_unavailable",
                "所选或沿用的技能当前未启用，请移除或重新选择。", 403,
            )
        if (skill.version, skill.digest) != (item.version, item.digest):
            _selection_error(
                "VERSION_CONFLICT", "requested_skill_version_changed",
                "所选或沿用的技能版本已变化，请移除或重新选择。",
            )
    return [item.model_dump(mode="json") for item in requested]


CONTINUED_SKILL_LIMIT = 2


def recent(session, run_id):
    """Return the last two actual main-load identities, without upgrading or enabling."""
    events = session.scalars(
        select(AgentEvent.body)
        .where(AgentEvent.run_id == run_id, AgentEvent.body["type"].astext == "skill_loaded")
        .order_by(AgentEvent.sequence.desc())
    )
    selected, seen = [], set()
    for body in events:
        if body.get("isolation", "main") != "main":
            continue
        key = body.get("key")
        if isinstance(key, str) and key in seen:
            continue
        try:
            item = RequestedSkill.model_validate({
                name: body.get(name) for name in ("key", "version", "digest")
            })
        except ValidationError:
            _selection_error(
                "VERSION_CONFLICT", "requested_skill_version_changed",
                "上轮技能记录缺少固定版本，请核对原记录或新建对话。",
            )
        selected.append(item)
        seen.add(item.key)
        if len(selected) == CONTINUED_SKILL_LIMIT:
            break
    return selected


def _inherited(session, scope, run_id, *, exclude, excluded):
    choices = recent(session, run_id) if run_id is not None else []
    if (
        len(excluded) > CONTINUED_SKILL_LIMIT
        or any(not isinstance(key, str) or not 1 <= len(key) <= 160 for key in excluded)
        or len(set(excluded)) != len(excluded)
        or not set(excluded) <= {item.key for item in choices}
    ):
        _selection_error(
            "VALIDATION_FAILED", "continued_skill_selection_invalid",
            "移除的技能与上轮延续清单不一致，请重新读取。", 422,
        )
    # Select the actual latest two before removing any; never refill from an
    # older third skill because the Human removed or explicitly selected one.
    items = [item for item in choices if item.key not in exclude and item.key not in excluded]
    validate(session, scope, items)
    return items


def validate_start(session, scope, requested, *, parent=None, excluded=()):
    """Validate before admission; return fixed merged identities for a fresh-session restart."""
    validate(session, scope, requested)
    inherited = _inherited(
        session, scope, parent.id if parent is not None else None,
        exclude={item.key for item in requested}, excluded=excluded,
    )
    return [*requested, *inherited]


def preload(store, scope, fallback=()):
    if scope.isolation != "main" or scope.trigger != "conversation":
        return tuple(fallback)
    with store.transaction(scope) as (session, run):
        event = session.scalar(select(AgentEvent).where(
            AgentEvent.run_id == run.id, AgentEvent.sequence == 1,
        ))
        body = event.body if event else {}
        requested = [
            RequestedSkill.model_validate(item) for item in body.get("requested_skills", [])
        ]
        from .context_restart import KEY, carried_body

        if KEY in getattr(run, "versions", {}):
            carried_body(session, run)
            validate(session, scope, requested)
            # Restart admission stored the complete fixed selection, including
            # an empty selection after Human removals. Defaults must not refill it.
            return tuple(item.key for item in requested)
        validate(session, scope, requested)
        excluded = body.get("excluded_continued_skills", ())
        explicit = tuple(item.key for item in requested)
        base = explicit if requested else tuple(key for key in fallback if key not in excluded)
        inherited = continued(
            session, scope, run, exclude=set(explicit), excluded=excluded,
        )
        return tuple(dict.fromkeys((*base, *inherited)))


def continued(session, scope, run, *, exclude, excluded=()):
    return tuple(item.key for item in _inherited(
        session, scope, run.continued_from_id, exclude=exclude, excluded=excluded,
    ))
