"""Pinned, read-only product capability evaluation; never grants model qualification.

Cases and reference answers are supplied candidates, not an automatically authored
trusted root. An executor sees runtime inputs only. Real execution authorization,
budgets and independent call verification remain outside this offline runner.
"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ai import product_matrix_preparation as matrix
from app.ai import product_work_context as work
from app.ai.application_domain_context import bundle
from app.ai.capability_contract import resolve_capability
from app.ai.context_projection import project_gateway_context
from app.ai.gateway import json_document, structured_messages
from app.ai.product_evidence_context import validate_refs
from app.ai.product_work_preparation import PROJECTION_VERSION
from app.ai.provider_adapters import ChatMessage, ProviderRequestError
from app.contracts.product_matrix_explanation import ProductMatrixExplanation
from app.contracts.product_work_ai import ProductCapability, ProductWorkAssessment
from app.domain.product_workspace import ProductWorkError
from app.domain.product_workspace import digest as source_digest

Capability = ProductCapability | Literal["product_matrix"]
MAX_SUITE_BYTES = 4 * 1024 * 1024
MAX_OUTPUT_BYTES = 256 * 1024


def canonical(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def digest(value: Any) -> str:
    return sha256(canonical(value).encode()).hexdigest()


def strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


class Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProductEvaluationCase(Frozen):
    case_id: str = Field(min_length=1, max_length=128)
    slices: tuple[str, ...] = Field(min_length=1, max_length=12)
    tenant_id: UUID
    source: dict[str, Any]
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    user_instruction: str = Field(default="", max_length=5000)
    expected_outputs: tuple[dict[str, Any], ...] = Field(min_length=1, max_length=8)


class ProductEvaluationSuite(Frozen):
    version: Literal["product-capability-evaluation.v1"]
    suite_version: str = Field(min_length=1, max_length=128)
    review_status: Literal["candidate"]
    capability: Capability
    prompt_version: str
    runtime_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    cases: tuple[ProductEvaluationCase, ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def distinct_cases(self) -> ProductEvaluationSuite:
        if len({case.case_id for case in self.cases}) != len(self.cases):
            raise ValueError("duplicate_case_id")
        if any(
            not name.strip() or len(name) > 128 or len(set(case.slices)) != len(case.slices)
            for case in self.cases
            for name in case.slices
        ):
            raise ValueError("invalid_case_slice")
        return self


@dataclass(frozen=True)
class LoadedProductSuite:
    document: bytes
    sha256: str


def load_product_suite(path: Path, *, expected_sha256: str) -> LoadedProductSuite:
    with path.open("rb") as source:
        document = source.read(MAX_SUITE_BYTES + 1)
    loaded = LoadedProductSuite(document, expected_sha256)
    _suite(loaded)
    return loaded


def _suite(loaded: LoadedProductSuite) -> ProductEvaluationSuite:
    if (
        len(loaded.document) > MAX_SUITE_BYTES
        or sha256(loaded.document).hexdigest() != loaded.sha256
    ):
        raise ValueError("suite_original_digest_mismatch_or_too_large")
    return ProductEvaluationSuite.model_validate(
        json.loads(loaded.document, object_pairs_hook=strict_object)
    )


def runtime_contract(capability: Capability) -> tuple[Any, type[BaseModel], dict[str, Any]]:
    prompt: Any
    output: type[BaseModel]
    version = resolve_capability(f"product_management_intelligence.{capability}").prompt_version
    if capability == "product_matrix":
        prompt, output = matrix.PROMPT, ProductMatrixExplanation
        purpose = "product_matrix"
    else:
        prompt, output = work.contract(capability=capability)
        purpose = "product_work"
    if version != prompt.version:
        raise ValueError("registered_prompt_mismatch")
    return prompt, output, bundle(purpose, prompt_version=prompt.version)


def validated_output(
    value: dict[str, Any],
    output_type: type[BaseModel],
    case: ProductEvaluationCase,
    capability: Capability,
) -> BaseModel:
    output = output_type.model_validate(value)
    validate_source_binding(output, case, capability)
    return output


def validate_source_binding(
    output: BaseModel, case: ProductEvaluationCase, capability: Capability
) -> None:
    if capability == "product_matrix":
        assert isinstance(output, ProductMatrixExplanation)
        matrix.validate_assessment(output, case.source)
    else:
        assert isinstance(output, ProductWorkAssessment)
        work.validate_assessment(output, case.source)
        validate_refs(output, case.source, case.tenant_id)


class ProductEvaluationBinding(Frozen):
    provider: str = Field(min_length=1, max_length=128)
    model: str = Field(min_length=1, max_length=256)
    protocol: str = Field(min_length=1, max_length=128)
    configuration_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ProductEvaluationRequest(Frozen):
    binding: ProductEvaluationBinding
    case_id: str
    capability: Capability
    attempt: int
    prompt_version: str
    runtime_sha256: str
    context_json: str
    output_schema_json: str
    messages: tuple[ChatMessage, ...]


class ProductEvaluationResponse(Frozen):
    content: str
    input_tokens: int = Field(default=0, ge=0, strict=True)
    output_tokens: int = Field(default=0, ge=0, strict=True)
    execution_source: Literal["offline_replay", "provider_claim"] = "offline_replay"
    original_receipt_ref: str | None = Field(default=None, max_length=2048)
    reported_model: str | None = Field(default=None, max_length=256)


class ProductEvaluationExecutor(Protocol):
    def __call__(self, request: ProductEvaluationRequest) -> ProductEvaluationResponse: ...


class OfflineProductReplay:
    def __init__(self, outputs: Mapping[str, Sequence[str]]) -> None:
        self.outputs = {key: tuple(values) for key, values in outputs.items()}

    def __call__(self, request: ProductEvaluationRequest) -> ProductEvaluationResponse:
        values = self.outputs.get(request.case_id, ())
        if request.attempt > len(values):
            raise ProviderRequestError("offline_response_missing", "Replay response missing")
        return ProductEvaluationResponse(content=values[request.attempt - 1])


def run_product_evaluation(
    loaded: LoadedProductSuite,
    *,
    binding: ProductEvaluationBinding,
    executor: ProductEvaluationExecutor,
    max_structured_attempts: int = 2,
) -> dict[str, Any]:
    started_at = datetime.now(UTC).isoformat()
    if type(max_structured_attempts) is not int or not 1 <= max_structured_attempts <= 3:
        raise ValueError("invalid_attempt_limit")
    suite = _suite(loaded)
    prompt, output_type, runtime = runtime_contract(suite.capability)
    if suite.prompt_version != prompt.version or suite.runtime_sha256 != digest(runtime):
        raise ValueError("evaluation_runtime_changed")
    schema = canonical(output_type.model_json_schema())
    prepared = []
    # Validate every source and reference answer before the first executor call.
    for case in suite.cases:
        if digest(case.source) != case.source_sha256 or case.source.get("digest") != source_digest(
            {k: v for k, v in case.source.items() if k != "digest"}
        ):
            raise ValueError("evaluation_source_changed")
        if suite.capability == "product_matrix":
            matrix.prompt_for(case.source)
            context = matrix.model_context(case.source, case.user_instruction)
        else:
            if (
                case.source.get("projection_version") != PROJECTION_VERSION
                or case.source["selection"]["capability"] != suite.capability
            ):
                raise ValueError("evaluation_source_scope_mismatch")
            context = work.model_context(
                case.source,
                case.user_instruction,
                prompt_version=prompt.version,
                tenant_id=case.tenant_id,
            )
        answers = tuple(
            canonical(
                validated_output(value, output_type, case, suite.capability).model_dump(mode="json")
            )
            for value in case.expected_outputs
        )
        if len(set(answers)) != len(answers):
            raise ValueError("duplicate_reference_answer")
        projection = project_gateway_context(context)
        requests = []
        for attempt in range(1, max_structured_attempts + 1):
            request = ProductEvaluationRequest(
                binding=binding,
                case_id=case.case_id,
                capability=suite.capability,
                attempt=attempt,
                prompt_version=prompt.version,
                runtime_sha256=suite.runtime_sha256,
                context_json=canonical(projection.payload),
                output_schema_json=schema,
                messages=tuple(
                    structured_messages(
                        system_prompt=prompt.system_prompt,
                        instruction=prompt.instruction,
                        context_json=canonical(projection.payload),
                        schema_json=schema,
                        retry=attempt > 1,
                    )
                ),
            )
            requests.append(request)
        prepared.append((case, answers, projection, tuple(requests)))
    receipts: list[dict[str, Any]] = []
    for case, answers, projection, prepared_requests in prepared:
        attempts: list[dict[str, Any]] = []
        passed = False
        for request in prepared_requests:
            record: dict[str, Any] = {
                "request": request.model_dump(mode="json"),
                "request_sha256": digest(request.model_dump(mode="json")),
                "status": "call_failed",
                "error_code": None,
                "response": None,
                "typed_output": None,
                "usage": {"input_tokens": 0, "output_tokens": 0},
            }
            tick = time.perf_counter()
            try:
                response = ProductEvaluationResponse.model_validate(executor(request))
            except ProviderRequestError as error:
                record["error_code"] = error.code
                if error.usage:
                    record["usage"] = {
                        "input_tokens": error.usage.input_tokens,
                        "output_tokens": error.usage.output_tokens,
                    }
                attempts.append(record)
                break
            except Exception:
                # Do not leak provider exceptions, credentials or candidate expected answers.
                record["error_code"] = "executor_failed"
                attempts.append(record)
                break
            finally:
                record["duration_seconds"] = time.perf_counter() - tick
            record["response"] = response.model_dump(mode="json")
            record["usage"] = {
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
            }
            record["output_sha256"] = sha256(response.content.encode()).hexdigest()
            if len(response.content.encode()) > MAX_OUTPUT_BYTES:
                record["response"]["content"] = None
                record.update(status="invalid_output", error_code="output_too_large")
                attempts.append(record)
                break
            try:
                raw = json.loads(json_document(response.content), object_pairs_hook=strict_object)
                output = output_type.model_validate(raw)
            except ValueError:
                record.update(status="invalid_output", error_code="output_contract_invalid")
                attempts.append(record)
                continue
            record["typed_output"] = output.model_dump(mode="json")
            try:
                validate_source_binding(output, case, suite.capability)
            except ProductWorkError:
                record.update(
                    status="source_binding_failed", error_code="citation_or_scope_invalid"
                )
                attempts.append(record)
                break
            passed = canonical(record["typed_output"]) in answers
            record.update(
                status="matched" if passed else "answer_mismatch",
                error_code=None if passed else "reference_answer_mismatch",
            )
            attempts.append(record)
            # A valid answer outside the fixed candidate variants is not a format retry.
            break
        receipts.append(
            {
                "case_id": case.case_id,
                "slices": list(case.slices),
                "source_sha256": case.source_sha256,
                "case_sha256": digest(case.model_dump(mode="json")),
                "removed_context_paths": list(projection.removed_paths),
                "passed": passed,
                "attempts": attempts,
            }
        )
    slices = {
        name: {
            "cases": sum(name in r["slices"] for r in receipts),
            "passed": sum(r["passed"] for r in receipts if name in r["slices"]),
        }
        for name in sorted({name for r in receipts for name in r["slices"]})
    }
    usage = {
        key: sum(a["usage"][key] for receipt in receipts for a in receipt["attempts"])
        for key in ("input_tokens", "output_tokens")
    }
    report = {
        "version": "product-capability-report.v1",
        "binding": binding.model_dump(mode="json"),
        "started_at": started_at,
        "completed_at": datetime.now(UTC).isoformat(),
        "usage": usage,
        "capability": suite.capability,
        "suite_version": suite.suite_version,
        "suite_sha256": loaded.sha256,
        "suite_snapshot": suite.model_dump(mode="json"),
        "runtime_snapshot": runtime,
        "runtime_sha256": suite.runtime_sha256,
        "status": "passed" if all(r["passed"] for r in receipts) else "failed",
        "cases": receipts,
        "slices": slices,
        "answer_match_rule": "normalized_full_output_equals_candidate_variant",
        "manual_review_required": True,
        "source_authorization_verified": False,
        "provider_calls_verified": False,
        "reference_answers_approved": False,
        "qualification_granted": False,
    }
    return {**report, "report_sha256": digest(report)}
