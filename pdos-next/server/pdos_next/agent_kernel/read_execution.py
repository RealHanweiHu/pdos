"""Server-owned read execution provenance; no persistence or domain write authority.

New reads validate the active Run and its actual completed model response. A
historical consumer must validate the persisted binding's isolation, rather than
substituting its own (usually main) isolation. This module does not authorize
source access or outbound data: the actual read adapter still owns those checks.
"""

from typing import Literal
from uuid import UUID

from pydantic import ConfigDict, Field, ValidationError, model_serializer, model_validator

from pdos_next.errors import DomainError
from pdos_next.schema_base import StrictModel
from pdos_next.service import digest

from .bindings import ModelBinding, execution_key
from .disclosure import binding_operations, disclosed_in_run, disclosure
from .execution import check_run_binding
from .models import AgentRun, AgentToolCall
from .types import Isolation

ReadKind = Literal["ordinary/v1", "compute/v1", "registered_snapshot/v1"]
Hash = str


class ReadSource(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    model_call_id: UUID
    response_index: int = Field(strict=True, ge=0)


class ReadBinding(ReadSource):
    """Immutable complete claim-time facts, never a provider argument schema."""

    kind: Literal["read"] = "read"
    read_kind: ReadKind
    proof_version: int = Field(default=1, strict=True, ge=1, le=1)
    graph: Literal["xiaopai"] = "xiaopai"
    step: Literal["tools"] = "tools"
    isolation: Isolation
    tenant_id: UUID
    category_id: UUID | None
    run_id: UUID
    session_id: UUID
    requester_id: UUID
    writer_id: UUID
    product_id: UUID | None
    proposal_id: UUID | None
    cancel_epoch: int = Field(strict=True, ge=0)
    private_context: bool = Field(strict=True)
    data_categories: tuple[str, ...]
    customer_identities: tuple[str, ...]
    tool: str = Field(min_length=1, max_length=160)
    call_key: str = Field(min_length=1, max_length=200)
    model_version: str = Field(min_length=1, max_length=160)
    model_route_digest: Hash = Field(pattern=r"^[a-f0-9]{64}$")
    tool_definitions_digest: Hash = Field(pattern=r"^[a-f0-9]{64}$")
    prompt_digest: Hash = Field(pattern=r"^[a-f0-9]{64}$")
    engine_version: str | None = Field(default=None, min_length=1, max_length=160)
    result_digest: Hash | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    page_chars: int | None = Field(default=None, strict=True, ge=1, le=200_000)

    @model_validator(mode="after")
    def coherent_kind(self):
        if self.call_key != execution_key(self.run_id, self.model_call_id, self.response_index):
            raise ValueError("Read key must identify the actual model response position")
        if self.read_kind == "compute/v1":
            if (
                self.engine_version is None or self.result_digest is None
                or self.page_chars is not None or self.isolation != "main"
            ):
                raise ValueError("Compute binding needs its server engine and complete result hash")
        elif self.read_kind == "registered_snapshot/v1":
            if (
                self.page_chars is None or self.engine_version is not None
                or self.result_digest is not None or self.isolation != "research"
                or self.tool != "research.read" or self.category_id is None
            ):
                raise ValueError("Registered snapshot binding needs a category research page")
        elif any(v is not None for v in (self.engine_version, self.result_digest, self.page_chars)):
            raise ValueError("Ordinary reads cannot declare compute or snapshot metadata")
        return self

    @model_serializer(mode="wrap")
    def omit_irrelevant_metadata(self, handler):
        result = handler(self)
        for key in ("engine_version", "result_digest", "page_chars"):
            if result.get(key) is None:
                result.pop(key, None)
        return result


def _deny(reason, *, code="FORBIDDEN_SCOPE"):
    raise DomainError(code, "读取须绑定实际运行、模型回复和登记工具。", detail={"reason": reason})


def _model_matches_run(run, scope, model):
    versions = run.versions
    if not isinstance(versions, dict) or any(
        not isinstance(versions.get(key), dict) for key in ("tool_definitions", "prompt_prefixes")
    ):
        _deny("read_versions_invalid", code="VERSION_CONFLICT")
    if (
        model.isolation != scope.isolation or model.cancel_epoch != run.cancel_epoch
        or model.model_version != versions.get("model_version")
        or model.model_route_digest != versions.get("model_route_digest")
        or not disclosed_in_run(versions, scope.isolation, model.tool_definitions_digest)
        or model.prompt_digest != versions["prompt_prefixes"].get(scope.isolation)
    ):
        _deny("read_model_binding_mismatch", code="VERSION_CONFLICT")


def verify_read_source(
    session, scope, run, spec, arguments, source, registry, route, *,
    catalog=None, intent_key=None,
):
    """Return the actual ModelBinding after validating a new, active read.

    Call within the host's ordinary RLS transaction. Registry authorization and
    exact current schema digest are checked here; payload semantic/schema parsing
    remains the registered adapter's responsibility, just as for existing reads.
    No skill-load or T0 qualification is required for READ. ``intent_key`` is the
    dispatcher key, not a provider/native tool-call ID; pass it when claiming.
    """
    if not isinstance(source, ReadSource):
        _deny("read_source_required")
    if catalog is None:
        from .skills import SkillCatalog

        catalog = SkillCatalog()
    try:
        actual = session.get(AgentRun, scope.run_id)
        check_run_binding(actual, scope)
        check_run_binding(run, scope)
        if run.versions != actual.versions:
            _deny("read_run_changed", code="VERSION_CONFLICT")
        expected_key = execution_key(actual.id, source.model_call_id, source.response_index)
        if intent_key is not None and intent_key != expected_key:
            _deny("read_intent_mismatch", code="DUPLICATE_INTENT_CONFLICT")
        if (
            spec.tier != "READ" or spec.kind not in {"read", "research", "compute"}
            or spec.operation_key is not None or spec.name == "skill.load"
            or not isinstance(arguments, dict)
        ):
            _deny("read_tool_required")
        current = registry.get(spec.name)
        if current != spec:
            _deny("read_registry_changed", code="VERSION_CONFLICT")
        registry.authorize(scope, spec.name, arguments, {}, lambda *_: False)
        if not any(
            item["name"] == spec.name for item in registry.definitions(scope.isolation)
        ):
            _deny("read_tool_isolation_mismatch")
        call = session.get(AgentToolCall, source.model_call_id)
        if (
            not call or call.id != source.model_call_id
            or call.tenant_id != actual.tenant_id or call.run_id != actual.id
            or call.tool != "model" or call.state != "completed"
            or call.error_code is not None or call.receipt_id is not None
        ):
            _deny("read_model_call_invalid")
        model = ModelBinding.model_validate(call.execution_binding)
        _model_matches_run(actual, scope, model)
        # A read is only trusted when the call it cites disclosed this tool, which
        # the binding's own loaded skills must imply (see .disclosure).
        disclosed = disclosure(
            registry, scope.isolation, binding_operations(catalog, model.loaded_skills)
        )
        if (
            route is None or route.version != model.model_version
            or route.digest != model.model_route_digest
            or digest(disclosed) != model.tool_definitions_digest
            or not any(item["name"] == spec.name for item in disclosed)
        ):
            _deny("read_route_or_registry_changed", code="VERSION_CONFLICT")
        calls = call.result.get("calls") if isinstance(call.result, dict) else None
        if not isinstance(calls, list) or source.response_index >= len(calls):
            _deny("read_response_index_invalid")
        request = calls[source.response_index]
        if (
            not isinstance(request, dict) or request.get("name") != spec.name
            or not isinstance(request.get("arguments"), dict)
            or digest([spec.name, request["arguments"]]) != digest([spec.name, arguments])
        ):
            _deny("read_model_input_mismatch", code="DUPLICATE_INTENT_CONFLICT")
        return model
    except (AttributeError, KeyError, TypeError, ValueError, ValidationError):
        _deny("read_binding_invalid")


def build_read_binding(
    scope, run, spec, source, model_binding, *, read_kind="ordinary/v1", server_metadata=None
):
    """Build claim-time immutable metadata after ``verify_read_source`` succeeds.

    The host supplies metadata from its selected pure engine or page policy, never
    from tool arguments. Compute results must already exist before claiming if
    their digest is stored here; existing bindings must never be updated at settle.
    """
    if not isinstance(source, ReadSource) or not isinstance(model_binding, ModelBinding):
        _deny("read_source_required")
    check_run_binding(run, scope)
    _model_matches_run(run, scope, model_binding)
    allowed = {
        "ordinary/v1": set(),
        "compute/v1": {"engine_version", "result_digest"},
        "registered_snapshot/v1": {"page_chars"},
    }
    metadata = {} if server_metadata is None else server_metadata
    if (
        read_kind not in allowed or not isinstance(metadata, dict)
        or set(metadata) != allowed[read_kind]
        or spec.tier != "READ" or spec.operation_key is not None
        or spec.kind not in {"read", "research", "compute"} or spec.name == "skill.load"
        or (read_kind == "compute/v1" and spec.kind != "compute")
    ):
        _deny("read_metadata_invalid")
    try:
        return ReadBinding(
            read_kind=read_kind,
            isolation=model_binding.isolation,
            **{key: getattr(run, key) for key in (
                "tenant_id", "category_id", "session_id", "requester_id", "writer_id",
                "product_id", "proposal_id", "cancel_epoch", "private_context",
            )},
            run_id=run.id,
            data_categories=tuple(sorted(run.data_categories)),
            customer_identities=tuple(run.customer_identities),
            tool=spec.name,
            call_key=execution_key(run.id, source.model_call_id, source.response_index),
            **source.model_dump(),
            **{key: getattr(model_binding, key) for key in (
                "model_version", "model_route_digest", "tool_definitions_digest", "prompt_digest",
            )},
            **metadata,
        )
    except (ValidationError, TypeError, ValueError):
        _deny("read_metadata_invalid")
