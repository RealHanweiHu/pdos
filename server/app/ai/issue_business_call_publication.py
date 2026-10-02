"""Read operator-verified business call originals; never publish or grant eligibility.

The trusted server file and SHA must be installed only after an operator compares
provider receipts with the immutable local invocation/context/result originals.
HTTP/model output cannot supply this configuration. A synthetic transport, an
independent golden evaluation, or a successful local trace alone is not proof.
"""

import json
import re
from collections.abc import Mapping
from datetime import datetime
from hashlib import sha256
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, ValidationError, model_validator

from app.ai.observations import digest
from app.ai.write_evaluation_publication import (
    WriteEvaluationPublicationError,
    _read_bounded_file,
    _unique_json_object,
)
from app.contracts.ai_issue_evaluation import IssueEvaluationBinding
from app.contracts.common_objects import Contract, Digest, Text

PATH = "PDOS_AI_ISSUE_BUSINESS_CALL_PUBLICATION_PATH"
SHA256 = "PDOS_AI_ISSUE_BUSINESS_CALL_PUBLICATION_SHA256"


class BusinessCall(Contract):
    project_id: UUID
    run_id: UUID
    invocation_id: UUID
    binding: IssueEvaluationBinding
    execution_source: Literal["real_business"]
    originals_digest: Digest
    provider_receipt_ref: Text
    provider_receipt_digest: Digest
    completed_at: AwareDatetime


class BusinessCallPublication(Contract):
    version: Literal["issue-business-call-publication.v1"]
    publication_id: UUID
    tenant_id: UUID
    published_by: UUID
    actor_kind: Literal["human"]
    actor_identity_source: Literal["operator_verified_identity"]
    actor_identity_ref: Text
    actor_identity_digest: Digest
    published_at: AwareDatetime
    valid_from: AwareDatetime
    valid_until: AwareDatetime
    calls: Annotated[tuple[BusinessCall, ...], Field(min_length=1, max_length=2000)]

    @model_validator(mode="after")
    def originals(self) -> Self:
        if not self.published_at <= self.valid_from < self.valid_until:
            raise ValueError("publication_time_order")
        for field in ("run_id", "invocation_id", "provider_receipt_ref", "provider_receipt_digest"):
            if len({getattr(call, field) for call in self.calls}) != len(self.calls):
                raise ValueError("duplicate_business_original")
        if any(call.completed_at > self.published_at for call in self.calls):
            raise ValueError("business_call_after_publication")
        return self


def originals_digest(row: Mapping[str, Any]) -> str:
    """Only immutable originals; later run control, review and application may change."""
    return digest(
        {
            k: row.get(k)
            for k in (
                "generation",
                "result",
                "call",
                "observation",
                "checkpoint",
                "manifest",
                "admission",
            )
        }
    )


def load_publication(
    environment: Mapping[str, str], tenant_id: UUID, as_of: datetime
) -> tuple[BusinessCallPublication, str] | None:
    path, pin = environment.get(PATH, ""), environment.get(SHA256, "")
    if not path and not pin:
        return None
    if not path or not re.fullmatch(r"[a-f0-9]{64}", pin):
        raise WriteEvaluationPublicationError("business_publication_configuration_invalid")
    body = _read_bounded_file(path)
    if sha256(body).hexdigest() != pin:
        raise WriteEvaluationPublicationError("business_publication_digest_mismatch")
    try:
        document = BusinessCallPublication.model_validate(
            json.loads(body, object_pairs_hook=_unique_json_object)
        )
    except (ValidationError, UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise WriteEvaluationPublicationError("business_publication_invalid_document") from error
    if document.tenant_id != tenant_id:
        raise WriteEvaluationPublicationError("business_publication_tenant_mismatch")
    if as_of.tzinfo is None or not document.valid_from <= as_of < document.valid_until:
        raise WriteEvaluationPublicationError("business_publication_outside_validity")
    return document, pin


def verify_call(
    loaded: tuple[BusinessCallPublication, str] | None,
    row: Mapping[str, Any],
    *,
    project_id: UUID,
    run_id: UUID,
    binding: IssueEvaluationBinding,
    as_of: datetime,
) -> dict[str, Any] | None:
    if loaded is None:
        return None
    publication, pin = loaded
    matches = [call for call in publication.calls if call.run_id == run_id]
    if len(matches) != 1:
        return None
    call = matches[0]
    result, invocation = row["result"], row["call"]
    if (
        call.project_id != project_id
        or str(call.invocation_id) != str(invocation["id"])
        or call.binding != binding
        or call.originals_digest != originals_digest(row)
        or not datetime.fromisoformat(invocation["created_at"])
        <= datetime.fromisoformat(result["created_at"])
        <= call.completed_at
        <= as_of
    ):
        return None
    return {
        "publication_id": str(publication.publication_id),
        "publication_sha256": pin,
        "invocation_id": str(call.invocation_id),
        "originals_digest": call.originals_digest,
        "provider_receipt_digest": call.provider_receipt_digest,
        "verified_by": str(publication.published_by),
        "verified_at": publication.published_at.isoformat(),
    }
