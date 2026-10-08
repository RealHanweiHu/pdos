"""Human-approved conservative accounting for three closed local-preview calls.

Bounds are not actual usage. Original traces and verified resolutions stay intact.
This port grants neither model permission nor a way to resolve new unknown calls.
"""

from datetime import UTC
from uuid import UUID, uuid4

from sqlalchemy import Engine, select, text

from app.ai.budget_accounting import BudgetAccountingError
from app.auth.repository import AuthContext
from app.db.schema import tables

TENANT = UUID("cc87e1fc-cc18-486e-89c1-56a8be1fb11d")
INVOCATIONS = frozenset(
    UUID(value)
    for value in (
        "c5ac39e4-af83-4911-b40c-236ee4066c24",
        "95fe9204-c8f3-4aa6-a870-c51123a08833",
        "a3b1253d-1c28-4272-92e9-4175ab9fdbfc",
    )
)
POLICY = "preview-legacy-20261006.v1"
BOUND_SOURCE = "https://platform.minimax.cn/docs/api-reference/text/api/openapi-chat-openai.json"
BOUND_DIGEST = "d3cda8f989a0076dca8e044aee7145d35293b00d4b32c14b74bde10c04729237"


class PreviewLegacyHolds:
    def __init__(self, engine: Engine):
        self.engine = engine

    def adopt(self, context: AuthContext, invocation_id: UUID, *, approval_ref: str) -> UUID:
        if context.tenant.id != TENANT or invocation_id not in INVOCATIONS:
            raise BudgetAccountingError("LEGACY_HOLD_SCOPE_INVALID")
        if not approval_ref.strip():
            raise BudgetAccountingError("LEGACY_HOLD_APPROVAL_REQUIRED")
        with self.engine.begin() as c:
            c.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:scope,0))"),
                {"scope": f"pdos-budget:{context.tenant.id}"},
            )
            actor = c.execute(
                select(tables.users.c.id)
                .where(
                    tables.users.c.id == context.user.id,
                    tables.users.c.tenant_id == context.tenant.id,
                    tables.users.c.is_active.is_(True),
                    tables.users.c.role.in_(["owner", "admin"]),
                )
                .with_for_update(read=True)
            ).first()
            if actor is None:
                raise BudgetAccountingError("LEGACY_HOLD_FORBIDDEN")
            prior = (
                c.execute(
                    select(tables.legacy_usage_holds).where(
                        tables.legacy_usage_holds.c.tenant_id == context.tenant.id,
                        tables.legacy_usage_holds.c.invocation_id == invocation_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if prior:
                if (
                    prior["reviewer_user_id"] != context.user.id
                    or prior["approval_ref"] != approval_ref
                ):
                    raise BudgetAccountingError("LEGACY_HOLD_CONFLICT")
                return prior["id"]
            trace = (
                c.execute(
                    select(tables.model_invocations).where(
                        tables.model_invocations.c.tenant_id == context.tenant.id,
                        tables.model_invocations.c.id == invocation_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if trace is None:
                raise BudgetAccountingError("LEGACY_HOLD_TARGET_INVALID")
            period = (
                trace["created_at"]
                .astimezone(UTC)
                .replace(hour=0, minute=0, second=0, microsecond=0)
            )
            identifier = uuid4()
            # The database also checks exact scope, route, original date, role,
            # closed session, absence of budget reservations and verified usage.
            c.execute(
                tables.legacy_usage_holds.insert(),
                dict(
                    id=identifier,
                    tenant_id=context.tenant.id,
                    invocation_id=invocation_id,
                    reviewer_user_id=context.user.id,
                    policy_key=POLICY,
                    approval_ref=approval_ref,
                    bound_source_ref=BOUND_SOURCE,
                    bound_source_digest=BOUND_DIGEST,
                    input_token_bound=1000000,
                    output_token_bound=524288,
                    budget_period_start=period,
                    created_at=c.execute(text("SELECT clock_timestamp()")).scalar_one(),
                ),
            )
            return identifier
