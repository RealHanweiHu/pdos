"""Deterministic NPI rules. A plan proposes work; the framework defines required outcomes."""

from graphlib import CycleError, TopologicalSorter
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, StrictBool, model_validator

from pdos_next.core.schema_base import StrictModel

Key = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")]
ProjectType = Literal["new_product", "derivative"]
Risk = Literal[
    "has_battery",
    "needs_new_mold",
    "needs_new_certification",
    "first_use_key_component",
    "has_lithium_battery",
    "has_pressurized_chamber",
    "has_firmware_or_app",
]
PATH_FIELDS = (
    "has_battery",
    "needs_new_mold",
    "needs_new_certification",
    "first_use_key_component",
)
RISK_FIELDS = (
    *PATH_FIELDS,
    "has_lithium_battery",
    "has_pressurized_chamber",
    "has_firmware_or_app",
)
PERMANENT = {"eol_test_capability": "pvt", "first_production_release": "mp"}


class Stage(StrictModel):
    key: Key
    name: str = Field(min_length=1, max_length=100)
    node: str = Field(min_length=1, max_length=100)


class Outcome(StrictModel):
    key: Key
    stage: Key
    name: str = Field(min_length=1, max_length=200)
    role: Key
    when_any: tuple[Risk, ...] = ()
    redline: StrictBool = False

    @property
    def waivable(self):
        return bool(self.when_any) and not self.redline


class Metric(StrictModel):
    key: Key
    stage: Key
    name: str = Field(min_length=1, max_length=100)
    minimum_percent: int = Field(ge=0, le=100, strict=True)


class Framework(StrictModel):
    stages: tuple[Stage, ...] = Field(min_length=1, max_length=16)
    outcomes: tuple[Outcome, ...] = Field(min_length=1, max_length=200)
    metrics: tuple[Metric, ...] = Field(default=(), max_length=30)

    @model_validator(mode="after")
    def consistent(self) -> Self:
        stages = [stage.key for stage in self.stages]
        if len(stages) != len(set(stages)) or stages[0] != "planning" or "pvt" not in stages:
            raise ValueError("框架须以规划开始，保留独立 PVT 评审，阶段键不能重复")
        if "prototype_validation" in stages or ("evt" in stages) != ("dvt" in stages):
            raise ValueError("完整路径的 EVT 与 DVT 须成对，轻量路径的样机验证由系统生成")
        if "evt" in stages and stages.index("dvt") != stages.index("evt") + 1:
            raise ValueError("EVT 与 DVT 须相邻且依次排列")
        for items in (self.outcomes, self.metrics):
            keys = [item.key for item in items]
            if len(keys) != len(set(keys)) or any(item.stage not in stages for item in items):
                raise ValueError("成果和指标各自须有唯一键，并引用框架内的阶段")
        by_key = {outcome.key: outcome for outcome in self.outcomes}
        for key, stage in PERMANENT.items():
            entry = by_key.get(key)
            if entry is None or entry.stage != stage or not entry.redline or entry.when_any:
                raise ValueError(f"永久红线须保留且无条件适用：{key}")
        freeze = by_key.get("specification_freeze")
        if freeze is None or freeze.stage != "planning" or freeze.when_any:
            raise ValueError("规划阶段须包含规格冻结")
        return self


class Source(StrictModel):
    kind: Literal[
        "framework_outcome",
        "definition",
        "category_knowledge",
        "parameter",
        "test_template",
        "g0_open_item",
        "artifact",
    ]
    id: UUID
    revision: int = Field(ge=1, strict=True)
    key: Key | None = None

    @property
    def ref(self):
        return self.kind, str(self.id), self.revision, self.key


class TaskBasis(StrictModel):
    role: Key
    deliverable: str = Field(min_length=1, max_length=500)
    outcome_keys: tuple[Key, ...] = Field(default=(), max_length=40)
    sources: tuple[Source, ...] = Field(min_length=1, max_length=30)


class PlanBasis(StrictModel):
    framework_id: UUID
    framework_revision: int = Field(ge=1, strict=True)
    tasks: dict[str, TaskBasis] = Field(min_length=1, max_length=500)
    milestones: dict[Key, str] = Field(max_length=16)


def attributes(definition):
    """Only canonical, known definition fields count. Contradictory data stays unknown."""
    found = {}
    for spec in definition["specs"]:
        key = spec["key"]
        if key not in RISK_FIELDS or spec["availability"] != "known":
            continue
        value = spec.get("text")
        if value in ("是", "yes", "true"):
            found[key] = True
        elif value in ("否", "no", "false"):
            found[key] = False
    return found


def path_for(facts, *, force_full=False):
    return (
        "light"
        if not force_full and all(facts.get(key) is False for key in PATH_FIELDS)
        else "full"
    )


def applicable(framework, facts, path):
    def stage_key(key):
        return "prototype_validation" if path == "light" and key in {"evt", "dvt"} else key

    stages = [
        (
            Stage(key="prototype_validation", name="样机验证", node="样机验证评审")
            if stage.key == "evt" and path == "light"
            else stage
        )
        for stage in framework.stages
        if stage.key != "dvt" or path != "light"
    ]
    outcomes = [
        outcome.model_copy(update={"stage": stage_key(outcome.stage)})
        for outcome in framework.outcomes
        if not outcome.when_any or any(facts.get(key) is not False for key in outcome.when_any)
    ]
    metrics = [
        metric.model_copy(update={"stage": stage_key(metric.stage)}) for metric in framework.metrics
    ]
    return stages, outcomes, metrics


def metric_result(metric, value):
    if value is None:
        return "unknown"
    return "met" if value >= metric.minimum_percent else "unmet"


def check(*, stages, outcomes, tasks, basis, sources, role_keys, estimates=None):
    """Return stable, addressable errors. estimates maps authorized references to minute bounds."""
    issues = []

    def issue(code, key):
        issues.append({"code": code, "key": key})

    estimates = estimates or {}
    stage_keys = {stage.key for stage in stages}
    outcome_keys = {outcome.key for outcome in outcomes}
    keys = {task.key for task in tasks}
    if len(keys) != len(tasks):
        issue("DUPLICATE_TASK", None)
    for key in sorted(keys ^ basis.tasks.keys()):
        issue("TASK_BASIS_MISMATCH", key)
    graph = {}
    covered = set()
    for task in sorted(tasks, key=lambda entry: entry.key):
        graph[task.key] = set(task.depends_on)
        if any(key not in keys for key in task.depends_on):
            issue("MISSING_DEPENDENCY", task.key)
        entry = basis.tasks.get(task.key)
        if not entry:
            continue
        if task.key in stage_keys or task.duration_min_minutes == task.duration_max_minutes == 0:
            issue("STAGE_NODE_AS_TASK", task.key)
        if entry.role not in role_keys:
            issue("ROLE_UNAVAILABLE", task.key)
        refs = {source.ref for source in entry.sources}
        if not refs <= sources:
            issue("SOURCE_OUTSIDE_BASIS", task.key)
        if (
            len(set(entry.outcome_keys)) != len(entry.outcome_keys)
            or not set(entry.outcome_keys) <= outcome_keys
        ):
            issue("OUTCOME_UNAVAILABLE", task.key)
        bounds = (task.duration_min_minutes, task.duration_max_minutes)
        if bounds != (None, None) and not any(
            estimates.get((source.ref, task.key)) == bounds
            and task.estimate_source == str(source.id)
            for source in entry.sources
        ):
            issue("DURATION_UNSUPPORTED", task.key)
        covered.update(entry.outcome_keys)
    try:
        ordered = list(TopologicalSorter(graph).static_order())
    except CycleError as error:
        issue("DEPENDENCY_CYCLE", " → ".join(error.args[1]))
        ordered = []
    for outcome in sorted(outcomes, key=lambda entry: entry.key):
        if outcome.key not in covered:
            issue("REDLINE_UNCOVERED" if outcome.redline else "OUTCOME_UNCOVERED", outcome.key)

    # A milestone points at actual work whose predecessor chain covers its exit.
    outputs = {}
    for key in ordered:
        entry = basis.tasks.get(key)
        outputs[key] = set(entry.outcome_keys if entry else ()).union(
            *(outputs[dependency] for dependency in graph.get(key, ()))
        )
    for key in sorted(stage_keys | basis.milestones.keys()):
        target = basis.milestones.get(key)
        if key not in stage_keys or target not in keys:
            issue("MILESTONE_BINDING_INVALID", key)
        elif ordered and any(
            outcome.stage == key and outcome.key not in outputs[target] for outcome in outcomes
        ):
            issue("MILESTONE_EXIT_NOT_COVERED", key)
    bound = set(basis.milestones.values())
    reachable = set()
    for key in reversed(ordered):
        if key in bound or key in reachable:
            reachable.update(graph.get(key, ()))
            reachable.add(key)
    if ordered:
        for key in sorted(keys - reachable):
            issue("TASK_HAS_NO_STAGE_EXIT", key)
    return issues
