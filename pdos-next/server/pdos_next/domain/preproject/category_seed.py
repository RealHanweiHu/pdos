"""Pure seed-to-preview conversion; callers own authorization and persistence.

No IDs, runs, snapshots, approvals or qualifications are created here. Stable keys
are category-local; the command layer must resolve them to scoped database IDs.
The original document and source catalogue remain attached as imported material,
including AI draft status and uncertainty that the command projection cannot hold.
"""

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class SeedParameter:
    key: str
    seed_parameter_id: str
    version: int
    name: str
    value_type: str
    enum_values: list[str] | None
    unit: str | None
    direction: str
    standard_condition: str | None
    method: str | None
    acceptance_criterion: str | None
    source_origin: str
    source_status: str
    source_ids: tuple[str, ...]
    raw: dict[str, Any]


@dataclass(frozen=True)
class SeedCategory:
    key: str
    name: str
    parameters: tuple[SeedParameter, ...]
    # Preserve knowledge/test/market coverage as material, not certified facts.
    raw: dict[str, Any]


@dataclass(frozen=True)
class SeedPreview:
    categories: tuple[SeedCategory, ...]
    raw_document: dict[str, Any]
    sources_markdown: str
    origin: Literal["imported"] = "imported"


def convert_seed(document: dict[str, Any], sources_markdown: str) -> SeedPreview:
    """Project pdos.category-seed v1 without mutating or claiming its authority.

    Missing optional dictionary fields remain None. Existing strings (including
    unknown/awaiting-review statements), status fields and source catalogue text
    are kept verbatim. This output is preview material, not a command payload.
    """
    if document.get("schema") != "pdos.category-seed" or document.get("schema_version") != 1:
        raise ValueError("Expected pdos.category-seed schema version 1")
    if not sources_markdown.strip():
        raise ValueError("The original source catalogue is required")
    raw_document = deepcopy(document)
    categories = []
    category_keys: set[str] = set()
    for category in raw_document["categories"]:
        key = category["category_id"]
        if key in category_keys:
            raise ValueError("Duplicate category key")
        category_keys.add(key)
        parameters = []
        parameter_keys: set[str] = set()
        for parameter in category["parameters"]:
            parameter_key = parameter["key"]
            if parameter_key in parameter_keys:
                raise ValueError("Duplicate parameter key within category")
            parameter_keys.add(parameter_key)
            parameters.append(
                SeedParameter(
                    key=parameter_key,
                    seed_parameter_id=parameter["parameter_id"],
                    version=parameter["version"],
                    name=parameter["label"],
                    value_type=parameter["value_type"],
                    enum_values=deepcopy(parameter.get("enum_values")),
                    unit=parameter.get("unit"),
                    direction=parameter["direction"],
                    standard_condition=parameter.get("conditions"),
                    method=parameter.get("verification_method"),
                    acceptance_criterion=parameter.get("acceptance_criterion"),
                    source_origin=parameter["origin"],
                    source_status=parameter["status"],
                    source_ids=tuple(parameter.get("source_ids", ())),
                    raw=deepcopy(parameter),
                )
            )
        categories.append(
            SeedCategory(key, category["name_zh"], tuple(parameters), deepcopy(category))
        )
    return SeedPreview(tuple(categories), raw_document, sources_markdown)
