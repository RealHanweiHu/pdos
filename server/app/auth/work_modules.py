"""Administrator-assigned workspace modules; action authority stays with Role."""

from enum import StrEnum


class WorkModule(StrEnum):
    PRODUCT = "product"
    PROJECT = "project"
    ENGINEERING = "engineering"
    QUALITY = "quality"
    INTRODUCTION = "introduction"
    SUPPLY = "supply"
    PORTFOLIO = "portfolio"


def normalize_work_modules(values: object) -> tuple[WorkModule, ...]:
    if not isinstance(values, (list, tuple)):
        raise ValueError("work_modules must be a list")
    selected = {WorkModule(value) for value in values}
    return tuple(module for module in WorkModule if module in selected)
