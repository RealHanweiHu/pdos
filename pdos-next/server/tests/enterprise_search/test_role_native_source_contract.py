"""Offline contracts at genuine catalog/event/schema and migration boundaries."""

from importlib import import_module
from uuid import uuid4

import pytest
from pdos_next.agent_kernel.disclosure import disclosure
from pdos_next.agent_kernel.tools import default_registry
from pdos_next.enterprise_search import business_events
from pdos_next.enterprise_search.presence import MODELS
from pdos_next.enterprise_search.relations import edges
from pdos_next.enterprise_search.role_native_audience import PARENT_FIELDS
from pdos_next.enterprise_search.role_native_events import OPERATIONS
from pdos_next.enterprise_search.role_native_sources import FAMILIES
from pdos_next.enterprise_search.schemas import SOURCE_TYPES, SearchInput
from pdos_next.enterprise_search.sources import catalog, identity_keys
from pdos_next.service import EVENTS
from sqlalchemy import select
from sqlalchemy.dialects import postgresql


def sql(value):
    return str(value.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def test_native_role_records_use_generic_sources_and_full_tool_disclosure():
    assert len(SOURCE_TYPES) == 13 and FAMILIES <= set(SOURCE_TYPES)
    assert SearchInput(query="fixed record", source_types=sorted(FAMILIES)).source_types
    assert len(disclosure(default_registry())) == 61
    assert {EVENTS[name] for name in OPERATIONS} <= business_events.EVENTS
    assert {model.__tablename__ for model in MODELS["manufacturing_document"]} == {
        "manufacturing_preparation_versions",
        "manufacturing_publication_documents",
    }


@pytest.mark.parametrize("kind", sorted(FAMILIES))
def test_family_and_cheap_identity_compile_in_actual_ordinary_rls_catalog(kind):
    query = sql(select(catalog([kind])))
    assert "shared_enterprise_projects" in query and "shared_enterprise_products" in query
    assert "source_revision" in query and "read_basis_status" in query
    identity = sql(identity_keys([kind], uuid4()))
    assert "source_id" in identity and "source_type" in identity
    assert "jsonb_build_object" not in identity


def test_publication_identity_and_current_pointers_remain_native():
    statement = sql(select(catalog(["manufacturing_document"])))
    assert "manufacturing_preparation_currents" in statement
    assert "manufacturing_publication_currents" in statement
    assert "publication_revision AS source_revision" in statement
    assert "document_revision" in statement and "document_kind" in statement
    assert "manufacturing_baseline_publications" in statement
    assert "仅为原生制造草稿" in statement and "该正式发布固定引用此文档版本" in statement
    assert "source_refs" in statement and "not_evaluated" in statement
    from pdos_next.domain.manufacturing_baseline.models import PreparationVersion
    from pdos_next.enterprise_search.role_native_sources import document_facts

    projected = sql(document_facts(PreparationVersion))
    for forbidden in ("input_snapshot", "kernel_event", "command_sha256"):
        assert forbidden not in projected
    assert PARENT_FIELDS["manufacturing_publication_documents"] == (
        ("publication_id", "manufacturing_baseline_publications"),
        ("document_id", "manufacturing_preparation_versions"),
    )


def test_relations_follow_only_actual_predecessor_publication_and_build_fks():
    query = sql(
        select(
            edges(
                set(SOURCE_TYPES),
                {
                    ("manufacturing_document", uuid4()),
                    ("verification_handoff", uuid4()),
                },
            )
        )
    )
    for required in (
        "previous_revision",
        "document_revision",
        "publication_id",
        "next_request_version_id",
        "next_request_revision",
        "build_revision",
    ):
        assert required in query
    assert "document_previous" in query and "handoff_build" in query
    status = sql(select(edges({"project_status"}, {("project_status", uuid4())})))
    assert "project_status_updates" not in status


def test_function_pins_extend_current_bodies_without_policy_or_role_changes():
    candidate = import_module("migrations.candidates.role_native_sources")
    old_resolver = import_module("migrations.schema_s0_0844")
    old_visibility = import_module("migrations.schema_s0_0845")
    old_clear = import_module("migrations.schema_s0_0846")
    resolver = "assistant_source_lifecycle_links(uuid,uuid,jsonb)"
    visible = "knowledge_answer_sources_visible(uuid,uuid,jsonb)"
    clear = old_clear.SIGNATURE
    assert candidate.PREVIOUS_FUNCTIONS[resolver] == old_resolver.SCHEMA_SQL[0]
    assert candidate.PREVIOUS_FUNCTIONS[visible] == old_visibility.NATIVE_FUNCTIONS[visible]
    assert candidate.PREVIOUS_FUNCTIONS[clear] == old_clear.NATIVE_FUNCTIONS[clear]
    for kind in FAMILIES:
        assert f"'{kind}'" in candidate.NATIVE_FUNCTIONS[resolver]
        assert f"WHEN '{kind}'" in candidate.NATIVE_FUNCTIONS[visible]
        assert f"'{kind}'" in candidate.NATIVE_FUNCTIONS[clear]
    for body in candidate.SCHEMA_SQL:
        assert body.startswith("CREATE OR REPLACE FUNCTION public.")
        assert "CREATE POLICY" not in body and "GRANT " not in body and "ALTER OWNER" not in body
    assert "SECURITY DEFINER" in candidate.NATIVE_FUNCTIONS[resolver]
    assert "SECURITY DEFINER" in candidate.NATIVE_FUNCTIONS[clear]
    assert "SECURITY INVOKER" in candidate.NATIVE_FUNCTIONS[visible]
    assert (
        "Fixed assistant source dependencies must be an array"
        in candidate.NATIVE_FUNCTIONS[resolver]
    )
