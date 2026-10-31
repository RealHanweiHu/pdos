"""Source search is a persisted object read, including an empty read set."""

from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest

from pdos_next.agent_kernel import domain_reads


@pytest.mark.parametrize("query,expected", [("", 2), ("pump", 1), ("missing", 0)])
def test_search_returns_an_object_and_only_checks_explicit_sources(monkeypatch, query, expected):
    sources = [
        SimpleNamespace(id=uuid4(), title=title, revision=3, content_hash="a" * 64)
        for title in ("Pump specification", "Motor specification")
    ]
    calls = []
    run = SimpleNamespace(
        read_sources=[
            {"artifact_id": str(source.id), "expected_revision": source.revision}
            for source in sources
        ]
    )
    scope = SimpleNamespace(category_id=uuid4(), product_id=None)

    @contextmanager
    def transaction(bound):
        assert bound is scope
        yield object(), run

    def source_for(session, ctx, product_id, identity, revision):
        calls.append((identity, revision))
        return next(source for source in sources if source.id == identity)

    monkeypatch.setattr(domain_reads, "source_for", source_for)
    reader = domain_reads.DomainReads(
        SimpleNamespace(transaction=transaction), SimpleNamespace(context=lambda _: object())
    )
    result = reader.call(scope, {"query": query}, name="evidence.search")
    assert isinstance(result, dict)
    assert len(result["items"]) == expected
    assert calls == [(source.id, source.revision) for source in sources]
    run.read_sources = []
    assert reader.call(scope, {}, name="evidence.search") == {"items": []}
