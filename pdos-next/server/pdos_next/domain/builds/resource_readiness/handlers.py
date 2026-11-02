"""Callable resource handler; all mutations stay staged in the caller's one UOW."""

from typing import Literal

from pdos_next.schemas.resource_readiness.contracts import (
    Check,
    ReadinessReport,
    Reservation,
    ReservationEvent,
    ReservationPreview,
    ReservationRequest,
    ResourceContext,
    StagedReservation,
)

from .ports import ReservationStorePort, ResourceFactsPort
from .rules import digest, evaluate, semantic_digest


class ResourceError(ValueError):
    def __init__(self, code: str, detail: str):
        self.code = code
        super().__init__(detail)


class ResourceReservationHandler:
    """Host invokes inside its common command, never as an unrestricted public tool."""

    def __init__(self, facts: ResourceFactsPort, store: ReservationStorePort):
        self.facts = facts
        self.store = store

    def _read(
        self, request: ReservationRequest, *, locked: bool = False, check_sources: bool = True
    ) -> tuple[ResourceContext, Reservation | None, ReadinessReport]:
        context = self.facts.context(request.owner_run_id, request.purpose, request.operation_id)
        if locked:
            self.store.lock(context, request)
            context = self.facts.context(
                request.owner_run_id, request.purpose, request.operation_id
            )
        ids = tuple(sorted((u.resource.id for u in request.uses), key=lambda x: x.bytes))
        existing = self.store.find(context, request)
        if existing is not None and (
            existing.scope != context.scope or existing.semantic_digest != semantic_digest(request)
        ):
            raise ResourceError(
                "intent_conflict", "Stable run intent/ID already has another payload"
            )
        snapshots = self.facts.resources(context, ids)
        checks = []
        for snapshot in sorted(snapshots if check_sources else (), key=lambda s: s.ref.id.bytes):
            sources = [snapshot.source, *(f.source for f in snapshot.facts)]
            sources.extend(m.source for m in (snapshot.maintenance or ()))
            if snapshot.calendar_source is not None:
                sources.append(snapshot.calendar_source)
            for source in sorted(
                set(sources), key=lambda s: (s.id.bytes, s.revision, s.kind, s.position)
            ):
                status = self.facts.source_status(context, source)
                checks.append(
                    Check(
                        resource=snapshot.ref,
                        code=f"source_{status}",
                        status="READY"
                        if status == "current"
                        else "UNKNOWN"
                        if status == "missing"
                        else "BLOCKED",
                        detail=f"Fixed evidence is {status}",
                        source=source,
                    )
                )
        occupancies = self.store.occupancies(context, ids)
        if existing is not None and existing.state == "formal":
            owned = tuple(o for o in occupancies if o.reservation_id == existing.id)
            expected = {(u.resource.id, request.window, u.units) for u in request.uses}
            actual = {(o.resource_id, o.window, o.units) for o in owned}
            if actual != expected or len(owned) != len(expected):
                checks.append(
                    Check(
                        code="formal_occupancy_changed",
                        status="BLOCKED",
                        detail="This run's current formal occupancy is missing or changed",
                    )
                )
        report = evaluate(
            context,
            request,
            snapshots,
            occupancies,
            tuple(checks),
            exclude_reservation_id=existing.id if existing else None,
        )
        return context, existing, report

    @staticmethod
    def _time_allowed(context: ResourceContext, request: ReservationRequest) -> bool:
        if context.verified_actual_start is not None:
            # Allows the host's real, independently sourced RunStart in this same UOW.
            # This value does not create Actual here or follow from a forecast time.
            return request.window.start <= context.verified_actual_start < request.window.finish
        return request.window.start >= context.now

    @staticmethod
    def _digest(context, request, report, version, state, reason):
        return digest(
            {
                "context_revision": context.facts_revision,
                "readset": report.input_digest,
                "request": semantic_digest(request),
                "expected_revision": version,
                "target_state": state,
                "reason": reason,
            }
        )

    def preview(
        self,
        request: ReservationRequest,
        *,
        expected_revision: int = 0,
        target_state: Literal["tentative", "formal", "released", "cancelled"] = "formal",
        reason: str | None = None,
    ) -> ReservationPreview:
        terminal = target_state in ("released", "cancelled")
        context, existing, report = self._read(request, check_sources=not terminal)
        authority = (
            context.authorized
            and context.qualified is True
            and context.policy_registered
            and context.owner_run_id == request.owner_run_id
        )
        allowed = authority
        if target_state in ("released", "cancelled"):
            allowed = (
                allowed
                and existing is not None
                and existing.state in ("tentative", "formal")
                and bool(reason and reason.strip())
            )
        else:
            allowed = (
                allowed
                and context.purpose == request.purpose
                and context.operation_id == request.operation_id
                and set(context.required_resources) == set(request.uses)
                and not context.cancelled
                and context.sources_current is True
                and self._time_allowed(context, request)
                and request.window.finish > context.now
            )
            if target_state == "formal":
                allowed = allowed and report.status in ("READY", "READY_WITH_CONDITIONS")
            if existing is not None and existing.state in ("released", "cancelled"):
                allowed = False
        if (existing.revision if existing else 0) != expected_revision:
            allowed = False
        return ReservationPreview(
            request=request,
            report=report,
            context_revision=context.facts_revision,
            expected_revision=expected_revision,
            target_state=target_state,
            reason=reason,
            digest=self._digest(context, request, report, expected_revision, target_state, reason),
            allowed=allowed,
            effect=(
                "Stage formal resource occupancy in caller UOW; samples and receipt must commit "
                "together"
                if target_state == "formal"
                else f"Record {target_state} history; no Actual or sample consumption"
            ),
        )

    def _stage(
        self,
        request: ReservationRequest,
        preview: ReservationPreview,
        target_state: Literal["tentative", "formal", "released", "cancelled"],
        expected_revision: int,
    ) -> StagedReservation:
        # Calling host must propagate any error and abort the entire UOW.
        terminal = target_state in ("released", "cancelled")
        context, existing, report = self._read(request, locked=True, check_sources=not terminal)
        if not terminal and (
            context.purpose != request.purpose
            or context.operation_id != request.operation_id
            or set(context.required_resources) != set(request.uses)
        ):
            raise ResourceError("required_scope_mismatch", "Server-required resource set changed")
        if not context.authorized:
            raise ResourceError("authority_forbidden", "Current authority is revoked")
        if context.qualified is not True:
            raise ResourceError("qualification_required", "Current qualification missing")
        if not context.policy_registered:
            raise ResourceError("policy_unavailable", "Current registered execution policy missing")
        if context.owner_run_id != request.owner_run_id:
            raise ResourceError("owner_mismatch", "Run differs from current authority")
        if (
            preview.request != request
            or preview.target_state != target_state
            or preview.expected_revision != expected_revision
        ):
            raise ResourceError("preview_mismatch", "Preview does not match fixed action")
        # Replays are authorized and source-checked, not another confirmation/occupancy.
        if existing and existing.state == target_state:
            if (
                target_state in ("released", "cancelled")
                and preview.reason != existing.events[-1].reason
            ):
                raise ResourceError("intent_conflict", "Terminal replay has a different reason")
            if target_state == "tentative" and (
                context.cancelled or context.sources_current is not True
            ):
                raise ResourceError(
                    "replay_stale", "Prior tentative record has stale owning context"
                )
            if target_state == "formal" and report.status not in ("READY", "READY_WITH_CONDITIONS"):
                raise ResourceError("replay_stale", "Prior reservation no longer permits execution")
            return StagedReservation(reservation=existing, replayed=True)
        if existing and existing.state in ("released", "cancelled"):
            raise ResourceError("terminal_reservation", "Historical reservation cannot reactivate")
        if (existing.revision if existing else 0) != expected_revision:
            raise ResourceError("version_conflict", "Reservation changed since preview")
        if not terminal and context.cancelled:
            raise ResourceError("run_cancelled", "Owning run is cancelled")
        if not terminal and context.sources_current is not True:
            raise ResourceError("sources_stale", "Owning source readset is no longer current")
        if not preview.allowed:
            raise ResourceError("preview_blocked", "Action is blocked")
        if preview.context_revision != context.facts_revision or preview.digest != self._digest(
            context,
            request,
            report,
            expected_revision,
            target_state,
            preview.reason,
        ):
            raise ResourceError(
                "readset_changed", "Authority, evidence, calendar or occupancy changed"
            )
        if target_state in ("released", "cancelled"):
            if existing is None or not preview.reason or not preview.reason.strip():
                raise ResourceError(
                    "terminal_requires_history", "Terminal change needs history/reason"
                )
        elif not self._time_allowed(context, request):
            raise ResourceError(
                "execution_started", "Elapsed start needs a verified host Actual event"
            )
        elif target_state == "formal" and report.status not in ("READY", "READY_WITH_CONDITIONS"):
            raise ResourceError("not_ready", "Resources do not cover complete execution interval")
        if existing and existing.state == "formal" and target_state == "tentative":
            raise ResourceError(
                "formal_downgrade", "Formal reservation must be released explicitly"
            )
        self.store.confirm(context, preview)
        event = ReservationEvent(
            kind=target_state, at=context.now, actor_id=context.actor_id, reason=preview.reason
        )
        terminal = target_state in ("released", "cancelled")
        record = Reservation(
            id=request.reservation_id,
            revision=expected_revision + 1,
            scope=context.scope,
            request=request,
            semantic_digest=semantic_digest(request),
            state=target_state,
            fixed_resources=existing.fixed_resources if terminal else report.fixed_resources,
            report=existing.report if terminal else report,
            events=(*existing.events, event) if existing else (event,),
        )
        self.store.stage(
            context,
            record,
            expected_revision,
            tuple((s.ref.id, s.occupancy_revision) for s in report.fixed_resources),
        )
        return StagedReservation(reservation=record)

    def stage_formal(
        self, request: ReservationRequest, preview: ReservationPreview, expected_revision: int = 0
    ) -> StagedReservation:
        return self._stage(request, preview, "formal", expected_revision)

    def stage_tentative(
        self, request: ReservationRequest, preview: ReservationPreview, expected_revision: int = 0
    ) -> StagedReservation:
        return self._stage(request, preview, "tentative", expected_revision)

    def stage_terminal(
        self, request: ReservationRequest, preview: ReservationPreview, expected_revision: int
    ) -> StagedReservation:
        if preview.target_state not in ("released", "cancelled"):
            raise ResourceError("terminal_state_required", "Choose release or cancellation")
        return self._stage(request, preview, preview.target_state, expected_revision)

    def recheck_execution(self, request: ReservationRequest) -> ReadinessReport:
        """No Actual write: caller starts only after resources AND samples pass in same UOW."""
        context, existing, report = self._read(request, locked=True)
        if (
            existing is None
            or existing.state != "formal"
            or report.status not in ("READY", "READY_WITH_CONDITIONS")
            or not request.window.start <= context.now < request.window.finish
        ):
            raise ResourceError(
                "execution_blocked", "Formal current reservation and interval required"
            )
        return report
