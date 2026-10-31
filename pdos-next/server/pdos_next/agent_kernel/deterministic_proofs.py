"""Verify computed Claim content against an actual deterministic tool execution.

No engine is enabled by default. Trusted host composition supplies engines and must
write the read binding at the actual registered graph step. Neither a provider tool
argument nor an arbitrary completed read result is a computation proof. Bootstrap
supplies registered engines; the host and database seal the original execution.
"""

import hashlib
import json
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass, replace
from decimal import Decimal
from uuid import UUID

from pydantic import ValidationError

from pdos_next.domain.projects.models import Project
from pdos_next.errors import DomainError
from pdos_next.models import Product
from pdos_next.service import digest

from .bindings import ModelBinding, execution_key
from .disclosure import disclosed_in_run
from .execution import check_run_binding, scope_for_run
from .models import AgentRun, AgentToolCall
from .persistence import KernelStore
from .read_execution import ReadBinding
from .tools import COMPUTE


def _deny(reason="deterministic_proof_required"):
    error = DomainError("SOURCE_UNAVAILABLE", "计算事实缺少可核对的实际计算证明。")
    error.detail["reason"] = reason
    raise error


def _canonical(value):
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Non-finite decimal")
        text = format(value, "f")
        return "0" if value == 0 else text.rstrip("0").rstrip(".") if "." in text else text
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise ValueError("Non-string key")
        return {key: _canonical(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if value is None or type(value) in (str, int, bool):
        return value
    raise ValueError("Unsupported computation value")


def canonical_hash(value):
    return hashlib.sha256(
        json.dumps(
            _canonical(value),
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


@dataclass(frozen=True)
class ComputeEngine:
    version: str
    calculate: Callable[[dict], dict]
    claim_paths: tuple[tuple[str | int, ...], ...]


def _historical_read(session, scope, call_id, read_kind, *, deny):
    """Shared ordinary-RLS proof check; consumers retain the read's own isolation."""
    run = session.get(AgentRun, scope.run_id)
    check_run_binding(run, scope, for_write=False)
    if run.state not in {"queued", "running", "waiting_input", "completed", "partial"}:
        deny("run_inactive")
    return _completed_read(session, run, scope, call_id, read_kind, deny=deny)


def archived_citation_read(session, scope, call_id, *, deny):
    """Only provenance for reissuing search metadata, never an execution/write proof.

    Cancellation prevents all new work in that Run. Its sealed completed reads
    can still identify sources for a new Run, which reauthorizes and extracts
    them afresh. Business/compute/extraction proof consumers retain the strict
    _historical_read entry point.
    """
    run = session.get(AgentRun, scope.run_id)
    if run is None or scope != scope_for_run(run) or run.reverted_at:
        deny("archive_scope_invalid")
    if run.state not in {"failed", "cancelled"}:
        actual, call, binding, arguments = _historical_read(
            session, scope, call_id, "ordinary/v1", deny=deny
        )
    else:
        original_epoch = run.cancel_epoch - int(run.state == "cancelled")
        if original_epoch < 0:
            deny("archive_epoch_invalid")
        actual, call, binding, arguments = _completed_read(
            session, run, scope, call_id, "ordinary/v1", deny=deny, epoch=original_epoch
        )
    if (
        call.tool not in {
            "assistant.search", "assistant.materials.read", "assistant.citations.read",
            "conversation.history",
        }
        or binding.isolation != "main"
    ):
        deny("archive_tool_invalid")
    return actual, call, binding, arguments


def _completed_read(session, run, scope, call_id, read_kind, *, deny, epoch=None):
    # Both original principals must still have category access. The current RLS
    # transaction may be Human T1, so do not impersonate its old Agent actor when
    # checking product/project rows: those branches require that actor context.
    # Check their exact stored binding under the actual reader's ordinary RLS below.
    KernelStore(None).authority(session, replace(scope, product_id=None, project_id=None))
    if run.product_id is not None:
        product = session.get(Product, run.product_id)
        if (
            not product or product.tenant_id != run.tenant_id
            or product.category_id != run.category_id
        ):
            deny("scope_mismatch")
    if run.project_id is not None:
        project = session.get(Project, run.project_id)
        if (
            not project or project.tenant_id != run.tenant_id
            or project.category_id != run.category_id or project.product_id != run.product_id
        ):
            deny("scope_mismatch")
    call = session.get(AgentToolCall, call_id)
    if (
        not call or call.id != call_id or call.tenant_id != run.tenant_id
        or call.run_id != run.id or call.state != "completed"
        or call.error_code is not None or call.receipt_id is not None
        or not isinstance(call.result, dict)
    ):
        deny("call_invalid")
    try:
        binding = ReadBinding.model_validate(call.execution_binding)
    except ValidationError:
        deny("binding_invalid")
    if (
        binding.model_dump(mode="json") != call.execution_binding
        or binding.read_kind != read_kind or binding.tool != call.tool
        or binding.call_key != call.call_key
    ):
        deny("binding_invalid")
    for field in (
        "tenant_id", "category_id", "session_id", "requester_id", "writer_id",
        "product_id", "proposal_id", "private_context",
    ):
        if getattr(binding, field) != getattr(run, field):
            deny("scope_mismatch")
    if (
        binding.cancel_epoch != (run.cancel_epoch if epoch is None else epoch)
        or binding.run_id != run.id
        or binding.data_categories != tuple(sorted(run.data_categories))
        or binding.customer_identities != tuple(run.customer_identities)
    ):
        deny("scope_mismatch")
    model = session.get(AgentToolCall, binding.model_call_id)
    if (
        not model or model.id != binding.model_call_id or model.id == call.id
        or model.tenant_id != run.tenant_id or model.run_id != run.id
        or model.tool != "model" or model.state != "completed"
        or model.error_code is not None or model.receipt_id is not None
        or not isinstance(model.result, dict)
    ):
        deny("step_invalid")
    try:
        model_binding = ModelBinding.model_validate(model.execution_binding)
    except ValidationError:
        deny("step_invalid")
    versions = run.versions
    if not isinstance(versions, dict) or any(
        not isinstance(versions.get(key), dict) for key in ("tool_definitions", "prompt_prefixes")
    ):
        deny("step_invalid")
    if (
        model_binding.isolation != binding.isolation
        or model_binding.cancel_epoch != binding.cancel_epoch
        or model_binding.model_version != versions.get("model_version")
        or model_binding.model_route_digest != versions.get("model_route_digest")
        or not disclosed_in_run(versions, binding.isolation, model_binding.tool_definitions_digest)
        or model_binding.prompt_digest != versions["prompt_prefixes"].get(binding.isolation)
        or any(getattr(model_binding, key) != getattr(binding, key) for key in (
            "model_version", "model_route_digest", "tool_definitions_digest", "prompt_digest",
        ))
        or call.call_key != execution_key(run.id, model.id, binding.response_index)
    ):
        deny("step_invalid")
    calls = model.result.get("calls")
    if not isinstance(calls, list) or binding.response_index >= len(calls):
        deny("step_invalid")
    request = calls[binding.response_index]
    if (
        not isinstance(request, dict) or request.get("name") != call.tool
        or not isinstance(request.get("arguments"), dict)
        or call.input_digest != digest([call.tool, request["arguments"]])
    ):
        deny("input_mismatch")
    return run, call, binding, request["arguments"]


def resolve_compute_proof(
    session, ctx, run, reference, payload_content, *,
    engines: Mapping[str, ComputeEngine] | None = None,
):
    """Recompute the exact declared ClaimContent path from a persisted compute read.

    Completed Runs remain consumable under current ordinary-RLS authorization.
    Neither this proof nor Human adoption grants an engine or T0 qualification.
    The host fixes engine_version/result_digest before claiming its immutable Call.
    """
    try:
        if not isinstance(reference, dict) or set(reference) != {"call_id", "result_path"}:
            _deny()
        identity = UUID(str(reference["call_id"]))
        path = reference["result_path"]
        if not isinstance(path, list) or not path or any(type(k) not in (str, int) for k in path):
            _deny()
        if (
            run.tenant_id != ctx.tenant_id or run.category_id != ctx.category_id
            or run.requester_id != ctx.requester_id
            or ctx.actor_id not in {run.writer_id, run.requester_id}
            or getattr(ctx, "run_id", None) not in (None, run.id)
            or getattr(ctx, "agent_run_id", None) not in (None, run.id)
            or getattr(ctx, "cancel_epoch", None) not in (None, run.cancel_epoch)
        ):
            _deny("compute_run_mismatch")
        actual, call, binding, arguments = _historical_read(
            session, scope_for_run(run), identity, "compute/v1",
            deny=lambda reason: _deny("compute_" + reason),
        )
        if call.tool not in COMPUTE:
            _deny("compute_call_invalid")
        engine = (engines or {}).get(call.tool)
        if engine is None:
            _deny()
        if (
            binding.engine_version != engine.version or not engine.version
            or tuple(path) not in engine.claim_paths
        ):
            _deny("compute_binding_invalid")
        result_hash = canonical_hash(call.result)
        if (
            binding.result_digest != result_hash
            or canonical_hash(engine.calculate(deepcopy(arguments))) != result_hash
        ):
            _deny("compute_output_mismatch")
        value = call.result
        for key in path:
            if isinstance(value, list):
                if type(key) is not int or key < 0:
                    _deny("compute_path_invalid")
            elif not isinstance(value, dict) or not isinstance(key, str):
                _deny("compute_path_invalid")
            value = value[key]
        if not isinstance(value, dict) or canonical_hash(value) != canonical_hash(payload_content):
            _deny("compute_content_mismatch")
        return {
            "call_id": str(call.id), "run_id": str(actual.id), "tool": call.tool,
            "engine_version": engine.version, "input_digest": call.input_digest,
            "result_digest": result_hash, "result_path": list(path),
        }
    except (KeyError, IndexError, TypeError, ValueError, AttributeError, ValidationError):
        _deny()
