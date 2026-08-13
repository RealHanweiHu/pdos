"""Fail-closed OSV audit for the repository's npm and PyPI lockfiles."""

from __future__ import annotations

import argparse
import http.client
import json
import ssl
import tomllib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

OSV_ENDPOINT = "https://api.osv.dev/v1/querybatch"
OSV_HOST = "api.osv.dev"
OSV_PATH = "/v1/querybatch"
MAX_BATCH_SIZE = 500
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
NETWORK_TIMEOUT_SECONDS = 60


class DependencyAuditError(RuntimeError):
    """Raised when lockfile or OSV evidence cannot be trusted."""


@dataclass(frozen=True, order=True)
class LockedPackage:
    ecosystem: str
    name: str
    version: str


@dataclass(frozen=True, order=True)
class VulnerabilityFinding:
    package: LockedPackage
    vulnerability_id: str


@dataclass(frozen=True)
class DependencyAuditReport:
    package_count: int
    batch_count: int
    findings: tuple[VulnerabilityFinding, ...]

    @property
    def ready(self) -> bool:
        return not self.findings


Transport = Callable[[bytes], bytes]


def _regular_file(path: Path) -> Path:
    if not path.is_file() or path.is_symlink():
        raise DependencyAuditError("DEPENDENCY_AUDIT_LOCKFILE_INVALID")
    return path


def _package(ecosystem: str, name: object, version: object) -> LockedPackage:
    if not isinstance(name, str) or not isinstance(version, str):
        raise DependencyAuditError("DEPENDENCY_AUDIT_LOCKFILE_INVALID")
    if not name or not version or len(name) > 256 or len(version) > 128:
        raise DependencyAuditError("DEPENDENCY_AUDIT_LOCKFILE_INVALID")
    if any(character.isspace() or ord(character) < 32 for character in name + version):
        raise DependencyAuditError("DEPENDENCY_AUDIT_LOCKFILE_INVALID")
    return LockedPackage(ecosystem=ecosystem, name=name, version=version)


def _npm_packages(path: Path) -> set[LockedPackage]:
    try:
        document = yaml.safe_load(_regular_file(path).read_text())
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise DependencyAuditError("DEPENDENCY_AUDIT_LOCKFILE_INVALID") from error
    if not isinstance(document, dict) or document.get("lockfileVersion") != "9.0":
        raise DependencyAuditError("DEPENDENCY_AUDIT_LOCKFILE_INVALID")
    packages = document.get("packages")
    if not isinstance(packages, dict) or not packages:
        raise DependencyAuditError("DEPENDENCY_AUDIT_LOCKFILE_INVALID")
    result: set[LockedPackage] = set()
    for key in packages:
        if not isinstance(key, str) or "@" not in key:
            raise DependencyAuditError("DEPENDENCY_AUDIT_LOCKFILE_INVALID")
        name, raw_version = key.rsplit("@", 1)
        version = raw_version.split("(", 1)[0]
        result.add(_package("npm", name, version))
    return result


def _pypi_packages(path: Path) -> set[LockedPackage]:
    try:
        with _regular_file(path).open("rb") as source:
            document = tomllib.load(source)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise DependencyAuditError("DEPENDENCY_AUDIT_LOCKFILE_INVALID") from error
    packages = document.get("package")
    if not isinstance(packages, list) or not packages:
        raise DependencyAuditError("DEPENDENCY_AUDIT_LOCKFILE_INVALID")
    result: set[LockedPackage] = set()
    for entry in packages:
        if not isinstance(entry, dict):
            raise DependencyAuditError("DEPENDENCY_AUDIT_LOCKFILE_INVALID")
        package_source = entry.get("source")
        if not isinstance(package_source, dict):
            raise DependencyAuditError("DEPENDENCY_AUDIT_LOCKFILE_INVALID")
        if "registry" not in package_source:
            continue
        result.add(_package("PyPI", entry.get("name"), entry.get("version")))
    return result


def collect_locked_packages(repository_root: Path) -> tuple[LockedPackage, ...]:
    packages = _npm_packages(repository_root / "web" / "pnpm-lock.yaml")
    packages.update(_pypi_packages(repository_root / "server" / "uv.lock"))
    if not packages:
        raise DependencyAuditError("DEPENDENCY_AUDIT_LOCKFILE_INVALID")
    return tuple(sorted(packages))


def _query_payload(packages: Sequence[LockedPackage]) -> bytes:
    document = {
        "queries": [
            {
                "version": package.version,
                "package": {
                    "ecosystem": package.ecosystem,
                    "name": package.name,
                },
            }
            for package in packages
        ]
    }
    return json.dumps(document, separators=(",", ":")).encode()


def _post_osv(payload: bytes) -> bytes:
    connection = http.client.HTTPSConnection(
        OSV_HOST,
        timeout=NETWORK_TIMEOUT_SECONDS,
        context=ssl.create_default_context(),
    )
    try:
        connection.request(
            "POST",
            OSV_PATH,
            body=payload,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "PDOS-dependency-audit/1",
            },
        )
        response = connection.getresponse()
        body = response.read(MAX_RESPONSE_BYTES + 1)
    except (OSError, http.client.HTTPException, ssl.SSLError) as error:
        raise DependencyAuditError("DEPENDENCY_AUDIT_NETWORK_ERROR") from error
    finally:
        connection.close()
    if response.status != 200 or len(body) > MAX_RESPONSE_BYTES:
        raise DependencyAuditError("DEPENDENCY_AUDIT_NETWORK_ERROR")
    return body


def _parse_results(
    raw: bytes,
    packages: Sequence[LockedPackage],
) -> set[VulnerabilityFinding]:
    try:
        document: Any = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DependencyAuditError("DEPENDENCY_AUDIT_RESPONSE_INVALID") from error
    if not isinstance(document, dict):
        raise DependencyAuditError("DEPENDENCY_AUDIT_RESPONSE_INVALID")
    results = document.get("results")
    if not isinstance(results, list) or len(results) != len(packages):
        raise DependencyAuditError("DEPENDENCY_AUDIT_RESPONSE_INVALID")
    findings: set[VulnerabilityFinding] = set()
    for package, result in zip(packages, results, strict=True):
        if not isinstance(result, dict):
            raise DependencyAuditError("DEPENDENCY_AUDIT_RESPONSE_INVALID")
        vulnerabilities = result.get("vulns", [])
        if not isinstance(vulnerabilities, list):
            raise DependencyAuditError("DEPENDENCY_AUDIT_RESPONSE_INVALID")
        for vulnerability in vulnerabilities:
            if not isinstance(vulnerability, dict):
                raise DependencyAuditError("DEPENDENCY_AUDIT_RESPONSE_INVALID")
            vulnerability_id = vulnerability.get("id")
            if not isinstance(vulnerability_id, str) or not vulnerability_id:
                raise DependencyAuditError("DEPENDENCY_AUDIT_RESPONSE_INVALID")
            findings.add(
                VulnerabilityFinding(
                    package=package,
                    vulnerability_id=vulnerability_id,
                )
            )
    return findings


def audit_locked_packages(
    packages: Sequence[LockedPackage],
    *,
    transport: Transport = _post_osv,
) -> DependencyAuditReport:
    if not packages:
        raise DependencyAuditError("DEPENDENCY_AUDIT_LOCKFILE_INVALID")
    findings: set[VulnerabilityFinding] = set()
    batch_count = 0
    for offset in range(0, len(packages), MAX_BATCH_SIZE):
        batch = packages[offset : offset + MAX_BATCH_SIZE]
        findings.update(_parse_results(transport(_query_payload(batch)), batch))
        batch_count += 1
    return DependencyAuditReport(
        package_count=len(packages),
        batch_count=batch_count,
        findings=tuple(sorted(findings)),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail-closed OSV lockfile audit")
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    arguments = parser.parse_args()
    try:
        packages = collect_locked_packages(arguments.repository_root.resolve())
        report = audit_locked_packages(packages)
    except DependencyAuditError as error:
        print(f"FAIL dependency_audit: {error}")
        return 2
    for finding in report.findings:
        print(
            "FAIL vulnerable_dependency: "
            f"{finding.package.ecosystem} "
            f"{finding.package.name} "
            f"{finding.package.version} "
            f"{finding.vulnerability_id}"
        )
    if not report.ready:
        print(f"Dependency audit failed: {len(report.findings)} known vulnerability record(s)")
        return 1
    print(
        f"Dependency audit passed: {report.package_count} locked registry versions, "
        f"{report.batch_count} OSV batch(es), 0 known vulnerabilities"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
