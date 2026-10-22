"""Compare actual settled RFQ rows, without accepting replacement customer values."""

from copy import deepcopy
from typing import Annotated
from uuid import UUID

from pydantic import Field, ValidationError, model_validator
from sqlalchemy import select

from pdos_next.domain.preproject import standard_match
from pdos_next.domain.preproject.access import proposal
from pdos_next.domain.preproject.category_models import ParameterCurrent, ParameterVersion
from pdos_next.domain.preproject.category_service import parameter_version
from pdos_next.domain.preproject.schemas import SpecItem
from pdos_next.errors import DomainError
from pdos_next.schema_base import StrictModel
from pdos_next.service import digest

from .deterministic_proofs import _historical_read, canonical_hash
from .extract_schemas import RFQDraftRow

VERSION = "extracted-standard-match/v1"


class ExtractionRows(StrictModel):
    call_id: UUID
    row_indices: list[Annotated[int, Field(strict=True, ge=0)]] | None = Field(
        default=None, min_length=1
    )

    @model_validator(mode="after")
    def actual_indices(self):
        if self.row_indices is not None and (
            any(type(index) is not int or index < 0 for index in self.row_indices)
            or len(set(self.row_indices)) != len(self.row_indices)
        ):
            raise ValueError("Row indices must be distinct nonnegative integers")
        return self


def _unavailable(reason):
    raise DomainError(
        "SOURCE_UNAVAILABLE",
        "需求核对须使用本次运行已核对的 RFQ 抽取行。",
        detail={"reason": reason},
    )


def map_spec(raw, current, resolve):
    """Suggest an identity; never fill customer values, units or conditions."""
    content = deepcopy(raw)
    candidates, basis, parameter = [], None, None
    if raw.get("parameter_id") is not None:
        try:
            parameter = resolve(UUID(str(raw["parameter_id"])), raw["parameter_version"])
            basis = "extracted_reference"
        except DomainError:
            pass
    else:
        labels = {str(raw.get(key, "")).strip().casefold() for key in ("key", "parameter")}
        candidates = [
            item
            for item in current
            if labels.intersection({item.key.strip().casefold(), item.name.strip().casefold()})
        ]
        if len(candidates) == 1:
            parameter, basis = candidates[0], "exact_dictionary_label"
    if parameter is not None:
        content.update(
            parameter_id=parameter.parameter_id,
            parameter_version=parameter.version,
            key=parameter.key,
            parameter=parameter.name,
        )
    else:
        # Invalid explicit references remain unresolved, not an invented dictionary entry.
        content.update(parameter_id=None, parameter_version=None)
    mapping = {
        "status": "mapped" if parameter else "ambiguous" if candidates else "unmapped",
        "basis": basis,
        "parameter_id": str(parameter.parameter_id) if parameter else None,
        "parameter_version": parameter.version if parameter else None,
        "candidates": [
            {
                "parameter_id": str(item.parameter_id),
                "version": item.version,
                "key": item.key,
                "name": item.name,
            }
            for item in candidates
        ]
        if parameter is None
        else [],
    }
    return SpecItem.model_validate(
        {**content, "nature": "extracted", "item_status": "ai_draft", "owner_id": None}
    ), mapping


def compare_extracted(session, ctx, scope, payload, *, extraction, public):
    reference = payload.extraction_ref
    actual, call, _, original_arguments = _historical_read(
        session,
        scope,
        reference.call_id,
        "ordinary/v1",
        deny=lambda reason: _unavailable("extraction_" + reason),
    )
    if call.tool != "evidence.extract" or actual.proposal_id is None:
        _unavailable("extraction_call_invalid")
    if call.result.get("row_schema") != {"kind": "rfq_requirement", "version": "1"}:
        _unavailable("rfq_row_schema_required")
    target = proposal(session, ctx, actual.proposal_id)
    if (
        "customer_original" not in set(actual.data_categories)
        or (target.effective_visibility != "category" or target.private_source_count)
        and not actual.private_context
        or not set(target.customer_identities).issubset(actual.customer_identities)
    ):
        _unavailable("private_run_binding_required")
    # Restore validates current sealed originals, scans, quotations and coverage;
    # it never calls the extraction graph or a provider.
    restored = extraction.restore(scope, original_arguments, call.result)
    rows = restored.get("rows")
    if not isinstance(rows, list):
        _unavailable("extraction_rows_missing")
    indices = reference.row_indices if reference.row_indices is not None else list(range(len(rows)))
    if any(index >= len(rows) for index in indices):
        _unavailable("extraction_row_missing")
    for subject in payload.subjects:
        if actual.product_id is not None and subject.id != actual.product_id:
            raise DomainError("FORBIDDEN_SCOPE", "核对型号不属于本次运行。", 403)
        public.product(subject.id)
    current = list(
        session.scalars(
            select(ParameterVersion)
            .join(
                ParameterCurrent,
                (
                    (ParameterCurrent.tenant_id == ParameterVersion.tenant_id)
                    & (ParameterCurrent.category_id == ParameterVersion.category_id)
                    & (ParameterCurrent.parameter_id == ParameterVersion.parameter_id)
                    & (ParameterCurrent.current_version == ParameterVersion.version)
                ),
            )
            .where(
                ParameterVersion.tenant_id == ctx.tenant_id,
                ParameterVersion.category_id == ctx.category_id,
            )
            .order_by(ParameterVersion.parameter_id)
        )
    )
    projected, requirements = [], []
    for index in indices:
        row = rows[index]
        try:
            draft = RFQDraftRow.model_validate(
                {
                    **row["fields"],
                    "artifact_version_id": row["artifact_id"],
                    "locator": row["locator"],
                    "quote": row["quote"],
                }
            )
        except (KeyError, TypeError, ValidationError):
            _unavailable("extraction_row_invalid")
        view = {
            "row_index": index,
            "kind": draft.kind,
            "statement": draft.statement,
            "missing": draft.missing,
            "citation": {
                key: row[key]
                for key in ("artifact_id", "revision", "locator", "quote", "read_call_ids")
            },
        }
        if draft.spec is not None:
            raw = draft.spec.model_dump(mode="json")
            required, mapping = map_spec(
                raw,
                current,
                lambda identity, version: parameter_version(session, ctx, identity, version),
            )
            view.update(
                requirement_index=len(requirements), parameter_mapping=mapping, extracted_spec=raw
            )
            requirements.append(required)
        projected.append(view)
    calculation = (
        standard_match.match(
            session,
            ctx,
            {
                "product_ids": [subject.id for subject in payload.subjects],
                "requirements": requirements,
            },
            before_definition_read=public.definition_head,
        )
        if requirements
        else None
    )
    limitations = ["selected_specifications_only", "human_understanding_not_confirmed"]
    if set(indices) != set(range(len(rows))):
        limitations.append("selected_extraction_rows_only")
    if any(row["kind"] != "spec" for row in projected):
        limitations.append("non_spec_requirements_require_review")
    if (
        restored.get("rejected")
        or restored.get("failures")
        or any(
            entry.get("original_locations", {}).get("fully_read") is not True
            for entry in restored.get("coverage", [])
        )
    ):
        limitations.append("extraction_coverage_incomplete_or_unknown")
    result = {
        "engine_version": VERSION,
        "mode": "extracted_standard_match",
        "proposal_id": str(actual.proposal_id),
        "extraction_ref": {
            "call_id": str(call.id),
            "row_indices": indices,
            "result_digest": canonical_hash(call.result),
        },
        "rows": projected,
        "summary": {
            "selected_rows": len(projected),
            "spec_rows": len(requirements),
            "non_spec_rows": len(projected) - len(requirements),
            **{
                f"{status}_specs": sum(
                    row.get("parameter_mapping", {}).get("status") == status for row in projected
                )
                for status in ("mapped", "ambiguous", "unmapped")
            },
        },
        "requirements": calculation["requirements"] if calculation else [],
        "products": calculation["products"] if calculation else [],
        "selected_product_ids": [str(subject.id) for subject in payload.subjects],
        "comparison_digest": calculation["comparison_digest"] if calculation else None,
        "coverage": deepcopy(restored["coverage"]),
        "rejected": deepcopy(restored.get("rejected", [])),
        "failures": deepcopy(restored.get("failures", [])),
        "limitations": limitations,
        "next_step": "confirm_full_scope_then_crm",
    }
    result["input_digest"] = digest(result)
    return result
