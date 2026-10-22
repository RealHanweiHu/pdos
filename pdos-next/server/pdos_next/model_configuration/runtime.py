"""Fail-closed runtime selection and a currentness callback for server-owned permit callbacks."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from pdos_next.errors import DomainError
from pdos_next.model_configuration.ports import (
    RuntimeFacts,
    RuntimePolicyPort,
    RuntimeQuery,
    SecretMaterial,
    SecretPort,
)
from pdos_next.model_configuration.service import (
    ConfigurationStore,
    ConfigurationVersion,
    current_secret,
    fail,
    secret_digest,
    utc,
)
from pdos_next.model_gateway.ports import CallPermit
from pdos_next.providers.types import ProviderRoute


@dataclass(frozen=True)
class Selection:
    code: str
    state: Literal["unavailable", "authorizer_check"] = "unavailable"
    configuration: ConfigurationVersion | None = field(default=None, repr=False)
    route: ProviderRoute | None = field(default=None, repr=False)
    reason: str | None = None


class RuntimeConfiguration:
    def __init__(
        self,
        store: ConfigurationStore,
        secrets: SecretPort | None,
        policy: RuntimePolicyPort | None,
    ):
        self.store, self.secrets, self.policy = store, secrets, policy

    def _config(self, query: RuntimeQuery, expected: ConfigurationVersion | None = None):
        head = self.store.current(query.tenant_id)
        if head is None:
            fail("MODEL_NOT_CONFIGURED")
        if head.tenant_id != query.tenant_id:
            fail("MODEL_CONFIGURATION_SCOPE_MISMATCH", 403)
        if expected is not None and head.binding_digest != expected.binding_digest:
            fail("MODEL_CONFIGURATION_CHANGED")
        if not head.enabled:
            fail("MODEL_DISABLED")
        current = current_secret(self.secrets, query.tenant_id, head.metadata.protocol)
        if secret_digest(current) != secret_digest(head.secret):
            fail("MODEL_SECRET_CHANGED")
        if current is None or not current.available:
            fail("MODEL_SECRET_MISSING")
        return head, current

    def _facts(self, query: RuntimeQuery, head: ConfigurationVersion, now: datetime):
        if not utc(now):
            fail("MODEL_CLOCK_INVALID")
        if self.policy is None:
            fail("MODEL_POLICY_INTERFACE_MISSING")
        try:
            facts = self.policy.current_facts(query, head.binding_digest)
        except Exception:
            fail("MODEL_POLICY_UNAVAILABLE")
        if facts is None:
            fail("MODEL_POLICY_FACTS_MISSING")
        if (
            not isinstance(facts, RuntimeFacts)
            or facts.query != query
            or facts.binding_digest != head.binding_digest
        ):
            fail("MODEL_POLICY_SCOPE_MISMATCH", 403)
        if not utc(facts.expires_at) or facts.expires_at <= now:
            fail("MODEL_POLICY_EXPIRED")
        checks = (
            (facts.permitted, "MODEL_PERMISSION_FACT_MISSING", "MODEL_PERMISSION_DENIED"),
            (facts.qualified, "MODEL_QUALIFICATION_FACT_MISSING", "MODEL_QUALIFICATION_REQUIRED"),
            (facts.egress_allowed, "MODEL_EGRESS_FACT_MISSING", "MODEL_EGRESS_REQUIRED"),
            (facts.budget_available, "MODEL_BUDGET_FACT_MISSING", "MODEL_BUDGET_REQUIRED"),
        )
        if type(facts.cancelled) is not bool:
            fail("MODEL_CANCEL_FACT_MISSING")
        if facts.cancelled:
            fail("MODEL_CANCELLED")
        for value, missing, denied in checks:
            if type(value) is not bool:
                fail(missing)
            if value is not True:
                fail(denied, 403)

    def select(self, query: RuntimeQuery, *, now: datetime) -> Selection:
        """No network call, permit, reservation, qualification or domain write occurs here."""
        try:
            head, secret = self._config(query)
            self._facts(query, head, now)
            try:
                material = self.secrets.resolve(secret)
            except Exception:
                fail("MODEL_SECRET_UNAVAILABLE")
            if not isinstance(material, SecretMaterial) or material.binding != secret:
                fail("MODEL_SECRET_MISSING")
            try:
                route = head.metadata.route(material.credential, head.provider_version)
            except (ValueError, TypeError, AttributeError):
                fail("MODEL_SECRET_INVALID")
            # Rotation/revocation during resolution must not leave a usable old binding.
            latest, _ = self._config(query, expected=head)
            self._facts(query, latest, now)
            return Selection("MODEL_AUTHORIZER_CHECK_REQUIRED", "authorizer_check", head, route)
        except DomainError as error:
            return Selection(error.code, reason=error.reason)

    def currentness(
        self,
        selection: Selection,
        query: RuntimeQuery,
        *,
        now: Callable[[], datetime],
        require_permit_current: Callable[[CallPermit], None] | None,
    ) -> Callable[[CallPermit], None]:
        """Compose with mainline authorization, never substitute for its permit currentness.

        The caller checks request_digest and expiry; this callback additionally
        ties the server-captured Run and immutable tenant/secret/config binding to it.
        """

        def check(permit: CallPermit):
            if require_permit_current is None:
                fail("MODEL_PERMIT_INTERFACE_MISSING", 403)
            head, route = selection.configuration, selection.route
            if selection.state != "authorizer_check" or head is None or route is None:
                fail("MODEL_UNAVAILABLE")
            checked_at = now()
            if (
                not isinstance(permit, CallPermit)
                or not utc(checked_at)
                or not utc(permit.expires_at)
                or permit.expires_at <= checked_at
                or permit.writer_id != query.writer_id
                or permit.route_digest != route.digest
                or permit.provider_version != head.provider_version
                or permit.purpose != query.purpose
                or permit.egress_allowed is not True
                or permit.protocol not in {None, route.protocol}
            ):
                fail("MODEL_PERMIT_BINDING_MISMATCH", 403)
            require_permit_current(permit)
            latest, _ = self._config(query, expected=head)
            final_time = now()
            if not utc(final_time) or permit.expires_at <= final_time:
                fail("MODEL_PERMIT_BINDING_MISMATCH", 403)
            self._facts(query, latest, final_time)

        return check
