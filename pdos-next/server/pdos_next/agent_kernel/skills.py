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

    @property
    def row_schemas(self):
        """Extraction row contracts this skill declares; declaration alone grants no scope."""
        from .extract_schemas import RowSchemaDeclaration

        declared = self.metadata.get("row_schemas") or ()
        if not isinstance(declared, (list, tuple)):
            raise ValueError("Skill row_schemas must be a list of kind/version declarations")
        return tuple(
            RowSchemaDeclaration.model_validate(item) for item in declared
        )


class SkillCatalog:
    def __init__(self, directory=None):
        directory = directory or Path(__file__).resolve().parents[1] / "skill_packages"
        from .context_projection import declared_contract, load_contracts

        self.contexts = load_contracts(Path(directory))
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
                "context_schema",
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
            data["context_schema"] = declared_contract(data["context_schema"], self.contexts)
            operations = frozenset(o["tool"] for o in data["allowed_operations"])
            self._skills[data["key"]] = Skill(
                data["key"], data["version"], data["purpose"], operations, data, content.strip()
            )
        from .extract_schemas import draft_registry

        rows = draft_registry()
        for skill in self._skills.values():
            for declaration in skill.row_schemas:
                try:
                    rows.rows_model(declaration)
                except ValueError:
                    raise ValueError(
                        f"Skill {skill.key} declares an unregistered extraction row contract"
                    ) from None

    @property
    def index(self):
        return [{"key": s.key, "purpose": s.purpose} for _, s in sorted(self._skills.items())]

    def configuration(self, key):
        """Inspect registered configuration; this does not enable or load a capability."""
        return self._skills.get(key)

    def load(self, name, scope, permitted):
        skill = self._skills.get(name)
        if skill is None or not permitted(scope, skill):
            raise DomainError("FORBIDDEN_SCOPE", "该技能未在当前租户与范围启用。")
        return skill

    def validate_registry(self, registry):
        for skill in self._skills.values():
            for name in skill.operations:
                registry.get(name)
