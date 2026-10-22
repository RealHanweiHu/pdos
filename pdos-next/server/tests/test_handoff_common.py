"""The existing formal request reader accepts handoff history but no future execution."""

from types import SimpleNamespace

import pytest
from verification_handoff.test_pure import offered, work  # noqa: F401

from pdos_next.domain.verification_front.service import _snapshot, professional_key
from pdos_next.error_catalog import REASONS
from pdos_next.errors import DomainError
from pdos_next.schemas.verification.contracts import DocumentRequirement
from pdos_next.service import digest


def row_for(request):
    return SimpleNamespace(
        request_snapshot=request.model_dump(mode="json"),
        snapshot_sha256=digest(request.model_dump(mode="json")),
        request_id=request.id,
        revision=request.revision,
        tenant_id=request.scope.tenant_id,
        product_id=request.scope.product_id,
        project_id=request.scope.project_id,
        build_id=request.build.id,
        build_revision=request.build.revision,
        status=request.status,
        operation="verification.request.create"
        if request.status == "draft"
        else "verification.handoff.offer",
    )


def documented(request):
    return request.model_copy(
        update={
            "documents": tuple(
                DocumentRequirement(
                    id=professional_key(item.id),
                    title="Original scoped professional review",
                    item_ids=(item.id,),
                    required=True,
                )
                for item in request.items
            )
        }
    )


def test_original_formal_reader_keeps_draft_and_exact_handoff_clocks(work):  # noqa: F811
    draft = documented(work.request)
    assert _snapshot(row_for(draft)) == draft
    actual = documented(offered(work))
    loaded = _snapshot(row_for(actual))
    assert loaded == actual and loaded.timeline.offered is not None
    assert loaded.timeline.accepted is None and loaded.timeline.actual_start is None
    assert _snapshot(row_for(draft)) == draft


@pytest.mark.parametrize(
    "name", ["promised_start", "actual_start", "preliminary_result", "final_result", "disposed"]
)
def test_formal_handoff_cannot_smuggle_a_future_execution_clock(work, name):  # noqa: F811
    request = documented(offered(work))
    forged = request.model_copy(
        update={"timeline": request.timeline.model_copy(update={name: request.timeline.offered})}
    )
    with pytest.raises(DomainError) as error:
        _snapshot(row_for(forged))
    assert error.value.reason == "INTEGRITY_MISMATCH"
    assert error.value.code == REASONS["INTEGRITY_MISMATCH"]


def test_draft_cannot_hide_actual_sample_or_offer_history(work):  # noqa: F811
    request = documented(offered(work)).model_copy(update={"status": "draft"})
    with pytest.raises(DomainError) as error:
        _snapshot(row_for(request))
    assert error.value.reason == "INTEGRITY_MISMATCH"
    assert error.value.code == REASONS["INTEGRITY_MISMATCH"]
