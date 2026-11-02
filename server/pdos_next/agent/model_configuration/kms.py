"""Alibaba Cloud KMS generic secrets; metadata lookup never decrypts a value."""

from pydantic import SecretStr

from pdos_next.errors import DomainError


class AliyunKms:
    def __init__(self, region, endpoint, *, client=None):
        self.region, self.endpoint, self.client = region, endpoint, client

    def sdk(self):
        if self.client is None:
            from alibabacloud_credentials.client import Client as Credentials
            from alibabacloud_kms20160120.client import Client
            from alibabacloud_tea_openapi.models import Config

            self.client = Client(
                Config(
                    credential=Credentials(),
                    region_id=self.region,
                    endpoint=self.endpoint,
                    protocol="https",
                )
            )
        return self.client

    @staticmethod
    def options():
        from alibabacloud_tea_util.models import RuntimeOptions

        return RuntimeOptions(autoretry=False, connect_timeout=2000, read_timeout=5000)

    @staticmethod
    def matches(arn, returned):
        return returned in {arn, arn.split(":secret/", 1)[-1]}

    def current_version(self, arn):
        from alibabacloud_kms20160120.models import ListSecretVersionIdsRequest

        try:
            page, versions, seen = 1, [], set()
            while True:
                response = (
                    self.sdk()
                    .list_secret_version_ids_with_options(
                        ListSecretVersionIdsRequest(
                            secret_name=arn,
                            include_deprecated="false",
                            page_number=page,
                            page_size=100,
                        ),
                        self.options(),
                    )
                    .body
                )
                if not self.matches(arn, response.secret_name) or response.page_number != page:
                    raise ValueError("KMS metadata scope changed")
                rows = response.version_ids.version_id if response.version_ids else []
                for row in rows:
                    if not row.version_id or row.version_id in seen:
                        raise ValueError("KMS version page did not advance")
                    seen.add(row.version_id)
                    if row.version_stages and "ACSCurrent" in row.version_stages.version_stage:
                        versions.append(row.version_id)
                if len(rows) < 100 or page * 100 >= response.total_count:
                    break
                page += 1
            if len(versions) > 1:
                raise ValueError("KMS current version is ambiguous")
            return versions[0] if versions else None
        except Exception:
            raise DomainError("SOURCE_UNAVAILABLE", "租户凭据版本暂不可核对。") from None

    def value(self, arn, version):
        from alibabacloud_kms20160120.models import GetSecretValueRequest

        try:
            response = (
                self.sdk()
                .get_secret_value_with_options(
                    GetSecretValueRequest(
                        secret_name=arn, version_id=version, version_stage="ACSCurrent"
                    ),
                    self.options(),
                )
                .body
            )
            if (
                not self.matches(arn, response.secret_name)
                or response.version_id != version
                or response.secret_type != "Generic"
                or response.secret_data_type != "text"
                or not isinstance(response.secret_data, str)
                or not response.secret_data
                or not response.version_stages
                or "ACSCurrent" not in response.version_stages.version_stage
            ):
                raise ValueError("KMS value binding changed")
            return SecretStr(response.secret_data)
        except Exception:
            raise DomainError("SOURCE_UNAVAILABLE", "租户凭据暂不可读取。") from None

    def create(self, name, version, credential):
        from alibabacloud_kms20160120.models import CreateSecretRequest, DescribeSecretRequest

        try:
            try:
                response = self.sdk().create_secret_with_options(CreateSecretRequest(
                    secret_name=name, version_id=version, secret_type="Generic",
                    secret_data_type="text", secret_data=credential.get_secret_value()),
                    self.options()).body
            except Exception:
                # Reconcile an unknown creation using the same deterministic secret name.
                # No new name, version or potentially duplicated external write is attempted.
                response = self.sdk().describe_secret_with_options(
                    DescribeSecretRequest(secret_name=name), self.options()).body
            arn = response.arn
            if not isinstance(arn, str) or not arn.startswith(f"acs:kms:{self.region}:"):
                raise ValueError("KMS target changed")
            if arn.split(":secret/", 1)[-1] != name or self.current_version(arn) != version:
                raise ValueError("KMS version changed")
            from hmac import compare_digest

            if not compare_digest(self.value(arn, version).get_secret_value(),
                                  credential.get_secret_value()):
                raise ValueError("Secret request changed")
            return arn
        except Exception:
            raise DomainError(
                "SOURCE_UNAVAILABLE", "凭据保存结果尚未确认，请核对原请求。", 503) from None
