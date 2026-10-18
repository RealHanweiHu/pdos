"""Dependency-free identities for independent, named exception decisions."""

DECIDE = "release.exception.decide"
WITHDRAW = "release.exception.withdraw"
SCHEMA_VERSION = "pdos-release-exception-v1"
OPERATIONS = {
    DECIDE: ("T2", "release.exception_decided"),
    WITHDRAW: ("T2", "release.exception_withdrawn"),
}
