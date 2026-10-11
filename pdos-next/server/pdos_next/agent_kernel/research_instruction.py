"""A versioned read-only skill section, fixed before the first child model call."""

from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import func, select

from pdos_next.errors import DomainError
from pdos_next.service import digest

from . import policy
from .bindings import SkillBinding
from .execution import validate_skill_load
from .models import AgentEvent


@dataclass(frozen=True)
class ResearchInstructionBinding:
    skill: SkillBinding
    instruction: str
    instruction_digest: str

    def context(self):
        return {
            "key": self.skill.key,
            "version": self.skill.version,
            "skill_digest": self.skill.digest,
            "instruction_digest": self.instruction_digest,
            "instruction": self.instruction,
        }


class ResearchInstruction:
    def __init__(self, store, catalog):
        self.store, self.catalog = store, catalog

    def __call__(self, scope):
        if scope.isolation != "research":
            raise DomainError("FORBIDDEN_SCOPE", "研究说明只能用于隔离研究子图。")
        with self.store.transaction(scope, lock=True) as (session, run):
            self.store.authority(session, scope)
            skill = self.catalog.load(
                "public_research", scope,
                lambda bound, actual: policy.skill_enabled(session, bound, actual),
            )
            marker = "### 子任务说明\n"
            if skill.content.count(marker) != 1:
                raise DomainError("SOURCE_UNAVAILABLE", "公开研究缺少唯一的版本化子任务说明。")
            instruction = skill.content.split(marker, 1)[1].split("\n##", 1)[0].strip()
            if not instruction:
                raise DomainError("SOURCE_UNAVAILABLE", "公开研究子任务说明为空。")
            identity = {
                "key": skill.key,
                "version": skill.version,
                "skill_digest": skill.digest,
                "instruction_digest": digest(instruction),
            }
            previous = run.versions.get("research_instruction")
            if previous is None:
                event_id = uuid4()
                sequence = session.scalar(
                    select(func.coalesce(func.max(AgentEvent.sequence), 0)).where(
                        AgentEvent.run_id == run.id
                    )
                ) + 1
                session.add(AgentEvent(
                    id=event_id, tenant_id=scope.tenant_id, run_id=run.id, sequence=sequence,
                    body={
                        "type": "skill_loaded", "key": skill.key, "version": skill.version,
                        "digest": skill.digest, "isolation": "research",
                    },
                ))
                run.versions = {
                    **run.versions,
                    "research_instruction": {**identity, "load_event_id": str(event_id)},
                }
                session.flush()
            else:
                if not isinstance(previous, dict) or (
                    set(previous) != {*identity, "load_event_id"}
                    or {key: previous[key] for key in identity} != identity
                ):
                    raise DomainError("VERSION_CONFLICT", "原研究子任务的技能说明已变化。")
                try:
                    event_id = UUID(previous["load_event_id"])
                except (ValueError, TypeError, AttributeError):
                    raise DomainError("VERSION_CONFLICT", "原研究说明缺少实际加载身份。") from None
            binding = SkillBinding(
                key=skill.key, version=skill.version, digest=skill.digest,
                load_event_id=event_id,
            )
            validate_skill_load(session, scope, binding)
            return ResearchInstructionBinding(binding, instruction, identity["instruction_digest"])
