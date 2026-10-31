"""Inspect actual RLS source plans without exposing statement values or source contents."""

import time

from sqlalchemy import select, text

from pdos_next.enterprise_search.query import SearchInput, search
from pdos_next.enterprise_search.sources import catalog
from tests.enterprise_search.test_retrieval_pg import session_for


def test_native_source_planner_cost_and_warm_latency_without_jit(setup, record_property):
    with session_for(setup, personal=True) as session:
        from dataclasses import replace

        statement = select(catalog().c.source_type)
        compiled = statement.compile(dialect=setup.engine.dialect)
        plan = session.connection().exec_driver_sql(
            "EXPLAIN (FORMAT JSON, SETTINGS) " + str(compiled), compiled.params
        ).scalar_one()[0]
        record_property("authority_total_cost", plan["Plan"]["Total Cost"])
        record_property("authority_jit_planned", "JIT" in plan)
        session.execute(text("SET LOCAL jit=off"))
        times = []
        for _index in range(4):
            started = time.perf_counter()
            value = search(session, replace(setup.ctx, category_id=None), SearchInput(query="漏气"))
            times.append(time.perf_counter() - started)
            assert value["items"] == []
        record_property("without_jit_warm_max_seconds", max(times[1:]))
        assert max(times[1:]) < 1.0
