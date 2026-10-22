"""Actual Current ORM and scoped Select, with an explicit connection-free SQL substitute."""

from contextlib import nullcontext
from uuid import uuid4

from pdos_next import change_controlled_owner as owner
from pdos_next.domain.quality_execution.models import QualityIssueCurrent
from pdos_next.schemas.verification.contracts import Scope
from pdos_next.service import Context


class ReadOnlySession:
    def __init__(self, row):
        self.row = row
        self.queries = []
        self.no_autoflush = nullcontext()

    def scalars(self, query):
        self.queries.append(query)
        return iter((self.row,))


def test_current_issue_revision_reads_real_pointer_field_in_exact_scope():
    scope = Scope(tenant_id=uuid4(), product_id=uuid4(), project_id=uuid4())
    actor, issue_id = uuid4(), uuid4()
    ctx = Context(scope.tenant_id, actor, actor, category_id=uuid4())
    pointer = QualityIssueCurrent(
        id=uuid4(),
        tenant_id=scope.tenant_id,
        category_id=ctx.category_id,
        product_id=scope.product_id,
        project_id=scope.project_id,
        issue_id=issue_id,
        issue_version_id=uuid4(),
        issue_revision=7,
        epoch=23,
    )
    assert not hasattr(pointer, "revision")
    session = ReadOnlySession(pointer)

    assert owner._current_issue_revision(session, ctx, scope.product_id, scope, issue_id) == 7

    assert len(session.queries) == 1
    query = session.queries[0]
    assert query.column_descriptions[0]["entity"] is QualityIssueCurrent
    assert {clause.left.name: clause.right.value for clause in query._where_criteria} == {
        "tenant_id": scope.tenant_id,
        "product_id": scope.product_id,
        "project_id": scope.project_id,
        "issue_id": issue_id,
    }
