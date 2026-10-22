"""The actual three S1 entry documents must satisfy the declared working schema."""
# ruff: noqa: F811 -- explicitly imported marked PG fixtures

import pytest

from pdos_next.agent_kernel.context_projection import combine_contracts, project
from pdos_next.agent_kernel.skills import SkillCatalog
from tests.agent_kernel.test_proposal_context_pg import start
from tests.preproject.test_g0 import work as work
from tests.test_original_security import security_work as security_work


@pytest.mark.parametrize("entry", ["customer_request", "new_product", "derivative"])
def test_three_bound_entries_preserve_all_declared_working_context(work, security_work, entry):
    owner, scope = start(work, security_work, entry)
    catalog = SkillCatalog()
    schema = combine_contracts(catalog, [catalog.configuration("proposal_drafting")])
    raw = owner.project_context(
        scope, "Synthetic complete entry context", frozenset(schema["properties"]),
    )
    projected, omitted, issues = project(raw, schema)
    assert not omitted and not issues, (omitted, issues)
    assert projected == raw and projected["proposal"]["id"] == str(scope.proposal_id)
