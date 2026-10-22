"""New combination checks, not source/professional or SQL acceptance evidence."""

import ast
import inspect
from pathlib import Path
from types import SimpleNamespace

import httpx
import psycopg
import pytest
from sqlalchemy import ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.engine import Engine

from pdos_next import command_handlers as registry
from pdos_next import contracts, lifecycle_catalog, models
from pdos_next import service as common

SERVER = Path(__file__).resolve().parents[2]
OPS = (
    ("change.order.prepare", "T1", "change.order_prepared"),
    ("change.order.approve", "T2", "change.approved"),
    ("change.implementation.record", "T1", "change.implementation_recorded"),
    ("change.selection.decide", "T2", "change.selection_decided"),
    ("npi.work_instruction.record", "T1", "work_instruction.recorded"),
    ("npi.control_plan.record", "T1", "control_plan.recorded"),
    ("npi.manufacturing_baseline.record", "T1", "manufacturing_baseline.recorded"),
)


@pytest.fixture(autouse=True)
def no_connections(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("This scope must not connect to a database or HTTP")

    monkeypatch.setattr(Engine, "connect", forbidden)
    monkeypatch.setattr(Engine, "raw_connection", forbidden)
    monkeypatch.setattr(psycopg, "connect", forbidden)
    monkeypatch.setattr(httpx.Client, "request", forbidden)


@pytest.mark.parametrize("operation,tier,event", OPS)
def test_real_combined_handler_has_correct_tier_event_and_common_callback_signature(
    operation, tier, event
):
    module = registry.handler(operation)
    assert contracts.PAYLOADS[operation]
    assert operation in registry.PHASED_MATERIAL_OPERATIONS
    assert operation in registry.LIVE_CONSUMPTION_OPERATIONS
    assert (operation in registry.T2_OPERATIONS) == (tier == "T2")
    assert (operation in registry.T1_OPERATIONS) == (tier == "T1")
    assert common.EVENTS[operation] == event
    for name, args in (
        ("prepare_preview", (None,) * 5),
        ("preview_prepared", (None,) * 6),
        ("prepare_write_review", (None,) * 5),
        ("bind_consumption", (None,) * 7),
        ("record_consumption", (None,) * 8),
    ):
        inspect.signature(getattr(module, name)).bind(*args)
    inspect.signature(module.apply_prepared_write).bind(*((None,) * 6), consumption=(None, None))


def test_both_trusted_startups_preserve_the_other_family_and_grant_nothing():
    from pdos_next import change_public_integration
    from pdos_next.domain.manufacturing_baseline import service as manufacturing

    engine = SimpleNamespace()
    manufacturing.configure(engine)
    before = engine._pdos_manufacturing_preparation_consumption
    assert change_public_integration.configure(engine) is None
    assert engine._pdos_manufacturing_preparation_consumption is before
    assert set(before.modules) == {op for op, _, _ in OPS if op.startswith("npi.")}
    assert set(engine._pdos_change_order_consumer.consumption.modules) == {
        "change.order.prepare",
        "change.order.approve",
        "change.implementation.record",
        "change.effectivity.record",
        "change.verification.record",
        "change.close",
    }
    assert not hasattr(engine, "_pdos_professional_issuers")
    assert not hasattr(engine, "_pdos_quality_followup")
    assert "change.policy.import" not in contracts.PAYLOADS
    assert registry.handler("change.policy.import") is None
    assert callable(registry.handler("npi.pilot.create").validate)


def test_actual_models_have_complete_lifecycle_and_exact_fk_parent_keys():
    assert "change_dependency_clocks" in models.Base.metadata.tables
    assert set(models.Base.metadata.tables) == set(lifecycle_catalog.COVERED_COLUMNS)
    for name, table in models.Base.metadata.tables.items():
        # Added migration columns have a different physical order from inheritance.
        assert set(table.columns.keys()) == set(lifecycle_catalog.COVERED_COLUMNS[name])
    new = {
        "manufacturing_preparation_versions",
        "manufacturing_preparation_currents",
        "manufacturing_baseline_document_links",
        "change_order_records",
        "change_approval_records",
        "change_implementation_captures",
        "change_implementation_records",
        "controlled_change_policy_facts",
        "controlled_change_policy_currents",
        "controlled_change_selection_facts",
        "controlled_change_selection_currents",
    }
    # Actual ORM table names are read, not inferred from a design label.
    assert new <= set(models.Base.metadata.tables)
    assert new <= set(lifecycle_catalog.GUARDED)
    for name in new:
        for fk in models.Base.metadata.tables[name].constraints:
            if isinstance(fk, ForeignKeyConstraint):
                parent = fk.elements[0].column.table
                refs = tuple(e.column.name for e in fk.elements)
                assert refs in (
                    tuple(parent.primary_key.columns.keys()),
                    *(
                        tuple(c.columns.keys())
                        for c in parent.constraints
                        if isinstance(c, UniqueConstraint)
                    ),
                ), (name, parent.name, refs)


def test_real_root_plan_preview_and_fact_first_flush_survive_both_hunks():
    raw = (SERVER / "pdos_next/service.py").read_text()
    tree = ast.parse(raw)
    preview = next(n for n in tree.body if getattr(n, "name", None) == "preview_command")
    preview_text = ast.get_source_segment(raw, preview)
    assert 'elif command.operation == "test.run.plan":' in preview_text
    assert "snapshot = preview_once(s, ctx, command, product, payload)" in preview_text
    assert '"change.selection.decide",\n' in raw
    assert "s.flush([subject])" in raw
    assert '"quality.capa.observation.record",\n' in raw
    assert '"quality.capa.verification.review",\n' in raw
