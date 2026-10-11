"""Explicit immutable USD rate cards; unknown fees retain conservative estimates."""

from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import ROUND_CEILING, Decimal

from pdos_next.clock import now
from pdos_next.errors import DomainError
from pdos_next.service import digest

MILLION = Decimal(1000000)


@dataclass(frozen=True)
class RateCard:
    provider: str
    model: str
    configuration_version: str
    source: str
    verified_at: datetime
    valid_until: datetime
    input_per_million: Decimal
    output_per_million: Decimal
    cache_read_per_million: Decimal
    cache_creation_per_million: Decimal
    request_fee: Decimal = Decimal(0)
    currency: str = "USD"
    text_tokens_per_utf8_byte: Decimal | None = None
    text_framing_tokens: int | None = None
    text_billing_source: str = ""
    output_cap_covers_all_billing: bool = False
    covers_all_fees: bool = False

    def validate(self, provider, route):
        prices = (
            self.input_per_million,
            self.output_per_million,
            self.cache_read_per_million,
            self.cache_creation_per_million,
            self.request_fee,
        )
        if (
            self.currency != "USD"
            or self.provider != provider
            or self.model != route.model
            or self.configuration_version != route.version
            or not self.source
            or not self.verified_at.tzinfo
            or not self.valid_until.tzinfo
            or not self.verified_at <= now() < self.valid_until
            or any(not isinstance(p, Decimal) or not p.is_finite() or p < 0 for p in prices)
            or not isinstance(self.text_tokens_per_utf8_byte, Decimal)
            or not self.text_tokens_per_utf8_byte.is_finite()
            or self.text_tokens_per_utf8_byte < 1
            or type(self.text_framing_tokens) is not int
            or self.text_framing_tokens < 0
            or not self.text_billing_source
            or self.output_cap_covers_all_billing is not True
            or self.covers_all_fees is not True
        ):
            raise DomainError("SOURCE_UNAVAILABLE", "当前模型价格未核对、已失效或与配置不同。")

    def input_upper_bound(self, wire_bytes):
        # The server must verify this exact model's billing/tokenization boundary.
        # Wire bytes alone cannot bound remote images or unknown provider accounting.
        return (
            int(
                (wire_bytes * self.text_tokens_per_utf8_byte).to_integral_value(
                    rounding=ROUND_CEILING
                )
            )
            + self.text_framing_tokens
        )

    def snapshot(self):
        value = {
            key: str(value) if isinstance(value, (datetime, Decimal)) else value
            for key, value in asdict(self).items()
        }
        return {**value, "digest": digest(value)}

    def reserve(self, input_tokens, output_tokens):
        worst = max(
            self.input_per_million, self.cache_read_per_million, self.cache_creation_per_million
        )
        return self._micro(
            self.request_fee
            + (worst * input_tokens + self.output_per_million * output_tokens) / MILLION
        )

    def actual(self, usage):
        uncached = usage.input_tokens - usage.cache_read_tokens - usage.cache_creation_tokens
        amount = (
            self.input_per_million * uncached
            + self.cache_read_per_million * usage.cache_read_tokens
            + self.cache_creation_per_million * usage.cache_creation_tokens
            + self.output_per_million * usage.output_tokens
        ) / MILLION + self.request_fee
        return self._micro(amount)

    @staticmethod
    def _micro(amount):
        return int((amount * MILLION).to_integral_value(rounding=ROUND_CEILING))


@dataclass(frozen=True)
class CostUsage:
    input_tokens: int
    output_tokens: int
    micro_usd: int
