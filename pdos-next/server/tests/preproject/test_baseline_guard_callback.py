"""Candidate authorization before baseline body projection; pure fixture only.

During Phase8 preparation the coordinator installs its private draft under the
actual module name in a one-process importlib harness before collecting this file.
"""
# ruff: noqa: F811 -- reuse the existing pure baseline fixture.

from copy import deepcopy
from types import SimpleNamespace as NS
from uuid import UUID

import pytest
from sqlalchemy.dialects import postgresql

from pdos_next.domain.preproject import baseline
from pdos_next.errors import DomainError
from tests.preproject.test_baseline import PRODUCT, Session
from tests.preproject.test_baseline import fixture as fixture  # noqa: F401


def read(fixture, rows, **kwargs):
    return baseline.read_baseline(Session(rows), fixture.ctx, PRODUCT, **kwargs)


def test_published_receipt_and_human_precede_guard_then_body_without_reading_later_draft(
    fixture,
    monkeypatch,
):
    later = NS(**vars(fixture.definition))
    later.id, later.revision, later.status = UUID(int=99), 2, "draft"
    later.sealed, later.g0_decision_id = False, None
    session = Session(
        [fixture.product, [later, fixture.definition], fixture.receipt, fixture.signer]
    )
    calls = []

    def guard(row):
        assert row is fixture.definition
        assert session.rows == []  # Actual receipt and named Human already read.
        calls.append("guard")

    def body(s, ctx, row):
        assert row is fixture.definition
        assert calls == ["guard"]
        calls.append("body")
        return deepcopy(fixture.document)

    monkeypatch.setattr(baseline, "definition_view", body)
    result = baseline.read_baseline(
        session,
        fixture.ctx,
        PRODUCT,
        before_definition_read=guard,
    )
    assert calls == ["guard", "body"]
    assert result["baseline_kind"] == "published"
    assert (
        result["definition"]["publication"]["definition_digest"]
        == (fixture.receipt.result["definition_digest"])
    )
    query = str(session.queries[1].compile(dialect=postgresql.dialect()))
    projection = query.split("FROM", 1)[0]
    assert set(
        part.strip().split(".")[-1] for part in projection.removeprefix("SELECT ").split(",")
    ) == {
        "id",
        "tenant_id",
        "category_id",
        "product_id",
        "variant_id",
        "revision",
        "status",
        "sealed",
        "g0_decision_id",
        "publication_receipt_id",
    }


@pytest.mark.parametrize("code", ["FORBIDDEN_SCOPE", "SOURCE_UNAVAILABLE", "VERSION_CONFLICT"])
def test_callback_denial_propagates_original_error_and_never_falls_back(fixture, monkeypatch, code):
    fallback = NS(**vars(fixture.definition))
    fallback.id, fallback.status, fallback.sealed = UUID(int=98), "draft", False
    denied = DomainError(code, "Synthetic private-read rejection", 403)
    calls = []

    def guard(row):
        calls.append(row.id)
        raise denied

    def forbidden_body(*args):
        pytest.fail("Denied candidate must not load its body or choose the fallback")

    monkeypatch.setattr(baseline, "definition_view", forbidden_body)
    with pytest.raises(DomainError) as error:
        read(
            fixture,
            [fixture.product, [fallback, fixture.definition], fixture.receipt, fixture.signer],
            before_definition_read=guard,
        )
    assert error.value is denied
    assert calls == [fixture.definition.id]


@pytest.mark.parametrize("kind", ["g0", "draft"])
def test_g0_and_draft_guard_precede_body(fixture, monkeypatch, kind):
    fixture.definition.status = "draft"
    fixture.definition.sealed = kind == "g0"
    fixture.definition.g0_decision_id = UUID(int=90) if kind == "g0" else None
    calls = []

    def body(*args):
        assert calls == [fixture.definition.id]
        calls.append("body")
        return deepcopy(fixture.document)

    monkeypatch.setattr(baseline, "definition_view", body)
    result = read(
        fixture,
        [fixture.product, [fixture.definition]],
        before_definition_read=lambda row: calls.append(row.id),
    )
    assert result["baseline_kind"] == kind
    assert calls == [fixture.definition.id, "body"]


@pytest.mark.parametrize("invalid", ["receipt", "signer"])
def test_invalid_publication_metadata_never_reaches_guard_or_body(fixture, monkeypatch, invalid):
    if invalid == "receipt":
        fixture.receipt.actor_id = UUID(int=93)
    else:
        fixture.signer.kind = "agent"

    def forbidden(*args):
        pytest.fail("Invalid publication metadata must precede any body authorization")

    monkeypatch.setattr(baseline, "definition_view", forbidden)
    result = read(
        fixture,
        [fixture.product, [fixture.definition], fixture.receipt, fixture.signer],
        before_definition_read=forbidden,
    )
    assert result["definition"] is None
    assert result["unavailable_definition_count"] == 1


def test_excluded_blocks_skip_all_block_reads_and_retain_explicit_unknown(fixture, monkeypatch):
    def forbidden(*args):
        pytest.fail("Comparison opted out of unrelated block reads")

    monkeypatch.setattr(baseline, "read_blocks", forbidden)
    result = read(
        fixture,
        [fixture.product, [fixture.definition], fixture.receipt, fixture.signer],
        before_definition_read=lambda row: None,
        include_blocks=False,
    )
    assert result["baseline_kind"] == "published"
    assert set(result["blocks"]) == {"bom", "certification", "tooling", "platform"}
    assert set(result["unavailable_blocks"]) == set(result["blocks"])
    assert all(
        block["status"] == "unknown" and block["items"] == [] for block in result["blocks"].values()
    )


@pytest.mark.parametrize("bound", [False, True])
def test_only_trusted_current_source_proof_replaces_legacy_traversal(fixture, monkeypatch, bound):
    checks = []

    def legacy(_s, _ctx, candidate, **options):
        checks.append(options.get("history_permissions", False))
        assert candidate["id"] == str(fixture.definition.id)

    def current(candidate):
        assert candidate["publication"]["definition_digest"] == fixture.receipt.result[
            "definition_digest"
        ]
        return bound

    monkeypatch.setattr(baseline, "validate_sources", legacy)
    result = read(fixture, [fixture.product, [fixture.definition], fixture.receipt, fixture.signer],
                  sources_current=current)
    assert result["derivation_eligible"]
    assert checks == ([] if bound else [True, False])
