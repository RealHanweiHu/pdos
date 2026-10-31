"""Local development credential store: macOS Keychain behind the TenantRuntime seam.

Production resolves generic secrets from Aliyun KMS. A host configuration with
kms.region "local" and endpoint "local-keychain" resolves them from the current
user's macOS Keychain instead — local pilot environments only. Secret values
never land in files, logs, or the repository; version metadata reads never
decrypt the value, matching the AliyunKms contract.
"""

import subprocess
from hmac import compare_digest

from pydantic import SecretStr

from pdos_next.errors import DomainError

LOCAL_REGION = "local"
LOCAL_ENDPOINT = "local-keychain"
_ARN_PREFIX = "acs:kms:local:0:secret/"
_ACCOUNT = "pdos-next-local"


def _add(service, value):
    # Security.framework accepts the password in memory, never in process argv/stdin logs.
    import ctypes

    api = ctypes.CDLL("/System/Library/Frameworks/Security.framework/Security")
    add = api.SecKeychainAddGenericPassword
    add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p,
        ctypes.c_uint32, ctypes.c_char_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p]
    add.restype = ctypes.c_int32
    service_bytes, account, password = service.encode(), _ACCOUNT.encode(), value.encode()
    status = add(None, len(service_bytes), service_bytes, len(account), account,
        len(password), password, None)
    if status not in {0, -25299}:  # Duplicate is resolved by exact value/version checks below.
        raise DomainError("SOURCE_UNAVAILABLE", "本机安全凭据保存失败，请核对钥匙串访问。")


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
    def __init__(self, region, endpoint, *, client=None, writer=None):
        if (region, endpoint) != (LOCAL_REGION, LOCAL_ENDPOINT):
            raise ValueError("LocalKeychainKms requires the exact local markers")
        self._read = client or _security
        self._write = writer or _add

    def create(self, name, version, credential):
        try:
            self._write(name, credential.get_secret_value())
            if not compare_digest(self._read(name) or "", credential.get_secret_value()):
                raise ValueError("Secret request changed")
            self._write(name + ".version", version)
            if self._read(name + ".version") != version:
                raise ValueError("Secret version changed")
            return _ARN_PREFIX + name
        except Exception:
            raise DomainError(
                "SOURCE_UNAVAILABLE", "本机凭据尚未保存，请核对原保存请求。", 503) from None

    def _service(self, arn):
        if not isinstance(arn, str) or not arn.startswith(_ARN_PREFIX):
            raise DomainError("SOURCE_UNAVAILABLE", "本地凭据引用格式不符。")
        return arn[len(_ARN_PREFIX) :]

    def current_version(self, arn):
        service = self._service(arn)
        version = self._read(service + ".version")
        if version is not None:
            return version
        if self._read(service) is None:
            return None
        return "1"  # Legacy entries without a separate version item retain their original binding.

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
