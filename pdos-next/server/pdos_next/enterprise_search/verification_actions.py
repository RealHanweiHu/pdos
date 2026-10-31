"""An explicit same-project continuation into a native verification preparation."""

from copy import deepcopy
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import Field

from pdos_next.agent_kernel.models import AgentRun
from pdos_next.agent_kernel.requested_skills import RequestedSkill, validate
from pdos_next.agent_kernel.skills import SkillCatalog
from pdos_next.contracts import SourceRead
from pdos_next.errors import DomainError
from pdos_next.schema_base import StrictModel
from pdos_next.schemas.verification.contracts import BuildRef

from .action_sources import capture, recheck
from .verification_candidates import SKILL, _target


class VerificationAction(StrictModel):
    kind: Literal["prepare_verification"] = "prepare_verification"
    selection: BuildRef
    citation_ids: tuple[UUID, ...] = Field(min_length=1, max_length=20)


def prepare_start(session, ctx, effective, parent, requested):
    if requested is None:
        return effective, None, tuple(effective.requested_skills)
    if parent is None or parent.project_id is None or parent.product_id is None:
        raise DomainError("INVALID_PAYLOAD", "请从当前项目中的引用回答继续准备复验。", 422)
    if (effective.project_id != parent.project_id or effective.product_id != parent.product_id
        or parent.category_id != ctx.category_id):
        raise DomainError("FORBIDDEN_SCOPE", "复验准备须沿用本次讨论的项目范围。", 403)
    _product, build, _project, selected, _reads = _target(
        session, ctx, parent, requested.selection,
    )
    proof = capture(
        session, ctx, parent, requested.citation_ids,
        product_id=parent.product_id, build_id=selected.id, include_taint=True,
    )
    from .action_taint import inherit

    inherit(parent, proof["taint"])
    sources = {ref.artifact_id: ref for ref in effective.sources}
    for value in proof["read_set"]:
        reference = SourceRead.model_validate({
            "artifact_id": value["artifact_id"],
            "expected_revision": value["expected_revision"],
        })
        old = sources.get(reference.artifact_id)
        if old is not None and old.expected_revision != reference.expected_revision:
            raise DomainError("VERSION_CONFLICT", "所选Build需要的资料版本与原会话不一致。")
        sources[reference.artifact_id] = reference
    catalog = SkillCatalog()
    skill = catalog.configuration(SKILL)
    if skill is None:
        raise DomainError("SOURCE_UNAVAILABLE", "复验准备技能尚未配置。")
    fixed = RequestedSkill(key=skill.key, version=skill.version, digest=skill.digest)
    skills = tuple(effective.requested_skills)
    if not any(item.key == SKILL for item in skills):
        skills += (fixed,)
    validate(session, ctx, skills, catalog=catalog)
    action = {
        "version": 1,
        "kind": requested.kind,
        "request_id": str(uuid5(NAMESPACE_URL, (
            f"pdos:verification-request:{ctx.tenant_id}:{parent.id}:{effective.idempotency_key}"
        ))),
        "selection": selected.model_dump(mode="json"),
        "build_name": build.name,
        "citation_ids": sorted({str(value) for value in requested.citation_ids}),
        "source_run_id": str(parent.id),
        "source_proof": proof,
    }
    return effective.model_copy(update={"sources": list(sources.values())}), action, skills


def check_action(session, ctx, run, action):
    """Recheck the fixed parent discussion, target and current source authority."""
    if (run is None or not isinstance(action, dict) or action.get("version") != 1
        or action.get("kind") != "prepare_verification"):
        raise DomainError("VERSION_CONFLICT", "复验准备入口资料已变化，请重新选择。")
    parent = session.get(AgentRun, UUID(action["source_run_id"]))
    if (parent is None or parent.id != run.continued_from_id
        or parent.tenant_id != run.tenant_id or parent.session_id != run.session_id
        or parent.requester_id != ctx.requester_id or parent.product_id != run.product_id
        or parent.project_id != run.project_id or parent.category_id != ctx.category_id):
        raise DomainError("FORBIDDEN_SCOPE", "复验准备不在原讨论的本人范围。", 403)
    _target(session, ctx, parent, action["selection"])
    proof = recheck(session, ctx, parent, action["source_proof"])
    if sorted(action["citation_ids"]) != sorted(
        source["citation_id"] for source in proof["discussion_sources"]
    ):
        raise DomainError("SOURCE_STALE", "所选讨论依据已变化，请重新准备。")
    return proof


def context_value(action):
    selected = BuildRef.model_validate(action["selection"])
    return {
        "kind": "prepare_verification",
        "target": selected.model_dump(mode="json"),
        "request_id": str(UUID(action["request_id"])),
        "build_name": action["build_name"],
        "citation_ids": list(action["citation_ids"]),
        "draft_rules": [
            "使用本次固定request_id和Build版本，仅新建准备，expected_request_revision为0。",
            "按本次讨论起草复验目标，保留所选历史来源。",
            "执行资料先用assistant.materials.read实际读取，再给出固定原文行引用。",
            "方法和验收依据无明确来源时保留待确认；真正缺少的数量等内容向本人询问。",
            "仅准备verification.preparation.record候选，由本人预览确认。",
        ],
    }


def _inline(schema, definitions):
    if isinstance(schema, list):
        return [_inline(value, definitions) for value in schema]
    if not isinstance(schema, dict):
        return schema
    if "$ref" in schema:
        return _inline(definitions[schema["$ref"].split("/")[-1]], definitions)
    return {key: _inline(value, definitions) for key, value in schema.items() if key != "$defs"}


_BUILD_SCHEMA = BuildRef.model_json_schema()
CONTEXT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "kind": {"const": "prepare_verification"},
        "target": _inline(deepcopy(_BUILD_SCHEMA), _BUILD_SCHEMA.get("$defs", {})),
        "build_name": {"type": "string"},
        "request_id": {"type": "string", "format": "uuid"},
        "citation_ids": {"type": "array", "items": {"type": "string", "format": "uuid"}},
        "draft_rules": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["kind", "target", "request_id", "build_name", "citation_ids", "draft_rules"],
}
