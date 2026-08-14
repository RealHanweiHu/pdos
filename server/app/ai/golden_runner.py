"""Read-only full-suite evaluator used before an operator publishes model qualification."""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.ai.context_projection import project_gateway_context
from app.ai.gateway import ModelProviderAdapter, json_document, structured_messages
from app.ai.golden_suite import GoldenAnswer, LoadedGoldenSuite
from app.ai.model_catalog import ResolvedModelRoute
from app.ai.provider_adapters import ProviderRequestError


class GoldenCaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    passed: bool
    attempts: int
    error_code: str | None
    input_tokens: int
    output_tokens: int


class GoldenEvaluationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str
    model: str
    suite_version: str
    suite_digest: str
    status: Literal["passed", "failed"]
    pass_rate: float
    cases: list[GoldenCaseResult]


def evaluate_candidate(
    route: ResolvedModelRoute,
    adapter: ModelProviderAdapter,
    loaded_suite: LoadedGoldenSuite,
    *,
    max_structured_attempts: int = 2,
) -> GoldenEvaluationReport:
    if not 1 <= max_structured_attempts <= 3:
        raise ValueError("structured attempt budget must be between 1 and 3")
    schema_json = json.dumps(
        GoldenAnswer.model_json_schema(), ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    results: list[GoldenCaseResult] = []
    for case in loaded_suite.suite.cases:
        projection = project_gateway_context(case.context)
        context_json = json.dumps(
            projection.payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        )
        input_tokens = 0
        output_tokens = 0
        result: GoldenCaseResult | None = None
        for attempt in range(1, max_structured_attempts + 1):
            try:
                response = adapter.complete(
                    route,
                    structured_messages(
                        system_prompt=case.system_prompt,
                        instruction=case.instruction,
                        context_json=context_json,
                        schema_json=schema_json,
                        retry=attempt > 1,
                    ),
                )
            except ProviderRequestError as error:
                result = GoldenCaseResult(
                    case_id=case.id,
                    passed=False,
                    attempts=attempt,
                    error_code=error.code.upper(),
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )
                break
            input_tokens += response.input_tokens
            output_tokens += response.output_tokens
            try:
                answer = GoldenAnswer.model_validate_json(json_document(response.content))
            except ValueError:
                continue
            matches = answer == case.expected
            result = GoldenCaseResult(
                case_id=case.id,
                passed=matches,
                attempts=attempt,
                error_code=None if matches else "EXPECTED_OUTPUT_MISMATCH",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
            break
        if result is None:
            result = GoldenCaseResult(
                case_id=case.id,
                passed=False,
                attempts=max_structured_attempts,
                error_code="STRUCTURED_OUTPUT_INVALID",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
        results.append(result)

    pass_rate = sum(result.passed for result in results) / len(results)
    return GoldenEvaluationReport(
        provider=route.provider.value,
        model=route.model,
        suite_version=loaded_suite.suite.suite_version,
        suite_digest=loaded_suite.digest,
        status="passed" if pass_rate >= loaded_suite.suite.pass_threshold else "failed",
        pass_rate=pass_rate,
        cases=results,
    )
