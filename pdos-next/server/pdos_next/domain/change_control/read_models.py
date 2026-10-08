"""Authorized current read projection; historic approval is never rewritten."""

from uuid import UUID

from pdos_next.schemas.change_control.contracts import ChangeRequest
from pdos_next.schemas.verification.contracts import DTO

from .handlers import ChangeControlHandler
from .ports import Ports
from .rules import effectivity_status


class ItemReading(DTO):
    item_id: UUID
    implementation_status: str
    effectivity_status: str
    covered_units: tuple[str, ...]
    remaining_units: tuple[str, ...]


class ChangeReading(DTO):
    request: ChangeRequest
    current: bool
    recheck_reasons: tuple[str, ...]
    items: tuple[ItemReading, ...]
    engineering_approved: bool
    manufacturing_approved: bool
    independently_verified: bool
    historically_closed: bool
    registered: bool = False  # host supplies live registration separately
    downstream_intents_only: bool = True


class ChangeControlReader:
    def __init__(self, ports: Ports):
        self.handler = ChangeControlHandler(ports)

    def get(self, uow: object, request_id: UUID) -> ChangeReading:
        h = self.handler
        a = h._port("commands").context(uow, "change.read", request_id)
        # Reading needs current scope/audience authorization, not a write qualification.
        if not a.authorized or a.cancelled:
            from pdos_next.errors import DomainError

            raise DomainError("FORBIDDEN_OPERATION", "当前范围不可读取。", 403)
        request = h._request(uow, a, request_id)
        # Authorize historical nested references before exposing the aggregate.
        # Currentness false does not remove history; a denied source raises.
        for assessment in request.assessments:
            h._fixed_graph(uow, a, assessment.graph)
            for hyp in assessment.hypotheses:
                for source in hyp.sources:
                    h._source(uow, a, source)
        for order in request.orders:
            h._source(uow, a, order.policy)
            for disposition in order.plan.dispositions:
                h._ref(uow, a, disposition.object)
                for source in disposition.sources:
                    h._source(uow, a, source)
            for item in order.plan.items:
                h._port("facts").selection(uow, a, item)
                for ref in (*item.selection.objects, *item.intent.basis):
                    h._ref(uow, a, ref)
                for source in item.selection.sources:
                    h._source(uow, a, source)
            for record in (
                *order.approvals,
                *order.implementations,
                *order.effectivity,
                *order.verifications,
            ):
                for source in record.sources:
                    h._source(uow, a, source)
                refs = getattr(record, "outputs", getattr(record, "output_refs", ()))
                for ref in refs:
                    h._ref(uow, a, ref)
                if hasattr(record, "fact"):
                    for source in record.fact.sources:
                        h._source(uow, a, source)
                    for ref in record.fact.output_refs:
                        h._ref(uow, a, ref)
            if order.closure:
                for source in order.closure.sources:
                    h._source(uow, a, source)
        reasons = h._current(uow, a, request)
        order = (
            request.orders[-1]
            if request.orders
            and request.status
            not in {
                "draft",
                "analysis",
            }
            else None
        )
        items = []
        if order:
            for item in order.plan.items:
                facts = [f for f in order.implementations if f.item_id == item.id]
                latest = {}
                reconciled = {
                    r.reconciles_id for r in order.effectivity if r.reconciles_id is not None
                }
                for receipt in sorted(
                    order.effectivity, key=lambda r: (r.received_at, r.occurred_at, str(r.id))
                ):
                    if (
                        receipt.id not in reconciled
                        and receipt.item_id == item.id
                        and (receipt.stage == "effective")
                    ):
                        for unit in receipt.covered_units:
                            latest[unit] = receipt.outcome
                covered = {u for u, result in latest.items() if result == "succeeded"}
                items.append(
                    ItemReading(
                        item_id=item.id,
                        implementation_status=facts[-1].outcome if facts else "pending",
                        effectivity_status=effectivity_status(order, item),
                        covered_units=tuple(sorted(covered)),
                        remaining_units=tuple(sorted(set(item.selection.units) - covered)),
                    )
                )
        return ChangeReading(
            request=request,
            current=not reasons,
            recheck_reasons=reasons,
            items=tuple(items),
            engineering_approved=bool(
                order and any(x.discipline == "engineering" for x in order.approvals)
            ),
            manufacturing_approved=bool(
                order and any(x.discipline == "manufacturing" for x in order.approvals)
            ),
            independently_verified=bool(
                order
                and order.verifications
                and (order.verifications[-1].fact.result == "pass")
                and not reasons
            ),
            historically_closed=any(o.closure is not None for o in request.orders),
        )
