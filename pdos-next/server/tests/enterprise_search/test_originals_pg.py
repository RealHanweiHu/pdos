"""Real local upload/parse with a synthetic scanner, then batch scan-proof retrieval."""
# ruff: noqa: F811 -- explicitly imported marked PG fixture

from dataclasses import replace

from pdos_next.original_security import configure
from tests.enterprise_search.test_retrieval_pg import index, query
from tests.test_original_security import parsed, uploaded
from tests.test_original_security import security_work as security_work


def test_uploaded_original_scan_epoch_and_current_configuration_are_rechecked(security_work):
    work, setup = security_work, security_work.setup
    original = uploaded(work, content="D16-01 气密性复验\n漏气处理：核对密封圈。\n".encode())
    artifact = parsed(work, original)
    calls = work.scanner.calls
    assert index(setup, artifact)["status"] == "ready"
    first = query(setup, "D16-01漏气怎么处理")
    assert first["returned"] == 1 and first["items"][0]["nature"] == "untrusted"
    assert first["items"][0]["customer_original"] is True
    assert first["items"][0]["locator"]["native"]
    assert work.scanner.calls == calls  # Reading performs no scan, parse or model call.
    configuration = replace(
        work.runtime.configuration,
        scanner=replace(work.runtime.configuration.scanner, rules_version="changed@2"),
    )
    configure(setup.engine, replace(work.runtime, configuration=configuration))
    changed = query(setup, "D16-01漏气怎么处理")
    assert changed["items"] == [] and changed["coverage"]["status"] == "partial"
    assert work.scanner.calls == calls
    configure(setup.engine, work.runtime)
    assert query(setup, "D16-01漏气怎么处理")["returned"] == 1
