"""Pure saved-Issue reading: actual DTO/ORM, without DB or permission-grant claims."""

import pytest
from quality_issues.helpers import uid

from pdos_next.domain.quality_execution.models import QualityIssueVersion
from pdos_next.domain.quality_followup import service
from pdos_next.errors import DomainError
from pdos_next.schemas.quality_issues.contracts import Issue
from pdos_next.service import digest
from quality_followup.test_pure import issue


def fixed_row(visibility="category", audience=None):
    category, owner = uid("followup-category"), uid("executor")
    saved = Issue.model_validate(
        {
            **issue().model_dump(mode="json"),
            "audience": audience
            or (f"private:{owner}" if visibility == "private" else f"category:{category}",),
        }
    )
    row = QualityIssueVersion(
        id=uid("followup-version"),
        tenant_id=saved.scope.tenant_id,
        category_id=category,
        product_id=saved.scope.product_id,
        project_id=saved.scope.project_id,
        issue_id=saved.id,
        revision=saved.revision,
        owner_id=owner,
        visibility=visibility,
        status=saved.status,
        issue_snapshot=saved.model_dump(mode="json"),
        snapshot_sha256=digest(saved.model_dump(mode="json")),
    )
    return row, saved


@pytest.mark.parametrize("visibility", ["category", "audience", "private"])
def test_saved_issue_uses_its_actual_category_or_private_owner(visibility):
    row, saved = fixed_row(visibility)
    assert service._snapshot(row) == saved


@pytest.mark.parametrize(
    "audience",
    [(f"product:{uid('product')}",), (f"category:{uid('other-category')}",)],
)
def test_shared_issue_rejects_product_audience_and_another_category(audience):
    row, _ = fixed_row(audience=audience)
    with pytest.raises(DomainError) as failure:
        service._snapshot(row)
    assert failure.value.reason == "INTEGRITY_MISMATCH"


def test_private_issue_cannot_be_read_as_category_shared():
    row, _ = fixed_row("private", audience=(f"category:{uid('followup-category')}",))
    with pytest.raises(DomainError) as failure:
        service._snapshot(row)
    assert failure.value.reason == "INTEGRITY_MISMATCH"
