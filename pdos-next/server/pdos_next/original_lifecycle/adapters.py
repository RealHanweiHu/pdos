"""Safe unwired transport: missing lifecycle storage support remains unknown."""

from .ports import ClockPort
from .service import SystemClock
from .types import EffectOutcome, EffectPermit, EffectReceipt


class UnavailableReversibleLifecycleAdapter:
    """Neither touches ObjectStore nor asserts that retained bytes were verified."""

    def __init__(self, *, clock: ClockPort | None = None):
        self.clock = clock if clock is not None else SystemClock()

    def _unavailable(self, permit: EffectPermit) -> EffectReceipt:
        return EffectReceipt(
            permit.operation_id,
            permit.reference,
            permit.scope,
            permit.lease_token,
            EffectOutcome.UNKNOWN,
            None,
            False,
            self.clock.now(),
            "unwired-v1",
            "LIFECYCLE_TRANSPORT_UNAVAILABLE",
        )

    def apply_once(self, permit: EffectPermit) -> EffectReceipt:
        return self._unavailable(permit)

    def observe(self, permit: EffectPermit) -> EffectReceipt:
        return self._unavailable(permit)
