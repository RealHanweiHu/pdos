"""P76 item 4a: a tool the run's scope always rejects is neither disclosed nor callable."""

from types import SimpleNamespace

import pytest

from pdos_next.agent.kernel.disclosure import disclosed_names, disclosure_digest
from pdos_next.agent.kernel.tools import default_registry
from pdos_next.errors import DomainError

PROJECT_READS = {"build.read", "build.lot.read", "build.sample.read", "quality.issue.read",
                 "test.run.read"}


def scope(**bound):
    values = {"category_id": None, "product_id": None, "project_id": None, "proposal_id": None,
              "isolation": "main", "private_context": False, **bound}
    return SimpleNamespace(**values)


def test_category_scope_hides_project_reads_and_project_scope_keeps_them():
    registry = default_registry()
    category = set(disclosed_names(registry, scope=scope(category_id=1)))
    project = set(disclosed_names(registry, scope=scope(category_id=1, product_id=2, project_id=3)))
    assert not PROJECT_READS & category
    assert PROJECT_READS <= project
    assert project - category == PROJECT_READS


def test_same_scope_gives_the_same_digest_and_a_different_scope_does_not():
    registry, bound = default_registry(), scope(category_id=1)
    assert disclosure_digest(registry, scope=bound) == disclosure_digest(registry, scope=bound)
    project = scope(category_id=1, product_id=2, project_id=3)
    assert disclosure_digest(registry, scope=bound) != disclosure_digest(registry, scope=project)


@pytest.mark.parametrize("name", sorted(PROJECT_READS))
def test_authorization_refuses_a_project_read_outside_a_project(name):
    with pytest.raises(DomainError) as refused:
        default_registry().authorize(scope(category_id=1), name, {}, {}, lambda *_: True)
    assert refused.value.code == "FORBIDDEN_SCOPE"
    assert refused.value.detail["reason_key"] == "tool_scope_required"
