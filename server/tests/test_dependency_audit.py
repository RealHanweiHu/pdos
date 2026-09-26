import json
from pathlib import Path
from typing import Any

import pytest

from scripts.audit_dependencies import (
    MAX_BATCH_SIZE,
    OSV_ENDPOINT,
    DependencyAuditError,
    LockedPackage,
    audit_locked_packages,
    collect_locked_packages,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_repository_lockfiles_produce_only_registry_package_versions() -> None:
    packages = collect_locked_packages(REPOSITORY_ROOT)

    assert packages
    assert LockedPackage("npm", "next", "16.3.3") in packages
    assert LockedPackage("PyPI", "cryptography", "50.0.0") in packages
    assert not any(package.name == "pdos-server" for package in packages)
    assert OSV_ENDPOINT == "https://api.osv.dev/v1/querybatch"


def test_audit_batches_minimal_queries_and_passes_empty_results() -> None:
    packages = tuple(
        LockedPackage("npm", f"package-{index}", "1.0.0") for index in range(MAX_BATCH_SIZE + 1)
    )
    payloads: list[dict[str, Any]] = []

    def transport(payload: bytes) -> bytes:
        document = json.loads(payload)
        payloads.append(document)
        return json.dumps({"results": [{} for _ in document["queries"]]}).encode()

    report = audit_locked_packages(packages, transport=transport)

    assert report.ready is True
    assert report.package_count == MAX_BATCH_SIZE + 1
    assert report.batch_count == 2
    assert [len(payload["queries"]) for payload in payloads] == [MAX_BATCH_SIZE, 1]
    assert set(payloads[0]) == {"queries"}
    first_query = payloads[0]["queries"][0]
    assert first_query == {
        "version": "1.0.0",
        "package": {"ecosystem": "npm", "name": "package-0"},
    }


def test_audit_fails_for_vulnerability_and_invalid_or_incomplete_response() -> None:
    package = LockedPackage("PyPI", "cryptography", "46.0.7")
    vulnerable = audit_locked_packages(
        (package,),
        transport=lambda _: b'{"results":[{"vulns":[{"id":"GHSA-example"}]}]}',
    )
    assert vulnerable.ready is False
    assert vulnerable.findings[0].package == package
    assert vulnerable.findings[0].vulnerability_id == "GHSA-example"

    for response in (b"not-json", b'{"results":[]}', b'{"results":[{"vulns":{}}]}'):

        def invalid_transport(_: bytes, value: bytes = response) -> bytes:
            return value

        with pytest.raises(DependencyAuditError, match="DEPENDENCY_AUDIT_RESPONSE_INVALID"):
            audit_locked_packages((package,), transport=invalid_transport)


def test_audit_propagates_network_failure_instead_of_skipping() -> None:
    package = LockedPackage("npm", "next", "16.3.3")

    def failed_transport(_: bytes) -> bytes:
        raise DependencyAuditError("DEPENDENCY_AUDIT_NETWORK_ERROR")

    with pytest.raises(DependencyAuditError, match="DEPENDENCY_AUDIT_NETWORK_ERROR"):
        audit_locked_packages((package,), transport=failed_transport)
