"""Stage reversible lifecycle commands through server ports; never commit or delete."""

from dataclasses import replace
from datetime import datetime
from uuid import UUID, uuid4

from pdos_next.object_storage.types import ObjectRef

from .ports import ClockPort, LifecycleAuthorityPort, LifecycleStorePort, ReferenceGuardPort
from .rules import digest, evaluate_quarantine, evaluate_restore, facts_digest
from .types import (
    ActorKind,
    CurrentAuthorization,
    Disposition,
    EffectOutcome,
    EffectPermit,
    EffectReceipt,
    IntentState,
    LifecycleAction,
    LifecycleFailure,
    LifecycleIntent,
    OrphanCandidate,
    RequestBinding,
    RetentionPolicy,
    token,
)


class SystemClock:
    def now(self) -> datetime:
        from pdos_next.clock import now

        return now()


def candidate_digest(candidate: OrphanCandidate) -> str:
    return digest(
        [
            candidate.id,
            candidate.action,
            candidate.original,
            candidate.references,
            candidate.decision,
            candidate.captured_at,
            candidate.policy_digest,
        ]
    )


class LifecycleService:
    def __init__(
        self,
        *,
        store: LifecycleStorePort,
        references: ReferenceGuardPort,
        authority: LifecycleAuthorityPort,
        policy: RetentionPolicy,
        clock: ClockPort | None = None,
    ):
        self.store, self.references, self.authority = store, references, authority
        self.policy = policy
        self.clock = clock if clock is not None else SystemClock()

    def _authorize(self, context, original, action, now, *, decision=None):
        authorization = self.authority.authorize(
            context, original.reference, action, now, decision=decision
        )
        if not isinstance(authorization, CurrentAuthorization) or (
            authorization.reference != original.reference
            or authorization.scope != original.scope
            or authorization.action != action
            or (authorization.expires_at is not None and authorization.expires_at <= now)
        ):
            raise LifecycleFailure("FORBIDDEN_SCOPE", "Current server authorization does not bind")
        return authorization

    def _decision(self, action, original, references, now, *, allowed_pending=None):
        rule = evaluate_quarantine if action == LifecycleAction.QUARANTINE else evaluate_restore
        return rule(original, references, self.policy, now, allowed_pending=allowed_pending)

    def _candidate(self, candidate_id):
        candidate = self.store.get_candidate(candidate_id)
        if candidate.id != candidate_id:
            raise LifecycleFailure("PREVIEW_CORRUPT", "Stored preview pointer does not bind")
        if candidate.digest != candidate_digest(candidate):
            raise LifecycleFailure(
                "PREVIEW_CORRUPT", "Stored preview does not match its fixed digest"
            )
        if candidate.policy_digest != digest(self.policy):
            raise LifecycleFailure(
                "POLICY_CHANGED", "Lifecycle policy changed; create a new preview"
            )
        return candidate

    def _write_result(self, expected, returned):
        if expected != returned:
            raise LifecycleFailure(
                "PORT_RESULT_MISMATCH", "Transaction port returned a different intent"
            )
        return returned

    def _change(self, fence, before, after, original):
        return self._write_result(after, self.store.change(fence, before, after, original))

    def _prior_binding(self, intent, original, action, *, intent_digest=None, intent_id=None):
        if (
            intent.reference != original.reference
            or intent.scope != original.scope
            or (
                intent.action != action
                or (intent_digest is not None and intent.intent_digest != intent_digest)
                or (intent_id is not None and intent.id != intent_id)
            )
        ):
            raise LifecycleFailure(
                "BINDING_MISMATCH", "Stored dedup result binds a different operation"
            )
        return intent

    def preview(
        self,
        context: object,
        reference: ObjectRef,
        *,
        action: LifecycleAction = LifecycleAction.QUARANTINE,
    ) -> OrphanCandidate:
        if not isinstance(action, LifecycleAction) or action not in (
            LifecycleAction.QUARANTINE,
            LifecycleAction.RESTORE,
        ):
            raise LifecycleFailure(
                "INVALID_ACTION", "Only reversible lifecycle previews are supported"
            )
        original = self.store.read_current(reference)
        if original.reference != reference:
            raise LifecycleFailure("BINDING_MISMATCH", "Object inventory does not bind exact bytes")
        self._authorize(context, original, LifecycleAction.PREVIEW, self.clock.now())
        references = self.references.read_current(reference)
        now = self.clock.now()
        self._authorize(context, original, LifecycleAction.PREVIEW, now)
        decision = self._decision(action, original, references, now)
        candidate = OrphanCandidate(
            uuid4(),
            action,
            original,
            references,
            decision,
            now,
            digest(self.policy),
            "0" * 64,
        )
        candidate = replace(candidate, digest=candidate_digest(candidate))
        self.store.save_candidate(candidate)
        return candidate

    def confirm(
        self,
        context: object,
        candidate_id: UUID,
        expected_digest: str,
        idempotency_key: str,
    ) -> LifecycleIntent:
        token(idempotency_key, "idempotency key", maximum=200)
        candidate = self._candidate(candidate_id)
        if expected_digest != candidate.digest:
            raise LifecycleFailure(
                "PREVIEW_MISMATCH", "Confirmation differs from the stored preview"
            )
        fence = self.store.lock_current(candidate.original.reference)
        original, now = fence.original, self.clock.now()
        authorization = self._authorize(context, original, candidate.action, now)
        if authorization.actor_kind != ActorKind.HUMAN or (
            authorization.named_decider_id != authorization.actor_id
            or authorization.decision_intent_id is not None
        ):
            raise LifecycleFailure("NAMED_CONFIRMATION_REQUIRED", "A current named human confirms")
        fingerprint = digest([candidate.id, candidate.digest])
        intent_digest = digest(
            [
                candidate.action,
                candidate.original.scope,
                candidate.original.reference,
                candidate.policy_digest,
                facts_digest(candidate.original, candidate.references),
            ]
        )
        previous_request = self.store.find_request(
            original.scope, authorization.actor_id, idempotency_key
        )
        if previous_request is not None:
            if previous_request.scope != original.scope or (
                previous_request.actor_id != authorization.actor_id
                or previous_request.key != idempotency_key
            ):
                raise LifecycleFailure(
                    "BINDING_MISMATCH", "Stored request binds a different caller"
                )
            if previous_request.fingerprint != fingerprint:
                raise LifecycleFailure(
                    "IDEMPOTENCY_CONFLICT", "Request key binds a different preview"
                )
            return self._prior_binding(
                self.store.get_intent(previous_request.intent_id),
                original,
                candidate.action,
                intent_digest=intent_digest,
                intent_id=previous_request.intent_id,
            )
        previous_intent = self.store.find_intent(original.scope, intent_digest)
        if previous_intent is not None:
            self._prior_binding(
                previous_intent, original, candidate.action, intent_digest=intent_digest
            )
            self.store.remember_request(
                fence,
                RequestBinding(
                    original.scope,
                    authorization.actor_id,
                    idempotency_key,
                    fingerprint,
                    previous_intent.id,
                ),
            )
            return previous_intent
        if candidate.captured_at > now:
            raise LifecycleFailure("FACT_TIME_INVALID", "Candidate capture cannot be in the future")
        if not candidate.decision.eligible:
            raise LifecycleFailure("RETENTION_PROTECTED", "Preview protects this original")
        references = self.references.read_under_fence(fence)
        now = self.clock.now()
        final_authorization = self._authorize(context, original, candidate.action, now)
        if final_authorization.actor_kind != ActorKind.HUMAN or (
            final_authorization.actor_id != authorization.actor_id
            or final_authorization.named_decider_id != final_authorization.actor_id
            or final_authorization.decision_intent_id is not None
        ):
            raise LifecycleFailure("NAMED_CONFIRMATION_REQUIRED", "A current named human confirms")
        authorization = final_authorization
        if candidate.captured_at > now:
            raise LifecycleFailure("FACT_TIME_INVALID", "Candidate capture cannot be in the future")
        if facts_digest(original, references) != facts_digest(
            candidate.original, candidate.references
        ):
            raise LifecycleFailure("PREVIEW_STALE", "Current references or lifecycle facts changed")
        decision = self._decision(candidate.action, original, references, now)
        if not decision.eligible:
            raise LifecycleFailure(
                "RETENTION_PROTECTED", "Current authority protects this original"
            )
        intent = LifecycleIntent(
            uuid4(),
            candidate.id,
            candidate.digest,
            intent_digest,
            original.reference,
            original.scope,
            candidate.action,
            authorization.actor_id,
            authorization.access_revision,
            self.policy.version,
            1,
            IntentState.PENDING,
            now,
            now,
        )
        updated = replace(original, revision=original.revision + 1, pending_intent_id=intent.id)
        return self._write_result(
            intent,
            self.store.stage(
                fence,
                intent,
                updated,
                RequestBinding(
                    original.scope,
                    authorization.actor_id,
                    idempotency_key,
                    fingerprint,
                    intent.id,
                ),
            ),
        )

    def _locked_operation(self, intent_id):
        initial = self.store.get_intent(intent_id)
        if initial.id != intent_id:
            raise LifecycleFailure("BINDING_MISMATCH", "Stored intent pointer does not bind")
        fence = self.store.lock_current(initial.reference)
        # Reread after taking the shared lock, not a pre-lock cached operation.
        intent = self.store.get_intent(intent_id)
        if (
            intent.id != intent_id
            or intent.reference != fence.original.reference
            or (intent.scope != fence.original.scope)
        ):
            raise LifecycleFailure(
                "BINDING_MISMATCH", "Operation no longer binds the exact original"
            )
        return fence, intent

    def _effect_authority(self, context, fence, intent, now, *, reconcile=False):
        action = LifecycleAction.RECONCILE if reconcile else intent.action
        authorization = self._authorize(context, fence.original, action, now, decision=intent)
        if authorization.actor_kind != ActorKind.SERVICE or (
            authorization.named_decider_id != intent.named_decider_id
            or authorization.decision_intent_id != intent.id
        ):
            raise LifecycleFailure(
                "WORKER_AUTHORITY_REQUIRED", "Current trusted worker binding required"
            )
        return authorization

    def begin_effect(self, context: object, intent_id: UUID) -> EffectPermit:
        """Stage one permit. Mainline must commit it before calling physical apply_once."""
        fence, intent = self._locked_operation(intent_id)
        now = self.clock.now()
        authorization = self._effect_authority(context, fence, intent, now)
        if intent.state != IntentState.PENDING or intent.permit is not None:
            raise LifecycleFailure(
                "EFFECT_ALREADY_ATTEMPTED", "Observe the stored attempt; never resend"
            )
        if fence.original.pending_intent_id != intent.id:
            raise LifecycleFailure("FENCE_LOST", "Pending operation fence was lost")
        candidate = self._candidate(intent.candidate_id)
        references = self.references.read_under_fence(fence)
        now = self.clock.now()
        authorization = self._effect_authority(context, fence, intent, now)
        if fence.original.revision != candidate.original.revision + 1:
            raise LifecycleFailure("PREVIEW_STALE", "Lifecycle version changed after confirmation")
        current_basis = replace(
            fence.original,
            revision=candidate.original.revision,
            pending_intent_id=None,
        )
        if facts_digest(current_basis, references) != facts_digest(
            candidate.original, candidate.references
        ):
            raise LifecycleFailure("PREVIEW_STALE", "Facts changed before physical execution")
        decision = self._decision(
            intent.action, fence.original, references, now, allowed_pending=intent.id
        )
        if not decision.eligible:
            raise LifecycleFailure(
                "RETENTION_PROTECTED", "Current authority protects this original"
            )
        permit = EffectPermit(
            operation_id=intent.id,
            reference=intent.reference,
            scope=intent.scope,
            action=intent.action,
            lease_token=uuid4(),
            attempt=1,
            named_decider_id=intent.named_decider_id,
            authorization_revision=authorization.access_revision,
            lifecycle_revision=fence.original.revision + 1,
            inventory_revision=fence.original.inventory_revision,
            reference_read_version=references.read_version,
            policy_digest=digest(self.policy),
            issued_at=now,
            expires_at=min(now + self.policy.effect_timeout, authorization.expires_at)
            if authorization.expires_at
            else now + self.policy.effect_timeout,
        )
        updated = replace(
            intent,
            revision=intent.revision + 1,
            state=IntentState.IN_FLIGHT,
            updated_at=now,
            permit=permit,
        )
        self._change(
            fence, intent, updated, replace(fence.original, revision=fence.original.revision + 1)
        )
        return permit

    def validate_effect(self, context: object, permit: EffectPermit):
        """Acquire current gate in the caller transaction immediately around physical I/O.

        A controlled transport MUST keep this fence held through its bounded byte-
        preserving effect. Every protection writer uses the same gate. Releasing
        it before apply is invalid; the storage marker also fences stale workers.
        """
        fence, intent = self._locked_operation(permit.operation_id)
        now = self.clock.now()
        authorization = self._effect_authority(context, fence, intent, now)
        if intent.state != IntentState.IN_FLIGHT or intent.permit != permit:
            raise LifecycleFailure(
                "EFFECT_ALREADY_ATTEMPTED", "Only the stored in-flight attempt may apply"
            )
        references = self.references.read_under_fence(fence)
        now = self.clock.now()
        authorization = self._effect_authority(context, fence, intent, now)
        if now < permit.issued_at:
            raise LifecycleFailure("EFFECT_TIME_INVALID", "Server clock moved before permit issue")
        if permit.expires_at <= now:
            raise LifecycleFailure("EFFECT_PERMIT_EXPIRED", "Expired attempt needs observation")
        if authorization.access_revision != permit.authorization_revision or (
            permit.policy_digest != digest(self.policy)
        ):
            raise LifecycleFailure("POLICY_CHANGED", "Current authorization or policy changed")
        if fence.original.pending_intent_id != intent.id or (
            fence.original.revision != permit.lifecycle_revision
            or fence.original.inventory_revision != permit.inventory_revision
        ):
            raise LifecycleFailure(
                "FENCE_LOST", "Protection/lifecycle epoch changed before byte effect"
            )
        if references.read_version != permit.reference_read_version:
            raise LifecycleFailure("PREVIEW_STALE", "References changed before byte effect")
        if not self._decision(
            intent.action, fence.original, references, now, allowed_pending=intent.id
        ).eligible:
            raise LifecycleFailure(
                "RETENTION_PROTECTED", "Current protection forbids physical effect"
            )
        return fence

    def mark_unknown(self, context: object, intent_id: UUID) -> LifecycleIntent:
        """Expired in-flight lease becomes unknown; pending protection remains held."""
        fence, intent = self._locked_operation(intent_id)
        now = self.clock.now()
        self._effect_authority(context, fence, intent, now, reconcile=True)
        if intent.state == IntentState.UNKNOWN:
            return intent
        if intent.state != IntentState.IN_FLIGHT or intent.permit.expires_at > now:
            raise LifecycleFailure(
                "EFFECT_NOT_EXPIRED", "Only expired in-flight work becomes unknown"
            )
        if fence.original.pending_intent_id != intent.id:
            raise LifecycleFailure("FENCE_LOST", "Pending operation fence was lost")
        return self._change(
            fence,
            intent,
            replace(
                intent,
                revision=intent.revision + 1,
                state=IntentState.UNKNOWN,
                updated_at=now,
            ),
            replace(fence.original, revision=fence.original.revision + 1),
        )

    def record_effect(
        self,
        context: object,
        intent_id: UUID,
        receipt: EffectReceipt,
    ) -> LifecycleIntent:
        """Internal trusted adapter result, never an HTTP/model-supplied observation."""
        fence, intent = self._locked_operation(intent_id)
        now = self.clock.now()
        self._effect_authority(context, fence, intent, now, reconcile=True)
        if intent.state in (IntentState.APPLIED, IntentState.NOT_APPLIED):
            if receipt == intent.receipt:
                return intent
            raise LifecycleFailure(
                "EFFECT_RESULT_CONFLICT", "Completed effect has a different receipt"
            )
        if (
            intent.state not in (IntentState.IN_FLIGHT, IntentState.UNKNOWN)
            or intent.permit is None
        ):
            raise LifecycleFailure("EFFECT_NOT_STARTED", "No exact stored physical attempt exists")
        if fence.original.pending_intent_id != intent.id:
            raise LifecycleFailure("FENCE_LOST", "Pending operation fence was lost")
        if (
            receipt.operation_id != intent.id
            or receipt.reference != intent.reference
            or (receipt.scope != intent.scope or receipt.lease_token != intent.permit.lease_token)
        ):
            raise LifecycleFailure(
                "EFFECT_BINDING_MISMATCH", "Observation binds a different attempt"
            )
        current_refs = None
        if receipt.outcome == EffectOutcome.APPLIED and intent.action == LifecycleAction.QUARANTINE:
            current_refs = self.references.read_under_fence(fence)
        now = self.clock.now()
        self._effect_authority(context, fence, intent, now, reconcile=True)
        if receipt.observed_at < intent.permit.issued_at or receipt.observed_at > now:
            raise LifecycleFailure(
                "EFFECT_OBSERVATION_STALE", "Require current authoritative observation"
            )
        original = fence.original
        state = IntentState.UNKNOWN
        protection_reasons = ()
        if receipt.outcome == EffectOutcome.APPLIED:
            expected = (
                Disposition.QUARANTINED
                if intent.action == LifecycleAction.QUARANTINE
                else Disposition.ACTIVE
            )
            if receipt.observed_disposition != expected:
                raise LifecycleFailure(
                    "EFFECT_RESULT_CONFLICT", "Observed location differs from effect"
                )
            state = IntentState.APPLIED
            if intent.action == LifecycleAction.QUARANTINE:
                protection_reasons = self._decision(
                    intent.action,
                    original,
                    current_refs,
                    now,
                    allowed_pending=intent.id,
                ).reasons
            original = replace(
                original,
                disposition=expected,
                pending_intent_id=None,
                quarantined_at=(
                    receipt.observed_at
                    if expected == Disposition.QUARANTINED
                    else original.quarantined_at
                ),
            )
        elif receipt.outcome == EffectOutcome.NOT_APPLIED:
            if receipt.observed_disposition != original.disposition:
                raise LifecycleFailure(
                    "EFFECT_RESULT_CONFLICT", "No-effect proof differs from retained state"
                )
            state = IntentState.NOT_APPLIED
            original = replace(original, pending_intent_id=None)
        updated = replace(
            intent,
            revision=intent.revision + 1,
            state=state,
            updated_at=now,
            receipt=receipt,
            recovery_required=bool(protection_reasons),
            protection_reasons=protection_reasons,
        )
        return self._change(
            fence, intent, updated, replace(original, revision=original.revision + 1)
        )

    def cancel_pending(self, context: object, intent_id: UUID) -> LifecycleIntent:
        """Only work that has never acquired a physical permit can be cancelled."""
        fence, intent = self._locked_operation(intent_id)
        now = self.clock.now()
        authorization = self._authorize(context, fence.original, intent.action, now)
        if authorization.actor_kind != ActorKind.HUMAN or (
            authorization.named_decider_id != authorization.actor_id
        ):
            raise LifecycleFailure(
                "NAMED_CONFIRMATION_REQUIRED", "Current named cancellation required"
            )
        if intent.state == IntentState.CANCELLED:
            return intent
        if intent.state != IntentState.PENDING or intent.permit is not None:
            raise LifecycleFailure(
                "EFFECT_ALREADY_ATTEMPTED", "Attempted work requires observation"
            )
        if fence.original.pending_intent_id != intent.id:
            raise LifecycleFailure("FENCE_LOST", "Pending operation fence was lost")
        return self._change(
            fence,
            intent,
            replace(
                intent,
                revision=intent.revision + 1,
                state=IntentState.CANCELLED,
                updated_at=now,
            ),
            replace(
                fence.original,
                revision=fence.original.revision + 1,
                pending_intent_id=None,
            ),
        )
