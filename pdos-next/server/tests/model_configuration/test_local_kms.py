"""LocalKeychainKms contract: version metadata never decrypts, wrong versions refuse."""

import pytest

from pdos_next.errors import DomainError
from pdos_next.model_configuration.local_kms import (
    LOCAL_ENDPOINT,
    LOCAL_REGION,
    LocalKeychainKms,
    factory_for,
)

ARN = "acs:kms:local:0:secret/synthetic-local-key"


def backend(items):
    return LocalKeychainKms(LOCAL_REGION, LOCAL_ENDPOINT, client=lambda service: items.get(service))


def test_current_version_never_reads_the_secret_value_and_value_checks_version():
    service = ARN[len("acs:kms:local:0:secret/") :]
    kms = backend({service: "synthetic-secret", service + ".version": "3"})
    assert kms.current_version(ARN) == "3"
    assert kms.value(ARN, "3").get_secret_value() == "synthetic-secret"
    with pytest.raises(DomainError):
        kms.value(ARN, "2")


def test_unknown_or_malformed_references_are_unavailable():
    kms = backend({})
    assert kms.current_version(ARN) is None
    with pytest.raises(DomainError):
        kms.value(ARN, "1")
    with pytest.raises(DomainError):
        kms.current_version("acs:kms:cn-hangzhou:1:secret/not-local")


def test_factory_selects_local_only_for_the_exact_marker_pair():
    from pdos_next.model_configuration.kms import AliyunKms

    assert isinstance(factory_for(LOCAL_REGION, LOCAL_ENDPOINT), LocalKeychainKms)
    assert isinstance(factory_for("cn-hangzhou", "kms.cn-hangzhou.aliyuncs.com"), AliyunKms)
