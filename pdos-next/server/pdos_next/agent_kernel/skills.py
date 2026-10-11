"""Versioned code configuration; loading appends content, never rewrites the prefix."""

from dataclasses import dataclass
from pathlib import Path

import yaml

from pdos_next.errors import DomainError


@dataclass(frozen=True)
class Skill:
    key: str
    version: str
    purpose: str
    operations: frozenset[str]
    metadata: dict
    content: str

    @property
    def digest(self):
        from pdos_next.service import digest

        return digest({
            "key": self.key, "version": self.version, "purpose": self.purpose,
            "operations": sorted(self.operations), "metadata": self.metadata,
            "content": self.content,
        })


class SkillCatalog:
    def __init__(self, directory=None):
        directory = directory or Path(__file__).resolve().parents[1] / "skill_packages"
        self._skills = {}
        for path in sorted(Path(directory).glob("*.md")):
            text = path.read_text()
            if not text.startswith("---\n"):
                continue
            header, content = text[4:].split("\n---", 1)
            data = yaml.safe_load(header)
            required = {
                "key",
                "version",
                "purpose",
                "input_schema",
                "output_schema",
                "context_requirements",
                "allowed_operations",
                "evidence_policy",
                "failure_policy",
                "budget",
                "model_capability_requirements",
                "evaluation_suite",
                "owner",
            }
            if not required <= data.keys() or data["key"] in self._skills:
                raise ValueError("Invalid versioned skill configuration")
            operations = frozenset(o["tool"] for o in data["allowed_operations"])
            self._skills[data["key"]] = Skill(
                data["key"], data["version"], data["purpose"], operations, data, content.strip()
            )

    @property
    def index(self):
        return [{"key": s.key, "purpose": s.purpose} for _, s in sorted(self._skills.items())]

    def load(self, name, scope, permitted):
        skill = self._skills.get(name)
        if skill is None or not permitted(scope, skill):
            raise DomainError("FORBIDDEN_SCOPE", "该技能未在当前租户与范围启用。")
        return skill

    def validate_registry(self, registry):
        for skill in self._skills.values():
            for name in skill.operations:
                registry.get(name)
