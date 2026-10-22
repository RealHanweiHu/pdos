"""Pure settlement rules for the COMMON human accounting command.

Model execution and new reservations are owned exclusively by agent_kernel.
"""

import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from uuid import UUID

from pdos_next.errors import DomainError
from pdos_next.model_gateway.ports import CallPermit, Reservation
from pdos_next.providers.types import ProviderUsage
from pdos_next.service import Context

_MAX_INTEGER = 2_147_483_647
_DIGEST = re.compile(r"[0-9a-f]{64}")
_ERROR_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,79}")
_REQUEST_ID = re.compile(r"[A-Za-z0-9:_.-]{1,200}")


def _positive_integer(value):
    return type(value) is int and 0 < value <= _MAX_INTEGER


def _permit_shape(permit, ctx: Context):
    if (
        not isinstance(permit, CallPermit)
        or not isinstance(permit.call_id, UUID)
        or not isinstance(permit.writer_id, UUID)
        or permit.writer_id != ctx.actor_id
        or permit.purpose != "source_claim"
        or permit.egress_allowed is not True
        or permit.protocol not in {None, "openai-compatible", "anthropic-native"}
        or not isinstance(permit.provider_version, str)
        or not permit.provider_version.strip()
        or len(permit.provider_version) > 160
        or not isinstance(permit.request_digest, str)
        or not _DIGEST.fullmatch(permit.request_digest)
        or not isinstance(permit.route_digest, str)
        or not _DIGEST.fullmatch(permit.route_digest)
        or not isinstance(permit.expires_at, datetime)
        or permit.expires_at.tzinfo is None
        or permit.expires_at <= datetime.now(UTC)
    ):
        raise DomainError("MODEL_EGRESS_DENIED", "模型预算的当前调用授权不匹配。", 403)


def _reservation_shape(reservation):
    if (
        not isinstance(reservation, Reservation)
        or not isinstance(reservation.call_id, UUID)
        or not isinstance(reservation.token, str)
        or not 20 <= len(reservation.token) <= 128
        or not re.fullmatch(r"[A-Za-z0-9_-]+", reservation.token)
    ):
        raise DomainError("MODEL_BUDGET_INVALID", "模型预算回执无效。")


def _metadata(error_code, request_id):
    if error_code is not None and (
        not isinstance(error_code, str) or not _ERROR_CODE.fullmatch(error_code)
    ):
        raise DomainError("MODEL_BUDGET_INVALID", "预算状态只能使用已登记的错误码。")
    if request_id is not None and (
        not isinstance(request_id, str) or not _REQUEST_ID.fullmatch(request_id)
    ):
        raise DomainError("MODEL_BUDGET_INVALID", "模型调用编号无效。")


@dataclass(frozen=True)
class _Settlement:
    charged: int
    status: str
    error_code: str | None
    normalized_usage: dict
    request_id: str | None


def _settlement(usage, outcome, error_code, request_id):
    _metadata(error_code, request_id)
    if not isinstance(usage, ProviderUsage) or outcome not in {"completed", "rejected"}:
        raise DomainError("MODEL_BUDGET_INVALID", "模型用量结算无效。")
    charged = usage.input_tokens + usage.output_tokens
    if type(charged) is not int or not 0 <= charged <= _MAX_INTEGER:
        raise DomainError("MODEL_BUDGET_INVALID", "模型用量超过可记录范围。")
    return _Settlement(charged, outcome, error_code, asdict(usage), request_id)


def _apply_settlement(run, row, final: _Settlement):
    """Apply once under the run + reservation locks; never downgrade a finished attempt."""
    previous_id = getattr(row, "request_id", None)
    if previous_id and final.request_id and previous_id != final.request_id:
        raise DomainError("MODEL_BUDGET_CONFLICT", "原调用编号不能由其他调用替代。")
    if row.status in {"completed", "rejected"}:
        if (row.status, row.charged, row.error_code) != (
            final.status,
            final.charged,
            final.error_code,
        ):
            raise DomainError("MODEL_BUDGET_CONFLICT", "原模型结算已保存，不能改写。")
        previous_usage = getattr(row, "normalized_usage", None)
        if previous_usage is not None and previous_usage != final.normalized_usage:
            raise DomainError("MODEL_BUDGET_CONFLICT", "原模型用量分项不能改写。")
        changed = False
        if previous_id is None and final.request_id:
            row.request_id, changed = final.request_id, True
        if previous_usage is None:
            row.normalized_usage, changed = final.normalized_usage, True
        if changed:
            row.revision = getattr(row, "revision", 1) + 1
        return run.used_tokens + run.reserved_tokens > run.token_limit
    if row.status not in {"reserved", "unknown"}:
        raise DomainError("MODEL_BUDGET_INVALID", "原模型调用状态不能结算。")
    if (
        type(run.reserved_tokens) is not int
        or type(run.used_tokens) is not int
        or run.used_tokens < 0
        or run.reserved_tokens < row.reserved
        or run.used_tokens > _MAX_INTEGER - final.charged
    ):
        raise DomainError("MODEL_BUDGET_INVALID", "模型预算计数需要核对。")
    run.reserved_tokens -= row.reserved
    run.used_tokens += final.charged
    row.charged, row.status, row.error_code = final.charged, final.status, final.error_code
    row.normalized_usage = final.normalized_usage
    row.request_id = previous_id or final.request_id
    row.settled_at = datetime.now(UTC)
    row.revision = getattr(row, "revision", 1) + 1
    return run.used_tokens + run.reserved_tokens > run.token_limit
