"""Reference-only durable rule supervision; actual admission belongs to its Activity."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

REFERENCE_KEYS = frozenset({"tenant_id", "category_id", "owner_id", "writer_id", "grant_id"})


def _reference(value):
    try:
        if (
            not isinstance(value, dict)
            or set(value) != REFERENCE_KEYS
            or any(not isinstance(item, str) for item in value.values())
        ):
            raise ValueError
        return {key: str(UUID(value[key])) for key in sorted(REFERENCE_KEYS)}
    except (ValueError, TypeError, AttributeError):
        raise ApplicationError(
            "Automation supervision requires its five fixed UUID references",
            type="AUTOMATION_REFERENCE_INVALID",
            non_retryable=True,
        ) from None


def _tick_result(value):
    try:
        if (
            not isinstance(value, dict)
            or not {"state", "wake_at"} <= value.keys()
            or set(value) - {"state", "wake_at", "reason"}
            or value["state"] not in {"active", "stopped"}
            or ("reason" in value and not isinstance(value["reason"], str))
        ):
            raise ValueError
        wake = value["wake_at"]
        if wake is not None:
            if not isinstance(wake, str):
                raise ValueError
            wake = datetime.fromisoformat(wake)
            if wake.utcoffset() is None:
                raise ValueError
            wake = wake.astimezone(UTC)
        return dict(value), wake
    except (ValueError, TypeError, OverflowError):
        raise ApplicationError(
            "Automation tick returned an invalid state or wake instant",
            type="AUTOMATION_TICK_INVALID",
            non_retryable=True,
        ) from None


@workflow.defn
class AutomationRuleWork:
    def __init__(self):
        self._wake_epoch = 0

    @workflow.signal
    def wake(self):
        # A level-triggered hint carries no business input or authorization.
        # Coalesce duplicates, but retain a signal delivered while a tick is awaiting.
        self._wake_epoch += 1

    @workflow.run
    async def run(self, reference: dict) -> dict:
        fixed = _reference(reference)
        while True:
            observed = self._wake_epoch
            result, wake_at = _tick_result(
                await workflow.execute_activity(
                    "automation_rule_tick",
                    dict(fixed),
                    start_to_close_timeout=timedelta(minutes=1),
                    # Infrastructure recovery is Temporal's retry of this same input.
                    # The supervisor never repeats a model or admits a Run itself.
                    retry_policy=RetryPolicy(maximum_interval=timedelta(minutes=1)),
                )
            )
            if result["state"] == "stopped":
                return result
            if self._wake_epoch != observed:
                continue
            timeout = None
            if wake_at is not None:
                timeout = wake_at - workflow.now()
                if timeout <= timedelta(0):
                    continue
            try:
                await workflow.wait_condition(
                    lambda epoch=observed: self._wake_epoch != epoch,
                    timeout=timeout,
                )
            except TimeoutError:
                # The durable timer reached the Activity's next wake instant.
                pass
