"""Answer citation selection cannot trim the server's actual dependency footprint."""
# ruff: noqa: F811 -- reuse the existing pure source fixture

from copy import deepcopy
from uuid import uuid4

import pytest
from pdos_next.domain.knowledge import assistant_sources as sources
from pdos_next.errors import DomainError
from tests.knowledge.test_assistant_knowledge import source  # noqa: F401


def add_uncited(source, monkeypatch, **changes):
    _ctx, _session, run, ref, actual = source
    cid = run.result["result"]["assistant"]["citation_ids"][0]
    other_cid = str(uuid4())
    extra = {**ref, "source_id": str(uuid4()), "content_hash": "b" * 64}
    rows = {cid: actual, other_cid: {**actual, **extra, **changes}}
    fixed = {cid: ref, other_cid: extra}
    monkeypatch.setattr(sources, "checked_sources", lambda *_: rows)
    monkeypatch.setattr(sources.ledger, "carried", lambda *_: (fixed, set()))
    return extra, rows, fixed


@pytest.mark.parametrize("flags", [{"private": True}, {"customer_original": True}, {}])
def test_uncited_actual_read_is_pinned_and_classified_without_fabricating_a_quote(
    source,
    monkeypatch,
    flags,
):
    ctx, session, run, ref, _actual = source
    before = deepcopy(run.result)
    extra, _rows, _fixed = add_uncited(source, monkeypatch, **flags)
    value = sources.capture(session, ctx, run.id)
    assert value["source_proof"] == sorted([ref, extra], key=lambda item: item["source_id"])
    assert [item["id"] for item in value["artifacts"]] == [ref["source_id"]]
    assert value["private"] == bool(flags.get("private"))
    assert value["customer_original"] == bool(flags.get("customer_original"))
    assert run.private_context is False and run.result == before


@pytest.mark.parametrize("change", ["category", "fixed_body", "digest", "version"])
def test_uncited_unavailable_or_changed_dependency_cannot_be_filtered_from_the_save(
    source,
    monkeypatch,
    change,
):
    ctx, session, run, _ref, _actual = source
    _extra, rows, _fixed = add_uncited(source, monkeypatch)
    extra = list(rows.values())[1]
    if change == "category":
        extra["category_id"] = str(uuid4())
    elif change == "fixed_body":
        extra["fixed_body_available"] = False
    elif change == "digest":
        extra["content_hash"] = "c" * 64
    else:
        extra["source_revision"] = 2
    with pytest.raises(DomainError):
        sources.capture(session, ctx, run.id)


def test_conflicting_carried_versions_fail_instead_of_last_write_winning(source, monkeypatch):
    ctx, session, run, ref, _actual = source
    _extra, rows, fixed = add_uncited(source, monkeypatch)
    cid = list(fixed)[1]
    fixed[cid].update(source_id=ref["source_id"], source_revision=2)
    rows[cid].update(source_id=ref["source_id"], source_revision=2)
    with pytest.raises(DomainError, match="不同固定版本"):
        sources.capture(session, ctx, run.id)


def test_uncited_footprint_changes_the_digest_but_unchanged_replay_is_stable(source, monkeypatch):
    ctx, session, run, _ref, _actual = source
    original = sources.capture(session, ctx, run.id)
    add_uncited(source, monkeypatch)
    current = sources.capture(session, ctx, run.id)
    assert current["answer_digest"] != original["answer_digest"]
    assert (
        sources.capture(session, ctx, run.id, expected_digest=current["answer_digest"]) == current
    )
    with pytest.raises(DomainError):
        sources.capture(session, ctx, run.id, expected_digest=original["answer_digest"])
