"""Local development credential store: macOS Keychain behind the TenantRuntime seam.

Production resolves generic secrets from Aliyun KMS. A host configuration with
kms.region "local" and endpoint "local-keychain" resolves them from the current
user's macOS Keychain instead — local pilot environments only. Secret values
never land in files, logs, or the repository; version metadata reads never
decrypt the value, matching the AliyunKms contract.
"""

import subprocess

from pydantic import SecretStr

from pdos_next.errors import DomainError

LOCAL_REGION = "local"
LOCAL_ENDPOINT = "local-keychain"
_ARN_PREFIX = "acs:kms:local:0:secret/"
_ACCOUNT = "pdos-next-local"


def _security(service):
    result = subprocess.run(
        ["security", "find-generic-password", "-a", _ACCOUNT, "-s", service, "-w"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


class LocalKeychainKms:
    def __init__(self, region, endpoint, *, client=None):
        if (region, endpoint) != (LOCAL_REGION, LOCAL_ENDPOINT):
            raise ValueError("LocalKeychainKms requires the exact local markers")
        self._read = client or _security

    def _service(self, arn):
        if not isinstance(arn, str) or not arn.startswith(_ARN_PREFIX):
            raise DomainError("SOURCE_UNAVAILABLE", "本地凭据引用格式不符。")
        return arn[len(_ARN_PREFIX) :]

    def current_version(self, arn):
        service = self._service(arn)
        if self._read(service) is None:
            return None
        return self._read(service + ".version") or "1"

    def value(self, arn, version):
        service = self._service(arn)
        current = self.current_version(arn)
        if current is None or version != current:
            raise DomainError("SOURCE_UNAVAILABLE", "租户凭据暂不可读取。")
        secret = self._read(service)
        if not secret:
            raise DomainError("SOURCE_UNAVAILABLE", "租户凭据暂不可读取。")
        return SecretStr(secret)


def factory_for(region, endpoint):
    if (region, endpoint) == (LOCAL_REGION, LOCAL_ENDPOINT):
        return LocalKeychainKms(region, endpoint)
    from .kms import AliyunKms

    return AliyunKms(region, endpoint)
