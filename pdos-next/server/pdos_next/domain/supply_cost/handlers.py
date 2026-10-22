"""T1 command participant. Never commits or bypasses common receipts/audit/outbox."""

from datetime import timedelta

from pdos_next.engines.supply_cost.common import digest, source_issues
from pdos_next.schemas.supply_cost.dto import (
    CalculateCoveragePayload,
    CommandBinding,
    CommandReceipt,
    Confirmation,
    CostProjection,
    CoverageProjection,
    EstimateCostPayload,
    Intent,
    PreparedPlan,
    Preview,
    RecordSupplyPayload,
)

from .adapters import cost_candidate, coverage_candidate
from .errors import SupplyBusinessError, unconnected
from .ports import Ports
from .rules import basis_binding, reconcile, require_binding, require_current, require_scope


def semantic_digest(intent: Intent) -> str:
    # Two command/idempotency keys for the same action must not cause two effects.
    # Host dedupe still namespaces this digest by scope/actor and validates keys.
    return digest(
        intent.model_copy(update={"command_id": "semantic", "idempotency_key": "semantic"})
    )


def _sources(binding, value, extra=()):
    refs = [
        binding.build,
        binding.bom,
        binding.engineering_configuration,
        binding.manufacturing_configuration,
        binding.demand,
    ]
    if isinstance(value, CoverageProjection):
        request = value.result.input_snapshot
        refs += [request.supply_snapshot]
        refs += [row.ref for row in (*request.pools, *request.reservations, *request.alternates)]
        refs += list(value.quality_sources)
    elif isinstance(value, CostProjection):
        request = value.result.input_snapshot
        refs += [row.ref for row in (*request.prices, *request.rates)]
        if request.process:
            refs.append(request.process.ref)
    else:
        snapshot = value.current
        refs += [snapshot.ref]
        for name in (
            "commitments",
            "in_transit",
            "receipts",
            "restrictions",
            "pools",
            "reservations",
        ):
            refs += [row.ref for row in getattr(snapshot, name)]
    refs += list(extra)
    unique = {}
    for ref in refs:
        if ref.source_id in unique and ref != unique[ref.source_id]:
            raise SupplyBusinessError(
                "SOURCE_VERSION_CONFLICT", "Read set includes conflicting sources"
            )
        unique[ref.source_id] = ref
    return tuple(unique[key] for key in sorted(unique))


class SupplyCostHandler:
    def __init__(self, ports: Ports):
        self.ports = ports

    def _plan(self, uow: object, binding: CommandBinding, intent: Intent) -> PreparedPlan:
        if self.ports.demand is None:
            unconnected("BuildDemandPort")
        payload = intent.payload
        bound = self.ports.demand.load(
            uow, binding.scope, payload.build_id, payload.expected_build_revision, binding.as_of
        )
        require_scope(binding.scope, bound.scope)
        fixed = basis_binding(bound, binding.as_of)
        if fixed.build_id != payload.build_id or fixed.build.version != str(
            payload.expected_build_revision
        ):
            raise SupplyBusinessError(
                "BUILD_VERSION_CONFLICT", "Build port returned a different version"
            )
        # Expiry since preview is a conflict, even if fixed calculation time still
        # produces a formerly complete candidate. Never save it as current.
        for ref in (
            fixed.build,
            fixed.bom,
            fixed.engineering_configuration,
            fixed.manufacturing_configuration,
            fixed.demand,
            *bound.source_read_set,
        ):
            require_current(ref, binding.current_time)
        if isinstance(payload, RecordSupplyPayload):
            if self.ports.supply is None:
                unconnected("SupplySnapshotPort")
            previous = self.ports.supply.current(uow, binding.scope, payload.build_id)
            if previous is not None:
                require_scope(binding.scope, previous.scope)
            if (
                previous.snapshot_id if previous else None
            ) != payload.expected_previous_snapshot_id or (
                previous.revision if previous else None
            ) != payload.expected_previous_revision:
                raise SupplyBusinessError(
                    "SNAPSHOT_VERSION_CONFLICT", "Current snapshot pointer changed"
                )
            current = self.ports.supply.capture(
                uow, binding.scope, payload.capture_id, bound, binding.as_of
            )
            require_scope(binding.scope, current.scope)
            require_binding(fixed, current.binding)
            require_current(current.ref, binding.as_of)
            value = reconcile(previous, current)
            effect = "保存固定供给/质量/占用快照及前版差异；承诺和在途不增加实际可用库存。"
        elif isinstance(payload, CalculateCoveragePayload):
            if self.ports.supply is None:
                unconnected("SupplySnapshotPort")
            supply = self.ports.supply.get(
                uow, binding.scope, payload.supply_snapshot_id, payload.expected_supply_revision
            )
            if (
                supply.snapshot_id != payload.supply_snapshot_id
                or supply.revision != payload.expected_supply_revision
            ):
                raise SupplyBusinessError(
                    "SNAPSHOT_VERSION_CONFLICT", "Supply port returned a different snapshot"
                )
            current = self.ports.supply.current(uow, binding.scope, payload.build_id)
            if current is None:
                unconnected("Current supply snapshot pointer")
            require_scope(binding.scope, current.scope)
            if current != supply:
                raise SupplyBusinessError(
                    "SNAPSHOT_VERSION_CONFLICT", "Selected supply snapshot is no longer current"
                )
            alternates = self.ports.supply.verified_alternates(
                uow, binding.scope, bound, binding.as_of
            )
            value = coverage_candidate(bound, supply, alternates, binding.as_of)
            effect = "保存已占用齐套与未分配库存候选；不预约库存、不授予替代资格、不批准开工。"
        elif isinstance(payload, EstimateCostPayload):
            if self.ports.cost is None:
                unconnected("CostInputPort")
            inputs = self.ports.cost.get(
                uow,
                binding.scope,
                payload.cost_input_id,
                payload.expected_cost_input_revision,
                bound,
            )
            if (
                inputs.input_id != payload.cost_input_id
                or inputs.revision != payload.expected_cost_input_revision
            ):
                raise SupplyBusinessError(
                    "COST_INPUT_VERSION_CONFLICT", "Cost port returned a different input"
                )
            value = cost_candidate(bound, inputs, binding.as_of)
            effect = "保存选定费用范围的成本估算候选；缺项保持未知，不代表实际降本或财务批准。"
        else:
            raise SupplyBusinessError(
                "OPERATION_UNSUPPORTED", "Unsupported supply business operation"
            )
        extra = bound.source_read_set
        if isinstance(value, CostProjection):
            # Aggregate import ref is additional to each quote/process/rate ref.
            extra = (*extra, inputs.ref)
            for price in inputs.prices:
                valid_at_preview = (
                    price.valid_from is None or binding.as_of >= price.valid_from
                ) and (price.valid_until is None or binding.as_of < price.valid_until)
                valid_now = (
                    price.valid_from is None or binding.current_time >= price.valid_from
                ) and (price.valid_until is None or binding.current_time < price.valid_until)
                if valid_at_preview != valid_now:
                    raise SupplyBusinessError(
                        "SOURCE_STALE", "Quote eligibility changed since preview"
                    )
            limit = timedelta(days=inputs.cost_scope.max_rate_age_days)
            for rate in inputs.rates:
                valid_at_preview = binding.as_of - rate.ref.captured_at <= limit
                valid_now = binding.current_time - rate.ref.captured_at <= limit
                if valid_at_preview != valid_now:
                    raise SupplyBusinessError(
                        "SOURCE_STALE", "Exchange rate aged out since preview"
                    )
        sources = _sources(fixed, value, extra)
        for ref in sources:
            if not source_issues(ref, binding.as_of, "source"):
                require_current(ref, binding.current_time)
        return PreparedPlan(
            as_of=binding.as_of,
            scope=binding.scope,
            operation=intent.operation,
            intent_sha256=semantic_digest(intent),
            sources=tuple(sources),
            value=value,
            effect=effect,
        )

    def preview(self, uow: object, context: object, intent: Intent) -> Preview:
        bound = self.ports.command.bind(uow, context, intent, None)
        self.ports.command.authorize(uow, context, bound, intent, apply=False)
        plan = self._plan(uow, bound, intent)
        preview = self.ports.command.preview(uow, bound, intent, plan)
        if (
            preview.review != plan
            or preview.plan_sha256 != digest(plan)
            or preview.as_of != bound.as_of
            or preview.expires_at <= bound.current_time
        ):
            raise SupplyBusinessError(
                "PREVIEW_PORT_REJECTED", "Preview port did not bind this substantive plan"
            )
        return preview

    def apply(
        self, uow: object, context: object, intent: Intent, confirmation: Confirmation
    ) -> CommandReceipt:
        bound = self.ports.command.bind(uow, context, intent, confirmation)
        self.ports.command.authorize(uow, context, bound, intent, apply=True)
        receipt = self.ports.command.replay(uow, bound, intent, confirmation)
        if receipt is not None:
            return self._checked_receipt(receipt, intent, confirmation.plan_sha256)
        plan = self._plan(uow, bound, intent)
        if digest(plan) != confirmation.plan_sha256:
            raise SupplyBusinessError(
                "PREVIEW_CHANGED", "Sources or substantive plan changed; preview again"
            )
        receipt = self.ports.command.stage_once(uow, context, bound, intent, confirmation, plan)
        return self._checked_receipt(receipt, intent, digest(plan))

    @staticmethod
    def _checked_receipt(receipt, intent, plan_sha):
        expected = {
            "supply.snapshot.record": "supply_snapshot",
            "supply.coverage.calculate": "supply_coverage",
            "supply.cost.estimate": "cost_estimate",
        }
        if receipt.subject_type != expected[intent.operation] or receipt.plan_sha256 != plan_sha:
            raise SupplyBusinessError(
                "RECEIPT_PORT_REJECTED", "Receipt does not match the requested plan"
            )
        return receipt
