"""Generated authority SQL must survive PostgreSQL's identifier length limit."""

import re

import pytest
from pdos_next.enterprise_search.schemas import SOURCE_TYPES
from pdos_next.enterprise_search.sources import retrieval_catalog
from sqlalchemy import select
from sqlalchemy.dialects import postgresql


@pytest.mark.parametrize("families", [SOURCE_TYPES, ("knowledge",), ("artifact", "knowledge")])
def test_nested_authority_ctes_have_distinct_postgresql_identifiers(families):
    relation = retrieval_catalog(families)
    sql = str(select(relation).compile(dialect=postgresql.dialect()))
    names = re.findall(r"(?:^WITH |^)([a-z][a-z0-9_]*) AS\s*\(", sql, re.MULTILINE)
    assert names
    encoded = [name.encode("utf-8") for name in names]
    assert all(len(name) <= 63 for name in encoded)
    assert len({name[:63] for name in encoded}) == len(encoded)
