import time
import pytest
from sqlalchemy import event

samples=[]
@pytest.hookimpl(hookwrapper=True)
def pytest_fixture_setup(fixturedef, request):
    outcome=yield
    if fixturedef.argname!='setup':
        return
    setup=outcome.get_result()
    engine=getattr(setup,'engine',None)
    if engine is None:
        return
    def before(conn,cursor,statement,parameters,context,executemany):
        context._pdos_query_profile_start=time.perf_counter()
    def after(conn,cursor,statement,parameters,context,executemany):
        if 'readable_keyword_matches' in statement or 'enterprise_index_health' in statement or statement=='SET LOCAL jit=off':
            tag='page_health' if 'enterprise_index_health' in statement else 'dependencies' if 'readable_keyword_matches' in statement else 'set_jit'
            samples.append((tag,time.perf_counter()-context._pdos_query_profile_start,len(statement)))
    event.listen(engine,'before_cursor_execute',before)
    event.listen(engine,'after_cursor_execute',after)
    def clean():
        event.remove(engine,'before_cursor_execute',before)
        event.remove(engine,'after_cursor_execute',after)
    request.addfinalizer(clean)

def pytest_terminal_summary(terminalreporter):
    import json,statistics
    for tag in ('set_jit','dependencies','page_health'):
        rows=[r for r in samples if r[0]==tag]
        if rows:
            terminalreporter.write_line('SQL_PROFILE '+json.dumps({'tag':tag,'samples':len(rows),'median_seconds':statistics.median(r[1] for r in rows),'max_seconds':max(r[1] for r in rows),'sql_chars':max(r[2] for r in rows)}))
