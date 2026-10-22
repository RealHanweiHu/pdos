"""Native Pilot facts through the actual common T1 transaction.

The creation atom and original observations remain immutable. Only Current
advances. Original-value/statistical owners read real lot/sample/source facts;
neither this service nor a recorded yield grants production qualification.
"""

import re
import sys
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
from types import MappingProxyType
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import select

from pdos_next.clock import proof_deadline_current
from pdos_next.contracts import Command, SourceRead
from pdos_next.domain.capa_effectiveness.fact_atom_storage import _same_uow, _uow
from pdos_next.domain.change_execution import service as evidence
from pdos_next.domain.configurations import service as configurations
from pdos_next.domain.manufacturing_baseline import service as preparation
from pdos_next.domain.manufacturing_baseline.consumption import ConsumptionHost
from pdos_next.domain.manufacturing_baseline.publication_service import SavedCommand
from pdos_next.domain.manufacturing_baseline.rules import require
from pdos_next.domain.professional_authority.signature_watermarks import signature_current
from pdos_next.domain.projects.models import Project
from pdos_next.errors import DomainError
from pdos_next.models import (
    Confirmation,
    Product,
    now,
)
from pdos_next.request_proof import snapshot_get, snapshot_rows, snapshot_scalar
from pdos_next.schemas.manufacturing_trials.contracts import Gap
from pdos_next.schemas.manufacturing_trials.pilot_results import FixedPilotScope, RecordedBatch
from pdos_next.schemas.verification.contracts import SourceRef
from pdos_next.service import Context, digest, material_digest, require_access

from . import pilot_result_rules
from .native_models import NativePilotCurrent as Current
from .native_models import NativePilotObservation as Observation
from .native_models import NativePilotRun as Pilot
from .native_schemas import (
    CREATE_EVENT,
    CREATE_OPERATION,
    CREATE_SUBJECT_TYPE,
    RESULT_EVENT,
    RESULT_OPERATION,
    RESULT_SUBJECT_TYPE,
    SCHEMA_VERSION,
    PilotCreatePayload,
    PilotResultPayload,
    json_snapshot,
    semantic,
)

PAYLOADS = MappingProxyType(
    {CREATE_OPERATION: PilotCreatePayload, RESULT_OPERATION: PilotResultPayload}
)
EVENTS = MappingProxyType({CREATE_OPERATION: CREATE_EVENT, RESULT_OPERATION: RESULT_EVENT})
category_lifecycle_fence = True
confirmation_watermarks = True
_CAPABILITY = object()


@dataclass(frozen=True)
class Runtime:
    material: object
    statistics: object
    consumption: ConsumptionHost
    module: object


def configure(engine):
    from .native_material_owner import ActualPilotMaterialOwner
    from .native_statistics_owner import ActualPilotStatisticsOwner

    module = sys.modules[__name__]
    material = ActualPilotMaterialOwner(engine)
    value = Runtime(
        material,
        ActualPilotStatisticsOwner(engine, material_owner=material),
        ConsumptionHost({operation: module for operation in PAYLOADS}),
        module,
    )
    engine._pdos_native_pilot = value
    return value


def _runtime(s):
    value = getattr(s.get_bind(), "_pdos_native_pilot", None)
    require(
        type(value) is Runtime and value.module is sys.modules[__name__],
        "INTEGRATION_REQUIRED",
        "实际Pilot原件、统计与共同消费端口尚未接通。",
        503,
    )
    return value


def _stamp(s):
    value = _runtime(s)
    return (
        id(value),
        *(
            id(getattr(method, "__func__", method))
            for method in (
                value.material.read,
                value.material.refresh,
                value.material.current,
                value.statistics.read,
                value.statistics.refresh,
                value.statistics.current,
                preparation._authority,
                signature_current,
                _compose,
                _confirmed_bound,
                _retained,
            )
        ),
    )


def _intent(ctx, command, payload):
    return digest(
        {
            "operation": command.operation,
            "category": command.category_id,
            "product": command.product_id,
            "payload": semantic(payload),
            "named_actor": ctx.requester_id,
            "source_revision": None,
            "private_owner": ctx.requester_id
            if getattr(payload, "visibility", "private") == "private"
            else None,
        }
    )


def _command(s, ctx, command, product, payload):
    require(
        isinstance(ctx, Context)
        and ctx.actor_id == ctx.requester_id
        and ctx.run_id is None
        and ctx.agent_run_id is None,
        "NAMED_DECISION_REQUIRED",
        "本轮Pilot须由当前有权本人确认。",
        403,
    )
    require(
        isinstance(command, Command)
        and command.operation in PAYLOADS
        and type(payload) is PAYLOADS[command.operation]
        and PAYLOADS[command.operation].model_validate(command.payload) == payload
        and command.category_id == ctx.category_id,
        "COMMAND_PAYLOAD_MISMATCH",
        "Pilot操作、范围或完整输入不能替换。",
        422,
    )
    preparation._persistent_product(s, ctx, command, product)
    require(product.category_id == ctx.category_id, "FORBIDDEN_SCOPE", "请选择实际品类型号。", 403)


def _project_row(s, ctx, pid, identity):
    project = snapshot_get(s, Project, identity, scope_id=pid)
    require(
        project is not None
        and (project.tenant_id, project.product_id) == (ctx.tenant_id, pid)
        and (project.visibility != "private" or project.owner_id == ctx.requester_id),
        "FORBIDDEN_SCOPE",
        "请选择当前可读的实际项目。",
        403,
    )
    return project


def _scope(model, ctx, pid):
    return (
        model.tenant_id == ctx.tenant_id,
        model.category_id == ctx.category_id,
        model.product_id == pid,
    )


def _root(s, ctx, pid, identity):
    row = snapshot_get(s, Pilot, identity, scope_id=pid)
    require(
        row is not None
        and (row.tenant_id, row.category_id, row.product_id)
        == (ctx.tenant_id, ctx.category_id, pid)
        and (row.visibility != "private" or row.owner_id == ctx.requester_id),
        "FORBIDDEN_SCOPE",
        "所选Pilot不在当前可读范围。",
        403,
    )
    return row


def _pointer(s, ctx, pid, root, *, lock=False):
    query = select(Current).where(*_scope(Current, ctx, pid), Current.pilot_id == root.id)
    value = snapshot_scalar(s, (Current, root.id), query, lock=lock, scope_id=pid)
    require(
        value is not None
        and (value.project_id, value.owner_id, value.visibility)
        == (root.project_id, root.owner_id, root.visibility),
        "STORED_ATOM_MISMATCH",
        "Pilot Current范围或属主不能核对。",
        503,
    )
    return value


def _pointer_value(pointer):
    return {
        "revision": pointer.revision,
        "epoch": pointer.epoch,
        "latest_observation_id": str(pointer.latest_observation_id)
        if pointer.latest_observation_id is not None
        else None,
    }


def _body(row):
    common = {
        "material": deepcopy(row.material_snapshot),
        "gaps": deepcopy(row.gaps),
        "qualification": "unknown",
        "start_authorized": False,
        "manufacturing_release": None,
        "external_delivery": False,
    }
    if type(row) is Pilot:
        return {
            **common,
            "details": deepcopy(row.details),
            "statistics_basis": deepcopy(row.statistics_basis),
        }
    return {
        **common,
        "record": deepcopy(row.record),
        "fixed_scope": deepcopy(row.fixed_scope),
        "projection": deepcopy(row.projection),
        "pilot_id": str(row.pilot_id),
        "pilot_revision_before": row.pilot_revision_before,
        "previous_observation_id": str(row.previous_observation_id)
        if row.previous_observation_id
        else None,
    }


def _retained(s, ctx, pid, row):
    """Read the immutable, storage-guarded original input and direct binding."""
    try:
        raw = row.input_snapshot
        command = SavedCommand.model_validate(raw["command"])
        payload = PAYLOADS[row.operation].model_validate(raw["semantic"])
        body = _body(row)
        require(
            set(raw) == {"command", "semantic", "original_key_sha256", "review", "previous_current"}
            and re.fullmatch(r"[a-f0-9]{64}", raw["original_key_sha256"]) is not None
            and command.command_id == row.command_id
            and command.operation == row.operation
            and command.category_id == row.category_id
            and command.product_id == pid
            and command.expected_revision == row.shared_proof_revision
            and command.payload == semantic(payload) == raw["semantic"]
            and digest(semantic(payload)) == row.payload_sha256
            and payload.confirmation_token is None
            and row.write_tier == "T1"
            and row.writer_id == row.actor_id == row.requester_id
            and row.status == "recorded"
            and raw["review"]["after"] == body
            and raw["review"]["authority"] == row.authority_snapshot
            and raw["review"]["read_basis"] == row.source_basis
            and raw["review"]["required_source_read_set"] == row.required_source_read_set
            and row.required_source_read_set
            == [v.model_dump(mode="json") for v in command.source_read_set],
            "STORED_ATOM_MISMATCH",
            "Pilot固定列、输入或实质预览不一致。",
            503,
        )
        if type(row) is Pilot:
            require(
                payload.details.pilot_id == row.id
                and payload.project_id == row.project_id
                and payload.details.model_dump(mode="json") == row.details
                and (payload.statistics.model_dump(mode="json") if payload.statistics else None)
                == row.statistics_basis
                and payload.visibility == row.visibility,
                "STORED_ATOM_MISMATCH",
                "Pilot固定创建材料不能核对。",
                503,
            )
        else:
            require(
                payload.pilot_id == row.pilot_id
                and payload.expected_pilot_revision == row.pilot_revision_before
                and row.revision == row.pilot_revision_before + 1
                and payload.record.observation_id == row.id
                and payload.record.model_dump(mode="json") == row.record
                and payload.record.previous_observation_id == row.previous_observation_id,
                "STORED_ATOM_MISMATCH",
                "Pilot原始观察及修订链不能核对。",
                503,
            )
            if row.fixed_scope is not None:
                batch = RecordedBatch(
                    fixed=FixedPilotScope.model_validate(row.fixed_scope), record=payload.record
                )
                expected_projection = (
                    json_snapshot(pilot_result_rules.project(batch, checked_at=row.created_at))
                    if row.projection is not None
                    else None
                )
                require(
                    batch.fixed.pilot_id == row.pilot_id
                    and expected_projection == row.projection
                    and (
                        expected_projection is not None
                        or any(
                            item["code"]
                            in {
                                "PILOT_STATISTICS_WINDOW_NOT_FINISHED",
                                "PILOT_FIXED_SCOPE_RETAINED_CURRENT_RESOURCE_UNKNOWN",
                            }
                            for item in row.gaps
                        )
                    ),
                    "STORED_ATOM_MISMATCH",
                    "原始分母及统计不能核对。",
                    503,
                )
            else:
                require(
                    row.projection is None,
                    "STORED_ATOM_MISMATCH",
                    "未知口径不能保存正向统计。",
                    503,
                )
    except (KeyError, TypeError, ValueError, ValidationError) as error:
        raise DomainError("STORED_ATOM_MISMATCH", "Pilot固定输入不完整。", 503) from error
    # The immutable atom and reciprocal common members were established by
    # deferred storage guards in their original transaction. A read keeps those
    # signed facts; it does not requalify their author or replay their proof.
    return payload


def _chain(s, ctx, pid, root, pointer):
    rows = snapshot_rows(
        s,
        (Observation, root.id),
        select(Observation)
        .where(*_scope(Observation, ctx, pid), Observation.pilot_id == root.id)
        .order_by(Observation.revision),
        scope_id=pid,
    )
    previous = None
    for index, row in enumerate(rows, start=2):
        _retained(s, ctx, pid, row)
        require(
            row.revision == index
            and (row.project_id, row.owner_id, row.visibility)
            == (root.project_id, root.owner_id, root.visibility)
            and row.previous_observation_id == (previous.id if previous else None),
            "STORED_ATOM_MISMATCH",
            "Pilot原始观察链缺失或跨范围。",
            503,
        )
        if previous is not None and previous.fixed_scope is not None:
            require(
                row.fixed_scope is not None, "STORED_ATOM_MISMATCH", "修订不能移除固定口径。", 503
            )
            _correction(
                RecordedBatch(fixed=previous.fixed_scope, record=previous.record),
                RecordedBatch(fixed=row.fixed_scope, record=row.record),
                checked_at=row.created_at,
                project_allowed=row.projection is not None,
            )
        previous = row
    require(
        pointer.revision == len(rows) + 1
        and pointer.epoch == pointer.revision
        and pointer.latest_observation_id == (previous.id if previous else None),
        "STORED_ATOM_MISMATCH",
        "Pilot Current与完整观察链不一致。",
        503,
    )
    return rows


def _correction(previous, current, *, checked_at, project_allowed=True):
    if project_allowed and current.fixed.yield_scope.window_end <= checked_at:
        return pilot_result_rules.revision(previous, current, checked_at=checked_at)
    old, new = previous.fixed.model_dump(), current.fixed.model_dump()
    old.pop("pilot_revision")
    new.pop("pilot_revision")
    require(
        old == new and current.fixed.pilot_revision == previous.fixed.pilot_revision + 1,
        "FIXED_SCOPE_CHANGED",
        "修订不能改变固定配置、成员、分母或统计条件。",
    )
    require(
        current.record.previous_observation_id == previous.record.observation_id
        and current.record.observation_id != previous.record.observation_id
        and bool(current.record.correction_reason),
        "OBSERVATION_REVISION_CONFLICT",
        "须固定前一观察和实际修正原因。",
    )
    old_counts = previous.record.counts or pilot_result_rules.counts_from_units(previous.record)
    new_counts = current.record.counts or pilot_result_rules.counts_from_units(current.record)
    require(
        old_counts.input_count == new_counts.input_count,
        "FIXED_DENOMINATOR_CHANGED",
        "修订不能改变原投入口径。",
    )
    require(
        current.record.observed.occurred_at >= previous.record.observed.occurred_at,
        "OBSERVATION_TIME_REVERSED",
        "修订发生钟不能倒退。",
    )
    return None


@dataclass(frozen=True)
class Bound:
    material_read: object
    statistics_read: object | None
    root: object | None
    pointer: dict | None
    previous: object | None
    create: PilotCreatePayload
    body: dict
    reads: list
    basis: dict
    sources: list
    gaps: list
    authority: dict
    deadline: object
    project: object
    runtime: tuple


def _scope_visibility(create, project, material_read, statistics_read):
    if create.visibility == "private":
        return
    material = material_read.material
    visible = [
        {"visibility": project.visibility},
        material.build,
        material.lot,
        material.actual_configuration,
        material.engineering_configuration,
        material.process,
        material.publication or {},
    ]
    for owner_read in (material_read, statistics_read):
        if owner_read is not None:
            visible.extend(
                row
                for mark in owner_read.source_basis.get("watermarks", ())
                for row in mark["rows"]
            )
    if statistics_read is not None:
        visible.extend(statistics_read.material.get("issues", ()))
    require(
        all(value.get("visibility") != "private" for value in visible),
        "FORBIDDEN_SCOPE",
        "私人项目、实物、配置或问题不能扩大为共享试产内容。",
        403,
    )


def _compose(s, ctx, command, product, payload, material_read, statistics_read, *, retained=None):
    _command(s, ctx, command, product, payload)
    stamp = _stamp(s)
    root, pointer, previous = None, None, None
    if type(payload) is PilotCreatePayload:
        create = payload
        exists = s.scalar(
            select(Pilot.id).where(
                *_scope(Pilot, ctx, product.id), Pilot.id == payload.details.pilot_id
            )
        )
        require(exists is None or retained is not None, "VERSION_CONFLICT", "Pilot身份已存在。")
    else:
        root = _root(s, ctx, product.id, payload.pilot_id)
        create = _retained(s, ctx, product.id, root)
        require(
            signature_current(s, ctx, product.id, root.project_id, root.authority_snapshot),
            "RECHECK_REQUIRED",
            "原Pilot签署依赖水位已变化，请先复核。",
        )
        actual_pointer = _pointer(s, ctx, product.id, root)
        pointer = retained.pointer if retained is not None else _pointer_value(actual_pointer)
        if retained is None:
            chain = _chain(s, ctx, product.id, root, actual_pointer)
            previous = chain[-1] if chain else None
        else:
            previous = retained.previous
        require(
            pointer["revision"] == payload.expected_pilot_revision
            and payload.record.previous_observation_id == (previous.id if previous else None),
            "VERSION_CONFLICT",
            "请从当前Pilot观察继续，原观察不能被覆盖。",
        )
    project = _project_row(s, ctx, product.id, create.project_id)
    material = material_read.material
    _scope_visibility(create, project, material_read, statistics_read)
    require(
        material.scope.tenant_id == ctx.tenant_id
        and material.scope.product_id == product.id
        and material.scope.project_id == project.id
        and material.category_id == product.category_id
        and material.product_revision == product.revision
        and project.purpose == create.details.purpose,
        "FORBIDDEN_SCOPE",
        "Pilot须对应实际项目、批次与当前型号范围。",
        403,
    )
    authority, deadline = preparation._authority(s, ctx, command, project, write=True)
    groups = [
        [v.model_dump(mode="json") for v in material_read.required_source_read_set],
        authority["required_source_read_set"],
    ]
    sources, gaps = list(material_read.sources), list(material.gaps)
    statistics_material, fixed, projection = None, None, None
    if statistics_read is not None:
        groups.append([v.model_dump(mode="json") for v in statistics_read.required_source_read_set])
        sources.extend(statistics_read.sources)
        gaps.extend(statistics_read.gaps)
        statistics_material = json_snapshot(statistics_read.material)
        fixed = json_snapshot(statistics_read.fixed) if statistics_read.fixed is not None else None
        projection = (
            json_snapshot(statistics_read.projection)
            if statistics_read.projection is not None
            else None
        )
        retained_fixed = (
            previous.fixed_scope
            if previous is not None
            else root.material_snapshot.get("fixed_scope")
            if root is not None
            else None
        )
        if fixed is None and retained_fixed is not None:
            fixed = (
                FixedPilotScope.model_validate(retained_fixed)
                .model_copy(update={"pilot_revision": payload.expected_pilot_revision})
                .model_dump(mode="json")
            )
            gaps.append(
                Gap(
                    code="PILOT_FIXED_SCOPE_RETAINED_CURRENT_RESOURCE_UNKNOWN",
                    state="unknown",
                    detail="保留已核原共同组的固定口径；本轮产线事实待核，原值保存且良率未知。",
                    owner_role="npi",
                )
            )
        if previous is not None and previous.fixed_scope is not None:
            require(
                fixed is not None,
                "FIXED_DENOMINATOR_CHANGED",
                "修订不能移除原固定口径。",
            )
            _correction(
                RecordedBatch(fixed=previous.fixed_scope, record=previous.record),
                RecordedBatch(fixed=fixed, record=payload.record),
                checked_at=statistics_read.checked_at,
                project_allowed=projection is not None,
            )
    reads = configurations._merge_reads(*groups)
    source_values = [v.model_dump(mode="json") for v in dict.fromkeys(sources)]
    artifacts, private, _ = evidence._evidence(
        s,
        ctx,
        product.id,
        reads,
        tuple(SourceRef.model_validate(v) for v in source_values),
        io=False,
    )
    require(
        not private or create.visibility == "private",
        "FORBIDDEN_SCOPE",
        "私人原件不能扩大为共享Pilot或观察。",
        403,
    )
    gaps = [v.model_dump(mode="json") for v in dict.fromkeys(gaps)]
    snapshot = {
        "pilot": material.model_dump(mode="json"),
        "statistics": statistics_material,
        "fixed_scope": fixed,
    }
    body = {
        "material": snapshot,
        "gaps": gaps,
        "qualification": "unknown",
        "start_authorized": False,
        "manufacturing_release": None,
        "external_delivery": False,
    }
    if type(payload) is PilotCreatePayload:
        body.update(
            details=create.details.model_dump(mode="json"),
            statistics_basis=create.statistics.model_dump(mode="json")
            if create.statistics
            else None,
        )
    else:
        body.update(
            record=payload.record.model_dump(mode="json"),
            fixed_scope=fixed,
            projection=projection,
            pilot_id=str(root.id),
            pilot_revision_before=payload.expected_pilot_revision,
            previous_observation_id=str(previous.id) if previous else None,
        )
    basis = json_snapshot(
        {
            "material_owner": material_read.source_basis,
            "statistics_owner": statistics_read.source_basis if statistics_read else None,
            "artifact_sources": [
                {"id": key, "status": "active", **deepcopy(artifacts[key])}
                for key in sorted(artifacts)
            ],
        }
    )
    preparation._deadline(authority, now(), deadline)
    require_access(s, ctx, product.id)
    require(stamp == _stamp(s), "SOURCE_STALE", "读取期间Pilot实际owner已变化。")
    return Bound(
        material_read,
        statistics_read,
        root,
        pointer,
        previous,
        create,
        body,
        reads,
        basis,
        source_values,
        gaps,
        authority,
        deadline,
        project,
        stamp,
    )


def _owner_arguments(s, ctx, pid, payload, retained=None):
    if type(payload) is PilotCreatePayload:
        return payload, None, 1, None
    root = _root(s, ctx, pid, payload.pilot_id)
    create = _retained(s, ctx, pid, root)
    pointer = _pointer(s, ctx, pid, root)
    previous = retained.previous if retained is not None else None
    if retained is None and pointer.latest_observation_id is not None:
        previous = s.scalar(
            select(Observation)
            .where(
                *_scope(Observation, ctx, pid),
                Observation.pilot_id == root.id,
                Observation.id == pointer.latest_observation_id,
            )
            .execution_options(populate_existing=True, autoflush=False)
        )
        require(previous is not None, "STORED_ATOM_MISMATCH", "缺实际前驱观察。", 503)
        _retained(s, ctx, pid, previous)
    previous_scope = previous.fixed_scope if previous else root.material_snapshot.get("fixed_scope")
    return (
        create,
        payload.record,
        payload.expected_pilot_revision,
        (FixedPilotScope.model_validate(previous_scope) if previous_scope is not None else None),
    )


def _load(s, ctx, command, product, payload, *, require_reads=True):
    _command(s, ctx, command, product, payload)
    captured, caller = _uow(s), digest(vars(ctx))
    with s.no_autoflush:
        create, record, revision, previous_scope = _owner_arguments(s, ctx, product.id, payload)
        material = _runtime(s).material.read(s, ctx, product.id, create.details)
        statistics = _runtime(s).statistics.read(
            s,
            ctx,
            product.id,
            create.details,
            create.statistics,
            record=record,
            pilot_revision=revision,
            previous_scope=previous_scope,
        )
        bound = _compose(s, ctx, command, product, payload, material, statistics)
        if require_reads:
            _reads(command, bound)
    _same_uow(s, captured, ctx, caller)
    return bound


def _reads(command, bound):
    require(
        configurations._merge_reads([v.model_dump(mode="json") for v in command.source_read_set])
        == bound.reads,
        "MISSING_REQUIRED_EVIDENCE",
        "请使用服务器核对的完整Pilot读集。",
        422,
    )


def _seal(bound):
    return digest(
        {
            "body": bound.body,
            "reads": bound.reads,
            "basis": bound.basis,
            "sources": bound.sources,
            "authority": bound.authority,
            "deadline": bound.deadline,
            "pointer": bound.pointer,
            "runtime": bound.runtime,
        }
    )


def _cas(s, ctx, command, product, bound, *, written=None):
    require_access(s, ctx, product.id, write=True, lock=True)
    require(product.revision == command.expected_revision, "VERSION_CONFLICT", "型号水位已变化。")
    root = bound.root or written
    pointer = None
    if root is not None:
        pointer = _pointer(s, ctx, product.id, root, lock=True)
        if written is None:
            require(
                _pointer_value(pointer) == bound.pointer, "VERSION_CONFLICT", "Pilot水位已变化。"
            )
        else:
            expected = {
                "revision": written.revision,
                "epoch": written.revision,
                "latest_observation_id": str(written.id) if type(written) is Observation else None,
            }
            require(
                _pointer_value(pointer) == expected, "VERSION_CONFLICT", "保存后Pilot指针不一致。"
            )
    return pointer


def _review(command, bound):
    return {
        "operation": command.operation,
        "before": deepcopy(bound.pointer),
        "after": deepcopy(bound.body),
        "authority": deepcopy(bound.authority),
        "required_source_read_set": deepcopy(bound.reads),
        "read_basis": deepcopy(bound.basis),
        "sources": deepcopy(bound.sources),
        "effect": "保存固定试产准备或原始观察；不授予资源资格、试产启动或制造放行。",
    }


class Prepared:
    def __init__(self, token, s, ctx, command, product, payload, bound):
        require(token is _CAPABILITY, "INVALID_PHASE", "缺实际Pilot准备阶段。", 503)
        self.session, self.uow, self.product = s, _uow(s), product
        self.ctx_sha, self.command_sha = digest(vars(ctx)), digest(command)
        self.payload_sha, self.bound, self.seal = digest(semantic(payload)), bound, _seal(bound)
        self.review = _review(command, bound)
        self.review_sha, self.used = digest(self.review), False

    def __reduce__(self):
        raise TypeError("Pilot phase stays in one transaction")

    def __copy__(self):
        raise TypeError("Pilot phase is one-use")

    def __deepcopy__(self, memo):
        raise TypeError("Pilot phase is one-use")


def _phase(s, ctx, command, product, payload, phase):
    require(
        type(phase) is Prepared
        and phase.session is s
        and phase.product is product
        and not phase.used,
        "INVALID_PHASE",
        "Pilot准备已使用或换事务。",
        503,
    )
    _same_uow(s, phase.uow, ctx, phase.ctx_sha)
    _command(s, ctx, command, product, payload)
    require(
        digest(command) == phase.command_sha
        and digest(semantic(payload)) == phase.payload_sha
        and _seal(phase.bound) == phase.seal
        and digest(phase.review) == phase.review_sha
        and phase.bound.runtime == _stamp(s),
        "PHASE_MATERIAL_CHANGED",
        "Pilot实质材料已变化。",
        503,
    )


def validate(s, ctx, command, product, payload):
    with s.no_autoflush:
        _load(s, ctx, command, product, payload)


def prepare_preview(s, ctx, command, product, payload):
    with s.no_autoflush:
        bound = _load(s, ctx, command, product, payload)
        _cas(s, ctx, command, product, bound)
        return Prepared(_CAPABILITY, s, ctx, command, product, payload, bound)


def preview_prepared(s, ctx, command, product, payload, phase):
    _phase(s, ctx, command, product, payload, phase)
    phase.used = True
    with s.no_autoflush:
        return deepcopy(phase.review)


def preview_view(s, ctx, command, product, payload):
    return preview_prepared(
        s, ctx, command, product, payload, prepare_preview(s, ctx, command, product, payload)
    )


def _confirmed_bound(s, ctx, command, product, payload, proof):
    """Reuse the actual common preview, comparing direct persisted watermarks."""
    _command(s, ctx, command, product, payload)
    require(
        isinstance(proof, Confirmation)
        and proof.payload_digest == material_digest(ctx, command, payload, sys.modules[__name__]),
        "CONFIRMATION_SCOPE_CHANGED",
        "确认载荷、版本或读集已变化。",
    )
    review = deepcopy(proof.snapshot)
    require(
        review.get("operation") == command.operation,
        "CONFIRMATION_SCOPE_CHANGED",
        "确认操作已变化。",
    )
    root, previous, pointer = None, None, None
    if type(payload) is PilotCreatePayload:
        create = payload
        require(
            snapshot_get(s, Pilot, payload.details.pilot_id, scope_id=product.id) is None,
            "VERSION_CONFLICT",
            "Pilot身份已存在。",
        )
    else:
        root = _root(s, ctx, product.id, payload.pilot_id)
        create = _retained(s, ctx, product.id, root)
        require(
            signature_current(s, ctx, product.id, root.project_id, root.authority_snapshot),
            "RECHECK_REQUIRED",
            "原Pilot签署依赖水位已变化，请先复核。",
        )
        current = _pointer(s, ctx, product.id, root, lock=True)
        pointer = _pointer_value(current)
        require(
            pointer == review.get("before")
            and pointer["revision"] == payload.expected_pilot_revision,
            "VERSION_CONFLICT",
            "Pilot水位已变化。",
        )
        if current.latest_observation_id is not None:
            previous = snapshot_get(
                s, Observation, current.latest_observation_id, scope_id=product.id
            )
            require(previous is not None, "STORED_ATOM_MISMATCH", "缺实际前驱观察。", 503)
            _retained(s, ctx, product.id, previous)
        require(
            payload.record.previous_observation_id == (previous.id if previous else None),
            "VERSION_CONFLICT",
            "前驱观察已变化。",
        )
    project = _project_row(s, ctx, product.id, create.project_id)
    authority, deadline = preparation._authority(s, ctx, command, project, write=True)
    require(
        authority["facts_revision"] == review["authority"]["facts_revision"]
        and authority["required_source_read_set"]
        == review["authority"]["required_source_read_set"],
        "RECHECK_REQUIRED",
        "本人职责或用途资格水位已变化。",
    )
    body, basis = review["after"], review["read_basis"]
    material = body["material"]
    runtime = _runtime(s)
    require(
        runtime.material.current(s, ctx, product.id, material["pilot"], basis["material_owner"])
        and runtime.statistics.current(
            s, ctx, product.id, material["statistics"], basis["statistics_owner"]
        ),
        "RECHECK_REQUIRED",
        "Pilot直接来源或资源水位已变化。",
    )
    require(
        configurations._source_state(s, ctx, product.id, review["required_source_read_set"])
        == "current",
        "SOURCE_STALE",
        "Pilot来源版本已变化。",
    )
    bound = Bound(
        None,
        None,
        root,
        pointer,
        previous,
        create,
        body,
        review["required_source_read_set"],
        basis,
        deepcopy(review["sources"]),
        body["gaps"],
        review["authority"],
        deadline,
        project,
        _stamp(s),
    )
    _reads(command, bound)
    return bound, review


def prepare_write_review(s, ctx, command, product, payload, proof=None):
    with s.no_autoflush:
        bound, review = _confirmed_bound(s, ctx, command, product, payload, proof)
        phase = Prepared(_CAPABILITY, s, ctx, command, product, payload, bound)
        phase.review = review
        phase.review_sha = digest(review)
        phase.pointer = _cas(s, ctx, command, product, bound)
        return phase, deepcopy(review)


def bind_consumption(s, ctx, command, product, payload, phase, proof):
    _phase(s, ctx, command, product, payload, phase)
    return _runtime(s).consumption.bind_before_transition(
        s, ctx, command, payload, sys.modules[__name__], proof, reviewed_snapshot=phase.review
    )


def record_consumption(s, ctx, command, product, payload, phase, proof, binding):
    marker = _runtime(s).consumption.capture_after_transition(
        s, ctx, command, payload, sys.modules[__name__], proof, binding=binding
    )
    _phase(s, ctx, command, product, payload, phase)
    return marker


def _saved_command(command, payload):
    value = command.model_dump(mode="json")
    value.pop("idempotency_key")
    value["payload"] = semantic(payload)
    return value


def apply_prepared_write(s, ctx, command, product, payload, phase, *, consumption):
    _phase(s, ctx, command, product, payload, phase)
    phase.used = True
    require(
        type(consumption) is tuple and len(consumption) == 2,
        "LIVE_CONSUMPTION_REQUIRED",
        "缺本次实际共同消费。",
        503,
    )
    binding, marker = consumption
    with s.no_autoflush:
        bound, pointer = phase.bound, phase.pointer
        live = _runtime(s).consumption.require_live(
            s,
            ctx,
            command,
            payload,
            sys.modules[__name__],
            binding.proof,
            binding=binding,
            marker=marker,
        )
        saved_at = now()
        preparation._deadline(bound.authority, saved_at, bound.deadline)
        require(
            live.tier == "T1"
            and live.consumed_at <= saved_at
            and proof_deadline_current("T1", live.expires_at, saved_at)
            and digest(binding.proof.snapshot) == phase.review_sha,
            "CONFIRMATION_REQUIRED",
            "完整材料的实际确认消费或有效期不满足。",
        )
        common = {
            "tenant_id": ctx.tenant_id,
            "category_id": ctx.category_id,
            "product_id": product.id,
            "project_id": bound.project.id,
            "owner_id": bound.root.owner_id if bound.root else ctx.requester_id,
            "writer_id": ctx.actor_id,
            "actor_id": ctx.actor_id,
            "requester_id": ctx.requester_id,
            "visibility": bound.root.visibility if bound.root else payload.visibility,
            "operation": command.operation,
            "write_tier": "T1",
            "status": "recorded",
            "material_snapshot": deepcopy(bound.body["material"]),
            "gaps": deepcopy(bound.gaps),
            "sources": deepcopy(bound.sources),
            "required_source_read_set": deepcopy(bound.reads),
            "source_basis": deepcopy(bound.basis),
            "authority_snapshot": deepcopy(bound.authority),
            "command_id": command.command_id,
            "receipt_id": uuid4(),
            "request_digest": preparation._request_digest(command, payload),
            "payload_sha256": digest(semantic(payload)),
            "created_at": saved_at,
            "input_snapshot": {
                "command": _saved_command(command, payload),
                "semantic": semantic(payload),
                "original_key_sha256": sha256(command.idempotency_key.encode("utf-8")).hexdigest(),
                "review": deepcopy(phase.review),
                "previous_current": deepcopy(bound.pointer),
            },
            **live.storage_columns(),
        }
        if type(payload) is PilotCreatePayload:
            basis = payload.details.basis
            row = Pilot(
                id=payload.details.pilot_id,
                revision=1,
                purpose=payload.details.purpose,
                details=payload.details.model_dump(mode="json"),
                statistics_basis=payload.statistics.model_dump(mode="json")
                if payload.statistics
                else None,
                build_id=basis.build.id,
                build_revision=basis.build.revision,
                lot_id=basis.lot.id,
                lot_revision=basis.lot.revision,
                actual_configuration_id=basis.actual_configuration.id,
                actual_configuration_revision=basis.actual_configuration.revision,
                engineering_configuration_id=basis.engineering_configuration.id,
                engineering_revision=basis.engineering_configuration.revision,
                process_id=basis.process_revision.id,
                process_revision=basis.process_revision.revision,
                publication_id=payload.details.manufacturing_baseline.id
                if payload.details.manufacturing_baseline
                else None,
                publication_revision=payload.details.manufacturing_baseline.revision
                if payload.details.manufacturing_baseline
                else None,
                **common,
            )
        else:
            row = Observation(
                id=payload.record.observation_id,
                pilot_id=payload.pilot_id,
                pilot_revision_before=payload.expected_pilot_revision,
                revision=payload.expected_pilot_revision + 1,
                previous_observation_id=payload.record.previous_observation_id,
                record=payload.record.model_dump(mode="json"),
                fixed_scope=deepcopy(bound.body["fixed_scope"]),
                projection=deepcopy(bound.body["projection"]),
                **common,
            )
        row.prepared_receipt_id, row.confirmation_id = row.receipt_id, live.proof_id
        row._pilot_finalization = (phase, binding, marker, bound)
        s.add(row)
        s.flush([row])
        if pointer is None:
            s.add(
                Current(
                    id=uuid4(),
                    tenant_id=ctx.tenant_id,
                    category_id=ctx.category_id,
                    product_id=product.id,
                    project_id=bound.project.id,
                    pilot_id=row.id,
                    owner_id=row.owner_id,
                    visibility=row.visibility,
                    revision=1,
                    latest_observation_id=None,
                    epoch=1,
                )
            )
        else:
            pointer.revision, pointer.latest_observation_id = row.revision, row.id
            pointer.epoch += 1
        return (
            row,
            CREATE_SUBJECT_TYPE if type(row) is Pilot else RESULT_SUBJECT_TYPE,
            row.visibility,
        )


def finalize_receipt(s, ctx, command, product, payload, subject, receipt):
    state = getattr(subject, "_pilot_finalization", None)
    require(
        type(subject) in (Pilot, Observation) and type(state) is tuple and len(state) == 4,
        "INVALID_PHASE",
        "缺原Pilot共同尾部绑定。",
        503,
    )
    phase, binding, marker, bound = state
    try:
        require(
            phase.used
            and phase.session is s
            and phase.product is product
            and digest(command) == phase.command_sha
            and digest(semantic(payload)) == phase.payload_sha
            and _seal(phase.bound) == phase.seal
            and digest(phase.review) == phase.review_sha
            and receipt.id == subject.receipt_id == subject.prepared_receipt_id
            and receipt.confirmation_id == subject.shared_proof_id,
            "PHASE_MATERIAL_CHANGED",
            "原共同回执或Pilot实质审阅已变化。",
            503,
        )
        _same_uow(s, phase.uow, ctx, phase.ctx_sha)
        _retained(s, ctx, product.id, subject)
        _runtime(s).consumption.require_live(
            s,
            ctx,
            command,
            payload,
            sys.modules[__name__],
            binding.proof,
            binding=binding,
            marker=marker,
        )
        preparation._deadline(bound.authority, now(), bound.deadline)
        require(
            proof_deadline_current("T1", marker.expires_at, now()),
            "CONFIRMATION_REQUIRED",
            "共同尾部实际确认已过期。",
        )
    finally:
        del subject._pilot_finalization


def apply(*args, **kwargs):
    raise DomainError("PHASED_COMMON_INTEGRATION_REQUIRED", "须通过实际共同T1确认办理Pilot。", 503)


def replay_subject_type(payload):
    return CREATE_SUBJECT_TYPE if type(payload) is PilotCreatePayload else RESULT_SUBJECT_TYPE


def replay_subject(s, ctx, command, product, payload):
    model = Pilot if type(payload) is PilotCreatePayload else Observation
    row = s.scalar(
        select(model).where(
            *_scope(model, ctx, product.id),
            model.actor_id == ctx.actor_id,
            model.operation == command.operation,
            model.intent_digest == _intent(ctx, command, payload),
        )
    )
    return row


def inputs(s, ctx, pid, command):
    require(
        command.product_id == pid and command.operation in PAYLOADS,
        "FORBIDDEN_SCOPE",
        "请选择本型号Pilot操作。",
        403,
    )
    require_access(s, ctx, pid, write=True, lock=True)
    product = s.scalar(
        select(Product)
        .where(Product.tenant_id == ctx.tenant_id, Product.id == pid)
        .with_for_update()
    )
    payload = PAYLOADS[command.operation].model_validate(command.payload)
    with s.no_autoflush:
        bound = _load(s, ctx, command, product, payload, require_reads=False)
        _cas(s, ctx, command, product, bound)
        updated = command.model_copy(
            update={"source_read_set": [SourceRead.model_validate(v) for v in bound.reads]}
        )
        return {"command": updated.model_dump(mode="json"), "review": _review(updated, bound)}


def _view(row, status):
    return {
        "id": str(row.id),
        "revision": row.revision,
        "created_at": row.created_at.isoformat(),
        "owner_id": str(row.owner_id),
        "writer_id": str(row.writer_id),
        "visibility": row.visibility,
        "receipt_id": str(row.receipt_id),
        "source_status": status,
        "sources": deepcopy(row.sources),
        "required_source_read_set": deepcopy(row.required_source_read_set),
        **_body(row),
    }


def get_pilot(s, ctx, pid, pilot_id):
    captured, caller, stamp = _uow(s), digest(vars(ctx)), _stamp(s)
    require_access(s, ctx, pid)
    root = _root(s, ctx, pid, pilot_id)
    _retained(s, ctx, pid, root)
    pointer = _pointer(s, ctx, pid, root)
    chain = _chain(s, ctx, pid, root, pointer)
    views = []
    for row in (root, *chain):
        status = configurations._source_state(s, ctx, pid, row.required_source_read_set)
        if status == "current":
            status = _live_status(s, ctx, pid, row)
        views.append(_view(row, status))
    require(stamp == _stamp(s), "RECHECK_REQUIRED", "读取期间Pilot实际owner已变化。")
    _same_uow(s, captured, ctx, caller)
    return root, {
        "schema_version": SCHEMA_VERSION,
        "pilot": views[0],
        "current": _pointer_value(pointer),
        "observations": views[1:],
        "project_id": str(root.project_id),
        "qualification": "unknown",
        "start_authorized": False,
        "manufacturing_release": None,
        "external_delivery": False,
    }


def _live_status(s, ctx, pid, row):
    """Compare direct Current/source watermarks, retaining signed history."""
    runtime = _runtime(s)
    material, basis = row.material_snapshot, row.source_basis
    try:
        current = signature_current(s, ctx, pid, row.project_id, row.authority_snapshot)
        current = current and runtime.material.current(
            s, ctx, pid, material["pilot"], basis["material_owner"]
        )
        current = current and runtime.statistics.current(
            s, ctx, pid, material["statistics"], basis["statistics_owner"]
        )
        return "current" if current else "needs_recheck"
    except DomainError as error:
        if error.status in {401, 403}:
            raise
        if error.code in {
            "SOURCE_STALE",
            "SOURCE_UNAVAILABLE",
            "MISSING_REQUIRED_EVIDENCE",
            "VERSION_CONFLICT",
            "QUALIFICATION_REQUIRED",
            "RECHECK_REQUIRED",
        }:
            return "needs_recheck"
        raise


def list_pilots(s, ctx, pid, *, project_id, history_cursor=None):
    require_access(s, ctx, pid)
    _project_row(s, ctx, pid, project_id)
    query = select(Pilot).where(*_scope(Pilot, ctx, pid), Pilot.project_id == project_id)
    if history_cursor is not None:
        try:
            cursor = UUID(history_cursor)
        except ValueError as error:
            raise DomainError("INVALID_PAYLOAD", "Pilot分页游标不正确。", 422) from error
        query = query.where(Pilot.id > cursor)
    rows = list(s.scalars(query.order_by(Pilot.id).limit(51)))
    items = [get_pilot(s, ctx, pid, row.id)[1] for row in rows[:50]]
    return {
        "schema_version": SCHEMA_VERSION,
        "items": items,
        "next_cursor": str(rows[49].id) if len(rows) > 50 else None,
        "project_id": str(project_id),
        "qualification": "unknown",
        "manufacturing_release": None,
    }
