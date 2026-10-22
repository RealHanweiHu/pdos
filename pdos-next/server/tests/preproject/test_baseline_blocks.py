"""Pure definition/configuration/BOM adapter checks; no database connection."""

from types import SimpleNamespace as NS
from uuid import UUID

import pytest

from pdos_next.domain.configurations.models import BomRevision
from pdos_next.domain.preproject import baseline_blocks as blocks
from pdos_next.errors import DomainError

TENANT, CATEGORY, PRODUCT, DEFINITION, BOM = (UUID(int=i) for i in range(1, 6))
CTX = NS(tenant_id=TENANT, category_id=CATEGORY, actor_id=UUID(int=99), run_id=UUID(int=98))
VIEW = {"id": str(DEFINITION), "product_id": str(PRODUCT), "revision": 2}


class Session:
    def __init__(self, rows):
        self.rows = rows
        self.query = None

    def scalars(self, query):
        self.query = query
        return self.rows


def configuration(**changes):
    return NS(
        tenant_id=TENANT,
        product_id=PRODUCT,
        definition_id=DEFINITION,
        definition_revision=2,
        bom_id=BOM,
        bom_revision=3,
        id=UUID(int=6),
        **changes,
    )


@pytest.fixture
def guards(monkeypatch):
    calls = []

    def row(s, ctx, product, model, identity):
        calls.append((model.__name__, identity))
        assert product == PRODUCT and ctx is CTX
        return NS(revision=3) if model is BomRevision else NS(category_id=CATEGORY, revision=2)

    monkeypatch.setattr(blocks.configurations, "_row", row)
    monkeypatch.setattr(
        blocks.configurations,
        "_base_view",
        lambda *args: {"id": str(args[3].id), "revision": 1, "source_status": "current"},
    )
    monkeypatch.setattr(
        blocks.configurations,
        "_bom_view",
        lambda *args: {
            "id": str(BOM),
            "revision": 3,
            "source_status": "current",
            "sources": [{"artifact_id": str(UUID(int=20)), "expected_revision": 4}],
            "lines": [{"key": "part", "quantity": "0.123456789012", "unit": "kg"}],
        },
    )
    monkeypatch.setattr(
        blocks.configurations,
        "_human",
        lambda *a, **kw: pytest.fail("read must not require human mutation authority"),
    )
    return calls


def test_exact_binding_and_complete_bom_read_for_ai(guards):
    s = Session([configuration()])
    result = blocks.read_blocks(s, CTX, VIEW)
    item = result["bom"]["items"][0]
    assert item["bom_revision"] == 3
    assert item["definition_revision"] == 2
    assert item["bom"]["lines"][0]["quantity"] == "0.123456789012"
    assert item["bom"]["sources"][0]["expected_revision"] == 4
    params = s.query.compile().params
    assert set(params.values()) == {TENANT, PRODUCT, DEFINITION, 2}
    assert s.query._limit_clause is None
    assert guards == [("DefinitionRevision", DEFINITION), ("BomRevision", BOM)]
    for name in ("certification", "tooling"):
        assert result[name]["status"] == "unknown" and result[name]["items"] == []
    assert "platform" not in result


def test_multiple_bound_configurations_are_preserved_without_picking_latest(guards):
    rows = [configuration() for _ in range(205)]
    result = blocks.read_blocks(Session(rows), CTX, VIEW)
    assert len(result["bom"]["items"]) == 205


@pytest.mark.parametrize("code", ["FORBIDDEN_SCOPE", "SOURCE_UNAVAILABLE", "VERSION_CONFLICT"])
def test_source_guard_failure_hides_configuration_payload(guards, monkeypatch, code):
    def denied(*args):
        raise DomainError(code, "Private source")

    monkeypatch.setattr(blocks.configurations, "_bom_view", denied)
    result = blocks.read_blocks(Session([configuration()]), CTX, VIEW)
    assert result["bom"] == {
        "status": "unknown",
        "items": [],
        "reason": "definition_binding_unavailable",
        "unavailable_configuration_count": 1,
    }


def test_wrong_pinned_bom_revision_is_not_substituted(guards):
    row = configuration()
    row.bom_revision = 2
    result = blocks.read_blocks(Session([row]), CTX, VIEW)
    assert result["bom"]["items"] == []
    assert result["bom"]["unavailable_configuration_count"] == 1


def test_missing_binding_stays_unknown_and_does_not_lookup_arbitrary_bom(guards):
    result = blocks.read_blocks(Session([]), CTX, VIEW)
    assert result["bom"]["status"] == "unknown"
    assert guards == [("DefinitionRevision", DEFINITION)]


def test_stale_visible_configuration_is_explicit(guards, monkeypatch):
    monkeypatch.setattr(
        blocks.configurations,
        "_base_view",
        lambda *args: {"id": str(UUID(int=6)), "revision": 1, "source_status": "needs_recheck"},
    )
    result = blocks.read_blocks(Session([configuration()]), CTX, VIEW)
    assert result["bom"]["source_status"] == "needs_recheck"
