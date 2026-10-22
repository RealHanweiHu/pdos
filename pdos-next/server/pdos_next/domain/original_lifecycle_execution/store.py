"""SQL ports use the caller transaction and the shared Product protection gate."""

from dataclasses import asdict, replace
from uuid import uuid4

from sqlalchemy import select

from pdos_next import models
from pdos_next.original_lifecycle.rules import digest
from pdos_next.original_lifecycle.types import (
    ActorKind,
    CurrentAuthorization,
    IntentState,
    LifecycleFailure,
    LifecycleFence,
    LifecycleScope,
    RequestBinding,
)
from pdos_next.request_proof import request_proof

from .codec import (
    decode_candidate,
    decode_intent,
    decode_state,
    encode_candidate,
    encode_intent,
    encode_state,
)
from .runtime import BoundFacts


def state_digest(state):
    data = asdict(state)
    data.pop("observed_at")
    return digest(data)


def fail(code="BINDING_MISMATCH", message="生命周期记录与当前对象范围不一致。"):
    raise LifecycleFailure(code, message)


class SqlLifecycleStore:
    def __init__(self, session, ctx, product_id, runtime, *, emit_transition=True):
        self.s, self.ctx, self.product_id, self.runtime = session, ctx, product_id, runtime
        self.scope = LifecycleScope(
            ctx.tenant_id, product_id, ctx.category_id if product_id is None else None
        )
        self.emit_transition = emit_transition
        self.request_reason = None
        self._fences = {}

    def gate(self):
        proof = request_proof(self.s)
        key = ("lifecycle_product", self.ctx, self.product_id)
        if key in proof.read_rows:
            return proof.read_rows[key]
        if self.product_id is None:
            from pdos_next.service import require_access

            return require_access(self.s, self.ctx, None, write=True, lock=True)
        product = self.s.scalar(
            select(models.Product)
            .where(
                models.Product.id == self.product_id, models.Product.tenant_id == self.ctx.tenant_id
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if product is None or product.category_id != self.ctx.category_id:
            fail("FORBIDDEN_SCOPE", "型号不在当前授权品类范围。")
        proof.read_rows[key] = product
        return product

    def _query(self, model):
        return (
            select(model)
            .where(
                model.tenant_id == self.ctx.tenant_id,
                model.category_id == self.ctx.category_id,
                model.product_id == self.product_id,
            )
            .execution_options(populate_existing=True)
        )

    def object_row(self, object_id):
        return self.s.scalar(
            self._query(models.LifecycleObject).where(models.LifecycleObject.id == object_id)
        )

    def _row_state(self, row):
        state = decode_state(row.state)
        if (
            row.id != state.reference.id
            or row.reference != encode_state(state)["value"]["reference"]
            or state.scope != self.scope
            or row.revision != state.revision
            or row.manual_hold != state.manual_hold
            or row.retention_until != state.retention_until
        ):
            fail()
        if row.owner_id != self.ctx.requester_id:
            fail("FORBIDDEN_SCOPE", "原件生命周期只由当前登记所有者办理。")
        return state

    def read_current(self, reference):
        self.gate()
        row = self.object_row(reference.id)
        previous = self._row_state(row) if row is not None else None
        if previous is not None and previous.reference != reference:
            fail()
        facts = self.runtime.read_facts(self.s, self.ctx, self.product_id, reference, previous)
        if not isinstance(facts, BoundFacts) or facts.owner_id != self.ctx.requester_id:
            fail("FORBIDDEN_SCOPE", "缺少当前原件所有者的权威事实。")
        current = facts.original
        if current.reference != reference or current.scope != self.scope:
            fail()
        if row is None:
            if current.revision != 1 or current.pending_intent_id is not None:
                fail()
            row = models.LifecycleObject(
                id=reference.id,
                tenant_id=self.ctx.tenant_id,
                category_id=self.ctx.category_id,
                product_id=self.product_id,
                owner_id=facts.owner_id,
                reference=encode_state(current)["value"]["reference"],
                revision=1,
                state=encode_state(current),
                manual_hold=current.manual_hold,
                retention_until=current.retention_until,
                protection_revision=1,
            )
            self.s.add(row)
            self.s.flush()
        else:
            if facts.owner_id != row.owner_id or (
                current.revision != previous.revision
                or current.disposition != previous.disposition
                or current.quarantined_at != previous.quarantined_at
                or current.pending_intent_id != previous.pending_intent_id
                or current.created_at != previous.created_at
            ):
                fail("FACTS_BINDING_MISMATCH", "事实读取不能重置生命周期位置或保护。")
            current = replace(
                current, manual_hold=row.manual_hold, retention_until=row.retention_until
            )
            if state_digest(current) != state_digest(previous):
                current = replace(current, revision=previous.revision + 1)
                row.revision, row.state = current.revision, encode_state(current)
                self.s.flush()
        return current

    def lock_current(self, reference):
        original = self.read_current(reference)
        fence = LifecycleFence(original, uuid4())
        self._fences[fence.token] = (original.revision, state_digest(original))
        return fence

    def _fenced(self, fence):
        if self._fences.get(fence.token) != (fence.original.revision, state_digest(fence.original)):
            fail("FENCE_LOST", "当前事务没有这个对象的保护锁。")
        row = self.object_row(fence.original.reference.id)
        if row is None or state_digest(self._row_state(row)) != state_digest(fence.original):
            fail("VERSION_CONFLICT", "当前生命周期版本已改变。")
        return row

    def save_candidate(self, candidate):
        if candidate.original.scope != self.scope:
            fail()
        self.read_current(candidate.original.reference)
        self.s.add(
            models.LifecycleCandidate(
                id=candidate.id,
                tenant_id=self.ctx.tenant_id,
                category_id=self.ctx.category_id,
                product_id=self.product_id,
                object_id=candidate.original.reference.id,
                actor_id=self.ctx.requester_id,
                document=encode_candidate(candidate),
            )
        )
        self.s.flush()

    def get_candidate(self, candidate_id):
        row = self.s.scalar(
            self._query(models.LifecycleCandidate).where(
                models.LifecycleCandidate.id == candidate_id
            )
        )
        if row is None or row.actor_id != self.ctx.requester_id:
            fail("SOURCE_UNAVAILABLE", "候选不在当前具名所有者范围。")
        candidate = decode_candidate(row.document)
        if (
            candidate.id != row.id
            or candidate.original.reference.id != row.object_id
            or candidate.original.scope != self.scope
        ):
            fail()
        object_row = self.object_row(row.object_id)
        if (
            object_row is None
            or self._row_state(object_row).reference != candidate.original.reference
        ):
            fail()
        return candidate

    def intent_row(self, intent_id):
        row = self.s.scalar(
            self._query(models.LifecycleIntentRecord).where(
                models.LifecycleIntentRecord.id == intent_id
            )
        )
        if row is None or row.actor_id != self.ctx.requester_id:
            fail("SOURCE_UNAVAILABLE", "意图不在当前具名所有者范围。")
        intent = decode_intent(row.document)
        if (
            row.id != intent.id
            or row.object_id != intent.reference.id
            or row.revision != intent.revision
            or row.intent_digest != intent.intent_digest
            or row.actor_id != intent.named_decider_id
            or intent.scope != self.scope
        ):
            fail()
        object_row = self.object_row(row.object_id)
        if object_row is None or self._row_state(object_row).reference != intent.reference:
            fail()
        return row

    def get_intent(self, intent_id):
        return decode_intent(self.intent_row(intent_id).document)

    def find_intent(self, scope, intent_digest):
        if scope != self.scope:
            fail()
        row = self.s.scalar(
            self._query(models.LifecycleIntentRecord).where(
                models.LifecycleIntentRecord.intent_digest == intent_digest
            )
        )
        return self.get_intent(row.id) if row is not None else None

    def find_request(self, scope, actor_id, key):
        if scope != self.scope or actor_id != self.ctx.requester_id:
            fail()
        row = self.s.scalar(
            self._query(models.LifecycleRequest).where(
                models.LifecycleRequest.actor_id == actor_id, models.LifecycleRequest.key == key
            )
        )
        if row is None:
            return None
        intent = self.get_intent(row.intent_id)
        if row.object_id != intent.reference.id:
            fail()
        return RequestBinding(scope, actor_id, row.key, row.fingerprint, row.intent_id)

    def remember_request(self, fence, binding):
        self._fenced(fence)
        if binding.scope != self.scope or binding.actor_id != self.ctx.requester_id:
            fail()
        intent = self.get_intent(binding.intent_id)
        if intent.reference != fence.original.reference:
            fail()
        prior = self.find_request(binding.scope, binding.actor_id, binding.key)
        if prior is not None:
            if prior != binding:
                fail("IDEMPOTENCY_CONFLICT", "相同请求编号对应了不同生命周期候选。")
            return
        self.s.add(
            models.LifecycleRequest(
                tenant_id=self.ctx.tenant_id,
                category_id=self.ctx.category_id,
                product_id=self.product_id,
                object_id=intent.reference.id,
                actor_id=binding.actor_id,
                key=binding.key,
                fingerprint=binding.fingerprint,
                intent_id=intent.id,
            )
        )
        self.s.flush()

    def stage(self, fence, intent, original, request):
        row = self._fenced(fence)
        if (
            original.reference != fence.original.reference
            or original.scope != self.scope
            or original.revision != fence.original.revision + 1
            or original.pending_intent_id != intent.id
            or intent.reference != original.reference
            or intent.scope != self.scope
            or intent.named_decider_id != self.ctx.requester_id
            or intent.revision != 1
            or intent.state != IntentState.PENDING
            or intent.permit is not None
            or request.intent_id != intent.id
            or original
            != replace(
                fence.original, revision=fence.original.revision + 1, pending_intent_id=intent.id
            )
        ):
            fail()
        candidate = self.get_candidate(intent.candidate_id)
        if candidate.digest != intent.candidate_digest or candidate.action != intent.action:
            fail()
        consumed = self.s.scalar(
            self._query(models.LifecycleIntentRecord).where(
                models.LifecycleIntentRecord.document["value"]["candidate_id"].astext
                == str(intent.candidate_id)
            )
        )
        if consumed is not None:
            fail("PREVIEW_CONSUMED", "候选已被消费。")
        if (
            not isinstance(self.request_reason, str)
            or not self.request_reason
            or len(self.request_reason) > 2000
        ):
            fail("NAMED_CONFIRMATION_REQUIRED", "生命周期意图需要共同确认绑定的理由。")
        self.s.add(
            models.LifecycleIntentRecord(
                id=intent.id,
                tenant_id=self.ctx.tenant_id,
                category_id=self.ctx.category_id,
                product_id=self.product_id,
                object_id=intent.reference.id,
                actor_id=intent.named_decider_id,
                revision=intent.revision,
                intent_digest=intent.intent_digest,
                document=encode_intent(intent),
                reason=self.request_reason,
            )
        )
        self.s.flush()
        self.remember_request(fence, request)
        row.revision, row.state = original.revision, encode_state(original)
        self.s.flush()
        return intent

    def change(self, fence, before, after, original):
        row = self._fenced(fence)
        record = self.intent_row(before.id)
        if decode_intent(record.document) != before or (
            after.id != before.id
            or after.reference != before.reference
            or after.scope != before.scope
            or after.named_decider_id != before.named_decider_id
            or after.intent_digest != before.intent_digest
            or after.candidate_id != before.candidate_id
            or after.candidate_digest != before.candidate_digest
            or after.action != before.action
            or after.created_at != before.created_at
            or after.policy_version != before.policy_version
            or after.authorization_revision != before.authorization_revision
            or after.revision != before.revision + 1
            or original.reference != fence.original.reference
            or original.scope != self.scope
            or original.revision != fence.original.revision + 1
            or replace(
                original,
                revision=fence.original.revision,
                disposition=fence.original.disposition,
                quarantined_at=fence.original.quarantined_at,
                pending_intent_id=fence.original.pending_intent_id,
            )
            != fence.original
        ):
            fail("VERSION_CONFLICT", "生命周期状态转换绑定或版本失效。")
        if self.emit_transition and self.runtime.transition_hook is None:
            fail("LIFECYCLE_AUDIT_UNAVAILABLE", "生命周期工作器缺少共同审计事务接口。")
        record.revision, record.document = after.revision, encode_intent(after)
        row.revision, row.state = original.revision, encode_state(original)
        self.s.flush()
        if self.emit_transition:
            self.runtime.transition_hook(self.s, self.ctx, before, after, original)
        return after


class SqlLifecycleAuthority:
    def __init__(self, store):
        self.store = store

    def authorize(self, server_context, reference, action, now, *, decision=None):
        store, ctx = self.store, self.store.ctx
        if server_context != ctx:
            fail("FORBIDDEN_SCOPE", "生命周期上下文必须由服务器固定。")
        product = store.gate()
        row = store.object_row(reference.id)
        if row is None or store._row_state(row).reference != reference:
            fail()
        # Worker authority is supplied separately by the server; clients cannot select it.
        if decision is not None and store.runtime.service_authorize is not None:
            authorization = store.runtime.service_authorize(
                store.s, ctx, store.product_id, reference, action, now, decision
            )
            if (
                not isinstance(authorization, CurrentAuthorization)
                or authorization.actor_kind != ActorKind.SERVICE
                or authorization.actor_id != ctx.actor_id
                or authorization.scope != store.scope
                or authorization.reference != reference
                or authorization.action != action
                or authorization.named_decider_id != row.owner_id
                or authorization.decision_intent_id != decision.id
            ):
                fail("WORKER_AUTHORITY_REQUIRED", "工作器授权未绑定当前具名意图。")
            return authorization
        proof = request_proof(store.s)
        key = ("lifecycle_authority", ctx, product.category_id)
        common = proof.authority.get(
            (ctx.tenant_id, product.category_id, ctx.actor_id, ctx.requester_id)
        )
        if key not in proof.read_rows and common and common["locked"] and "rows" in common:
            proof.read_rows[key] = next(
                (
                    (principal, grant)
                    for principal, grant in common["rows"]
                    if principal.id == ctx.actor_id
                ),
                (None, None),
            )
        if key not in proof.read_rows:
            principal = store.s.scalar(
                select(models.Principal)
                .where(
                    models.Principal.id == ctx.actor_id, models.Principal.tenant_id == ctx.tenant_id
                )
                .with_for_update(read=True)
            )
            grant = store.s.scalar(
                select(models.Grant)
                .where(
                    models.Grant.principal_id == ctx.actor_id,
                    models.Grant.tenant_id == ctx.tenant_id,
                    models.Grant.category_id == product.category_id,
                )
                .with_for_update(read=True)
            )
            proof.read_rows[key] = (principal, grant)
        principal, grant = proof.read_rows[key]
        if (
            ctx.run_id is not None
            or ctx.actor_id != ctx.requester_id
            or principal is None
            or not principal.active
            or principal.kind != "human"
            or grant is None
            or not grant.can_write
            or (grant.expires_at is not None and grant.expires_at <= now)
        ):
            fail("NAMED_CONFIRMATION_REQUIRED", "生命周期操作需要当前具名本人及产品写权限。")
        revision = digest(
            [
                principal.id,
                principal.access_epoch,
                grant.id,
                grant.access_epoch,
                grant.can_write,
                grant.expires_at,
            ]
        )
        return CurrentAuthorization(
            reference,
            store.scope,
            ctx.actor_id,
            ActorKind.HUMAN,
            action,
            revision,
            grant.expires_at,
            ctx.actor_id,
        )
