"""Read-only formal action fulfillment from actual selected implementation originals.

The default startup installs this read-only adapter. A saved completion or
classification alone cannot produce an attestation. New Run applicability, effectiveness and
closing remain with their separate owners.
"""

# Common registry initializes before these domain owners.
# ruff: noqa: I001
from weakref import ref
from types import SimpleNamespace
from uuid import UUID

from pdos_next import service as common
from pdos_next import change_controlled_owner as controlled
from pdos_next import change_order_service as orders
from pdos_next import change_order_store as store
from pdos_next.capa_applicability_owner import (
    ActualActionAttestation,
    ActualActionFulfillmentOwner,
)
from pdos_next.change_implementation_owner import ApprovedImplementationOwner, original_occurrence
from pdos_next.clock import deadline_current, earliest_deadline
from pdos_next.clock import now
from pdos_next.domain.capa_effectiveness import anchor as anchors
from pdos_next.domain.capa_effectiveness.fact_atom_storage import _same_uow, _uow
from pdos_next.domain.capa_effectiveness.fact_sources_owner import _wire
from pdos_next.domain.capa_effectiveness.facts import _action_bindings
from pdos_next.domain.capa_verification.service import load_followup_basis
from pdos_next.domain.change_execution import service as change
from pdos_next.domain.quality_execution.evidence import merge_reads, union_sources
from pdos_next.errors import DomainError
from pdos_next.schemas.verification.contracts import SourceRef


def require(value, code="ACTION_FULFILLMENT_OWNER_REQUIRED", status=503):
    if not value:
        raise DomainError(code, "措施履行须精确绑定实际完成、批准范围及已保存实施原件。", status)


def _current_action_items(s, ctx, pid, origin, request, order, action_id):
    """Start with every immutable approved item, not today's visible action rows.

    The consumed order review pins each actual Selection's common receipt. Read
    those exact original Facts before choosing this action's obligations. A
    missing/rebound Current can invalidate an obligation, never remove it.
    The caller rechecks the actual order/dual approvals around all owner IO.
    """
    prepared = orders._one(
        s,
        store.ChangeOrderRecord,
        store.ChangeOrderRecord.tenant_id == ctx.tenant_id,
        store.ChangeOrderRecord.product_id == pid,
        store.ChangeOrderRecord.project_id == origin.scope.project_id,
        store.ChangeOrderRecord.change_id == request.id,
        store.ChangeOrderRecord.order_id == order.id,
    )
    require(
        prepared.content_sha256 == order.content_digest
        and prepared.order_snapshot["plan"] == order.plan.model_dump(mode="json"),
        "ACTION_IMPLEMENTATION_MISMATCH",
        409,
    )
    values = prepared.input_snapshot.get("review", {}).get("selection")
    require(
        type(values) is list and len(values) == len(order.plan.items),
        "ACTION_IMPLEMENTATION_MISMATCH",
        409,
    )
    proofs = tuple(store.SelectionProof.model_validate(value) for value in values)
    require(
        len({value.item_sha256 for value in proofs}) == len(proofs),
        "ACTION_IMPLEMENTATION_MISMATCH",
        409,
    )
    obligations = []
    fact = controlled.models.ChangeSelectionFact
    for item in order.plan.items:
        selected = [proof for proof in proofs if proof.item_sha256 == orders.digest(item)]
        require(len(selected) == 1, "ACTION_IMPLEMENTATION_MISMATCH", 409)
        proof = selected[0]
        receipt = proof.owner_proof.get("receipt", {})
        require(
            proof.scope == request.scope.model_dump(mode="json")
            and proof.nature == origin.nature
            and receipt.get("subject_type") == controlled.models.SELECTION_FAMILY
            and type(receipt.get("subject_revision")) is int
            and receipt["subject_revision"] > 0
            and bool(receipt.get("subject_id")),
            "ACTION_IMPLEMENTATION_MISMATCH",
            409,
        )
        original = orders._one(
            s,
            fact,
            fact.tenant_id == ctx.tenant_id,
            fact.product_id == pid,
            fact.project_id == origin.scope.project_id,
            fact.change_id == request.id,
            fact.item_id == item.id,
            fact.id == UUID(str(receipt["subject_id"])),
            fact.revision == receipt["subject_revision"],
        )
        material = controlled.models.SelectionMaterial.model_validate(original.material)
        require(
            material.item == item
            and material.scope == request.scope
            and material.change_id == request.id
            and material.purpose == origin.purpose
            and material.nature == origin.nature
            and material.status == "applicable"
            and original.material_sha256 == orders.digest(material)
            and original.item_sha256 == proof.item_sha256
            and (
                original.issue_id,
                original.capa_id,
                original.action_id,
                original.action_sha256,
                original.intent_id,
                original.status,
            )
            == (
                material.issue_id,
                material.capa_id,
                material.action_id,
                material.action_sha256,
                item.intent.id,
                "applicable",
            ),
            "ACTION_IMPLEMENTATION_MISMATCH",
            409,
        )
        group = controlled.common_group(
            s,
            ctx,
            pid,
            original,
            operation=controlled.models.SELECTION_OPERATION,
            event=controlled.models.SELECTION_EVENT,
            actor=original.actor_id,
        )
        # Use the same DTO JSON conversion as the saved order review (including
        # UUIDs and aware timestamps inside the common receipt/audit/outbox).
        actual_group = proof.model_copy(update={"owner_proof": group}).model_dump(mode="json")[
            "owner_proof"
        ]
        require(actual_group == proof.owner_proof, "ACTION_IMPLEMENTATION_MISMATCH", 409)
        # Selection's stored original hash and confirmation payload hash are
        # deliberately distinct. Reuse the actual consumed T2 proof verifier.
        controlled._atom_proof(
            s,
            ctx,
            pid,
            SimpleNamespace(
                **{**original.__dict__, "material_sha256": original.confirmation_material_sha256}
            ),
            group,
        )
        if material.action_id != action_id:
            continue
        require(
            (material.issue_id, material.capa_id) == (origin.issue_id, origin.issue.capa.id),
            "ACTION_IMPLEMENTATION_MISMATCH",
            409,
        )
        pointer, current = controlled.selection_pointer(
            s, ctx, pid, request.scope, request.id, item.id
        )
        require(
            pointer is not None
            and current is not None
            and (current.id, current.revision, current.material_sha256, current.material)
            == (original.id, original.revision, original.material_sha256, original.material)
            and all(
                getattr(current, field) == getattr(original, field)
                for field in (
                    "item_id",
                    "intent_id",
                    "issue_id",
                    "capa_id",
                    "action_id",
                    "action_sha256",
                    "status",
                )
            ),
            "ACTION_IMPLEMENTATION_MISMATCH",
            409,
        )
        obligations.append(current)
    require(bool(obligations), "ACTION_IMPLEMENTATION_MISMATCH", 409)
    return tuple(obligations)


class ApprovedChangeActionFulfillmentOwner:
    """Explicit engine-bound adapter for applicable, actually implemented actions.

    ``selection.sources`` must name all actual Occurrence originals for one
    approved order/action. Unknown/not-applicable selections need their own
    actual judgment owner; this adapter never derives them from absence.
    """

    def __init__(self, engine, *, epoch=1):
        require(type(epoch) is int and epoch > 0)
        self.engine, self.epoch = engine, epoch
        self.implementation = ApprovedImplementationOwner(engine)
        self.action_intent = controlled.ApprovedActionIntentOwner()
        self._reads = {}

    def runtime_stamp(self, s):
        require(s.get_bind() is self.engine)
        return common.digest(
            {
                "epoch": self.epoch,
                "change": change._runtime_stamp(s),
                "order": orders.runtime(s)[0],
                "implementation": [
                    id(self.implementation),
                    id(type(self.implementation).read),
                    id(type(self.implementation).refresh),
                ],
                "intent": [
                    id(self.action_intent),
                    id(type(self.action_intent).read),
                    id(type(self.action_intent).refresh),
                ],
            }
        )

    def read(
        self,
        s,
        ctx,
        pid,
        selection,
        *,
        anchor,
        candidate,
        rule,
        observations,
        action,
        completion,
        classification_material,
    ):
        require(selection.conclusion == "applicable", "ACTION_FULFILLMENT_MISMATCH", 409)
        uow, caller_hash, stamp = _uow(s), common.digest(vars(ctx)), self.runtime_stamp(s)
        with s.no_autoflush:
            origin = anchor.origin
            require(
                origin.scope.tenant_id == ctx.tenant_id and origin.scope.product_id == pid,
                "FORBIDDEN_SCOPE",
                403,
            )
            caller, caller_until = controlled._caller(s, ctx, pid, write=False)
            _, project_stamp = controlled._project(s, ctx, origin.scope)
            basis = load_followup_basis(
                s, ctx, pid, origin.issue_id, origin.ref.revision, write=False
            )
            binding = next((v for v in basis.actions if v.action_id == selection.action_id), None)
            expected = next(
                (v for v in _action_bindings(anchor) if v.action_id == selection.action_id), None
            )
            saved_action = next(
                (v for v in origin.issue.capa.actions if v.id == selection.action_id), None
            )
            require(
                binding is not None
                and binding == expected
                and basis.scope == origin.scope
                and basis.capa_id == origin.issue.capa.id
                and basis.purpose == origin.purpose
                and basis.nature == origin.nature
                and saved_action == action
                and action.completion == completion
                and binding.completion_sha256 == common.digest(completion.model_dump(mode="json"))
                and binding.completed_at == completion.at
                and binding.executor_id == completion.executor_id == action.executor_id,
                "ACTION_COMPLETION_MISMATCH",
                409,
            )
            event, event_reads, event_basis = ActualActionFulfillmentOwner._completion(
                s, ctx, pid, origin, completion
            )
            require(
                (event.issue_id, event.capa_id, event.action_id, event.executor_id, event.purpose)
                == (
                    origin.issue_id,
                    basis.capa_id,
                    binding.action_id,
                    binding.executor_id,
                    basis.purpose,
                ),
                "ACTION_COMPLETION_MISMATCH",
                409,
            )
            refs = anchors.canonical_sources(selection.sources)
            require(
                bool(refs)
                and all(source.kind == "artifact" for source in refs)
                and set(refs) <= set(anchors.canonical_sources(completion.evidence)),
                "ACTION_IMPLEMENTATION_MISMATCH",
                409,
            )
            occurrences = tuple(original_occurrence(s, ctx, pid, source)[0] for source in refs)
            require(
                len({value.item_id for value in occurrences}) == len(occurrences),
                "ACTION_IMPLEMENTATION_MISMATCH",
                409,
            )
            first = occurrences[0]
            pointer, current = orders.current_fixed(s, ctx, pid, first.change_id)
            request = orders.snapshot(current)
            current_stamp = (pointer.id, current.id, current.request_sha256)
            order = next((value for value in request.orders if value.id == first.order_id), None)
            require(order is not None and request.scope == basis.scope)
            approval_until = controlled.approved_order(s, ctx, pid, request, order)
            required_items = _current_action_items(
                s, ctx, pid, origin, request, order, binding.action_id
            )
            require(
                {value.item_id for value in occurrences} == {row.item_id for row in required_items},
                "ACTION_IMPLEMENTATION_MISMATCH",
                409,
            )
            executions, intents, saved_material = [], [], []
            sources = union_sources(
                basis.sources, completion.evidence, (completion.at.source,), refs
            )
            reads = merge_reads(basis.required_source_read_set, event_reads)
            deadlines = [
                caller_until,
                rule.valid_until,
                approval_until,
            ]
            for source, occurrence in zip(refs, occurrences, strict=True):
                require(
                    occurrence.scope == basis.scope
                    and occurrence.issue_id == basis.issue_id
                    and occurrence.capa_id == basis.capa_id
                    and occurrence.action_id == binding.action_id
                    and occurrence.action_sha256 == binding.action_sha256
                    and occurrence.executor_id == binding.executor_id
                    and occurrence.purpose == basis.purpose
                    and occurrence.nature == basis.nature
                    and (occurrence.change_id, occurrence.order_id) == (request.id, order.id)
                    and occurrence.outcome == "succeeded"
                    and bool(occurrence.outputs)
                    and occurrence.occurred_at <= completion.at.occurred_at,
                    "ACTION_IMPLEMENTATION_MISMATCH",
                    409,
                )
                history = [
                    value for value in order.implementations if value.item_id == occurrence.item_id
                ]
                require(
                    bool(history)
                    and history[-1].id == occurrence.implementation_id
                    and history[-1].outcome == "succeeded",
                    "ACTION_IMPLEMENTATION_MISMATCH",
                    409,
                )
                capture = orders._one(
                    s,
                    store.ImplementationCapture,
                    store.ImplementationCapture.tenant_id == ctx.tenant_id,
                    store.ImplementationCapture.product_id == pid,
                    store.ImplementationCapture.project_id == basis.scope.project_id,
                    store.ImplementationCapture.change_id == request.id,
                    store.ImplementationCapture.order_id == order.id,
                    store.ImplementationCapture.item_id == occurrence.item_id,
                    store.ImplementationCapture.fact_id == occurrence.implementation_id,
                    store.ImplementationCapture.executor_id == binding.executor_id,
                )
                require(
                    capture.occurrence_snapshot == occurrence.model_dump(mode="json")
                    and bool(capture.sources)
                    and SourceRef.model_validate(capture.sources[0]) == source,
                    "ACTION_IMPLEMENTATION_MISMATCH",
                    409,
                )
                atom = orders._one(
                    s,
                    store.ChangeImplementationRecord,
                    store.ChangeImplementationRecord.tenant_id == ctx.tenant_id,
                    store.ChangeImplementationRecord.product_id == pid,
                    store.ChangeImplementationRecord.project_id == basis.scope.project_id,
                    store.ChangeImplementationRecord.change_id == request.id,
                    store.ChangeImplementationRecord.order_id == order.id,
                    store.ChangeImplementationRecord.item_id == occurrence.item_id,
                    store.ChangeImplementationRecord.fact_id == occurrence.implementation_id,
                    store.ChangeImplementationRecord.capture_id == capture.id,
                )
                executed = self.implementation.read(
                    s, ctx, pid, implementation_version_id=atom.change_version_id
                )
                intended = self.action_intent.read(
                    s,
                    ctx,
                    pid,
                    change_id=request.id,
                    order_id=order.id,
                    item_id=occurrence.item_id,
                    action_id=binding.action_id,
                )
                require(
                    executed.implementation.id == atom.id
                    and executed.version.id == atom.change_version_id
                    and executed.occurrence == occurrence
                    and intended.action_id == binding.action_id
                    and intended.order_id == order.id
                    and intended.item_id == occurrence.item_id
                    and intended.selection.scope == basis.scope.model_dump(mode="json")
                    and intended.selection.applicable is True
                    and intended.selection.nature == basis.nature
                    and intended.selection_id
                    == next(row.id for row in required_items if row.item_id == occurrence.item_id)
                    and intended.action_sha256 == binding.action_sha256
                    and intended.executor_id == binding.executor_id
                    and intended.intent_id == occurrence.intent_id,
                    "ACTION_IMPLEMENTATION_MISMATCH",
                    409,
                )
                executions.append(executed)
                intents.append(intended)
                saved_material.append(
                    {"implementation": executed.material, "selection": intended.__dict__}
                )
                sources = union_sources(
                    sources,
                    tuple(SourceRef.model_validate(v) for v in executed.version.sources),
                    intended.selection.sources,
                )
                reads = merge_reads(
                    reads,
                    executed.version.required_source_read_set,
                    intended.selection.required_source_read_set,
                )
                deadlines.extend((executed.valid_until, intended.selection.valid_until))
            sources = union_sources(sources)
            reads = merge_reads(reads, change._source_reads(sources))
            safety = controlled._source_guard(
                s, ctx, pid, basis.visibility, basis.owner_id, reads, sources
            )
            for executed, intended in zip(executions, intents, strict=True):
                require(
                    self.implementation.refresh(s, ctx, pid, executed).material
                    == executed.material,
                    "SOURCE_STALE",
                    409,
                )
                refreshed_intent = self.action_intent.refresh(s, ctx, pid, intended)
                require(
                    _wire(refreshed_intent.__dict__) == _wire(intended.__dict__),
                    "SOURCE_STALE",
                    409,
                )
            final_basis = load_followup_basis(
                s, ctx, pid, origin.issue_id, origin.ref.revision, write=False
            )
            final_event, final_reads, final_event_basis = ActualActionFulfillmentOwner._completion(
                s, ctx, pid, origin, completion
            )
            final_items = _current_action_items(
                s, ctx, pid, origin, request, order, binding.action_id
            )
            require(
                final_basis == basis
                and (final_event, final_reads, final_event_basis)
                == (event, event_reads, event_basis)
                and [(v.id, v.item_id, v.revision) for v in final_items]
                == [(v.id, v.item_id, v.revision) for v in required_items],
                "SOURCE_STALE",
                409,
            )
            late_pointer, late = orders.current_fixed(s, ctx, pid, request.id)
            require(
                (late_pointer.id, late.id, late.request_sha256) == current_stamp,
                "SOURCE_STALE",
                409,
            )
            deadlines.append(controlled.approved_order(s, ctx, pid, request, order))
            require(
                controlled.same(
                    controlled._source_guard(
                        s, ctx, pid, basis.visibility, basis.owner_id, reads, sources, io=False
                    ),
                    safety,
                ),
                "SOURCE_STALE",
                409,
            )
            final_caller, final_until = controlled._caller(s, ctx, pid, write=False)
            require(
                final_caller == caller
                and controlled._project(s, ctx, basis.scope)[1] == project_stamp
                and self.runtime_stamp(s) == stamp,
                "SOURCE_STALE",
                409,
            )
            deadlines.append(final_until)
            final_pointer, final_change = orders.current_fixed(s, ctx, pid, request.id)
            require(
                (final_pointer.id, final_change.id, final_change.request_sha256) == current_stamp,
                "SOURCE_STALE",
                409,
            )
            _same_uow(s, uow, ctx, caller_hash)
            until = earliest_deadline(*deadlines)
            require(deadline_current(until), "SOURCE_STALE", 409)
            material = _wire(
                {
                    "kind": "approved_change_action_fulfillment_v1",
                    "runtime": stamp,
                    "basis_sha256": basis.basis_sha256,
                    "anchor_sha256": anchor.anchor_sha256,
                    "action": binding,
                    "completion": completion,
                    "completion_source_basis": event_basis,
                    "change_current": current_stamp,
                    "items": saved_material,
                    "source_basis": safety,
                    "classification_input_sha256": common.digest(classification_material),
                }
            )
            proof = ActualActionAttestation(
                s,
                ctx,
                pid,
                anchor.anchor_sha256,
                binding,
                "formal_change",
                "applicable",
                refs,
                material,
                tuple(anchors.canonical_reads(reads)),
                now(),
                until,
            )
            key = id(proof)
            self._reads[key] = (
                ref(proof, lambda _: self._reads.pop(key, None)),
                uow,
                caller_hash,
                common.digest(material),
                common.digest(_wire(selection)),
            )
            return proof

    def refresh(self, s, ctx, pid, selection, previous, **kwargs):
        saved = self._reads.get(id(previous))
        require(
            saved is not None
            and saved[0]() is previous
            and type(previous) is ActualActionAttestation
            and previous.session is s
            and previous.caller is ctx
            and previous.product_id == pid
        )
        _same_uow(s, saved[1], ctx, saved[2])
        require(
            common.digest(previous.owner_material) == saved[3]
            and common.digest(_wire(selection)) == saved[4],
            "SOURCE_STALE",
            409,
        )
        current = self.read(s, ctx, pid, selection, **kwargs)
        require(
            current.owner_material == previous.owner_material
            and current.owner_refs == previous.owner_refs
            and current.reads == previous.reads
            and current.valid_until == previous.valid_until
            and current.time_constraints == previous.time_constraints,
            "SOURCE_STALE",
            409,
        )
        return current
