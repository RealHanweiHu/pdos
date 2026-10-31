"""Offline D source wiring; actual native facts/permissions are checked in PG cases."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from pdos_next.agent_kernel.disclosure import disclosure
from pdos_next.agent_kernel.tools import default_registry
from pdos_next.domain.field_feedback.models import EVENTS
from pdos_next.enterprise_search import business_events
from pdos_next.enterprise_search.action_sources import _source_roots
from pdos_next.enterprise_search.presence import MODELS
from pdos_next.enterprise_search.relations import edges
from pdos_next.enterprise_search.schemas import SOURCE_TYPES, SearchInput
from pdos_next.enterprise_search.sources import catalog, identity_keys
from sqlalchemy import select
from sqlalchemy.dialects import postgresql


def test_registered_generic_search_accepts_native_field_without_an_extra_tool():
    value = SearchInput(query="D16-01", source_types=["field_feedback"])
    assert value.source_types == ["field_feedback"] and len(SOURCE_TYPES) == 13
    registry = default_registry()
    assert len(disclosure(registry)) == 61
    assert not any(spec.tier == "READ" and name.startswith("field.")
                   for name, spec in registry._specs.items())
    assert set(EVENTS.values()) <= business_events.EVENTS
    assert {model.__tablename__ for model in MODELS["field_feedback"]} == {
        "field_feedback_versions", "field_response_records",
    }


def test_field_projector_keeps_untrusted_intake_and_structured_performed_facts_distinct():
    branches = catalog(["field_feedback"]).element.selects
    assert len(branches) == 2
    assert [query.selected_columns.nature.element.value for query in branches] == [
        "untrusted", "structured",
    ]
    sql = str(select(catalog(["field_feedback"])).compile(dialect=postgresql.dialect()))
    assert "LEFT OUTER JOIN shared_enterprise_projects" in sql
    assert "LEFT OUTER JOIN shared_enterprise_products" in sql
    assert "source_basis" in sql and "field_feedback_currents" in sql
    assert "feedback_version_id" in sql and "feedback_revision" in sql
    # Identity lookup is deliberately a cheap superset, not another permission query.
    identity = str(identity_keys(["field_feedback"], uuid4()).compile(dialect=postgresql.dialect()))
    assert "field_feedback_versions.feedback_id" in identity
    assert "field_response_records.feedback_id" in identity


def test_existing_action_audience_port_follows_the_retained_parent_basis_not_only_direct_reads():
    tenant, category, owner, response, original = [uuid4() for _ in range(5)]
    ctx = SimpleNamespace(tenant_id=tenant, category_id=category, requester_id=owner)
    rows = {
        ("field_response_records", response): {
            "id": response, "category_id": category, "owner_id": owner,
            "visibility": "private", "reads": [],
            "source_basis": {"artifacts": [{"id": str(original), "revision": 1}]},
        },
        ("artifact_versions", original): {
            "id": original, "category_id": category, "owner_id": owner, "visibility": "private",
        },
    }

    class Rows:
        def execute(self, query):
            table = query.get_final_froms()[0].name
            identity = next(value for value in query.compile().params.values()
                            if value in {response, original})
            self.value = rows.get((table, identity))
            return self

        def mappings(self):
            return self

        def one_or_none(self):
            return self.value

    assert _source_roots(Rows(), ctx, "field_feedback", response) == {
        ("field_response_records", str(response), str(owner)),
        ("artifact_versions", str(original), str(owner)),
    }


@pytest.mark.parametrize("kinds", [SOURCE_TYPES, ("field_feedback",), ("change", "field_feedback")])
def test_one_hop_uses_registered_field_version_references(kinds):
    query = edges(set(kinds), {("field_feedback", uuid4())})
    sql = str(select(query).compile(dialect=postgresql.dialect()))
    assert "field_response_records" in sql
    assert "feedback_version_id" in sql and "feedback_revision" in sql
    if "change" in kinds:
        assert "registered_field_change_refs" in sql
    if "build" in kinds:
        assert "build_lots" in sql
