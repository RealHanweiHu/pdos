"""Host-only trusted publication in the caller's original transaction/common tail."""

from copy import deepcopy
from uuid import uuid4

from sqlalchemy import select

import pdos_next.models  # noqa: F401 - complete model registration before runtime imports
from pdos_next import change_controlled_owner as controlled
from pdos_next import service as common
from pdos_next.change_implementation_owner import common_group
from pdos_next.change_order_service import _one
from pdos_next.clock import earliest_deadline
from pdos_next.contracts import Command
from pdos_next.domain.capa_effectiveness.fact_atom_storage import _same_uow, _uow
from pdos_next.domain.change_control.rules import digest
from pdos_next.domain.change_execution import service as old
from pdos_next.models import Product, Receipt, RequestKey
from pdos_next.schemas.verification.contracts import Scope

from . import models, owner, registry, trust
from .schemas import EVENT, FAMILY, OPERATION, CoverageImport, CoverageMaterial
from .trust import require


def trusted_import(s, ctx, pid, issuer, payload, *, command_id, request_key):
    """No public payload registry/T1/T2, new issuer, qualification, commit or callback.

    Exceptions require the caller to roll back its whole transaction, including
    pending domain/common effects. Root adds deferred database atom constraints.
    """
    data = CoverageImport.model_validate(payload)
    require(type(issuer) is trust.CoverageIssuer, "COVERAGE_TRUSTED_ISSUER_REQUIRED", 403)
    require(common.EVENTS.get(OPERATION) == EVENT, "COVERAGE_PUBLICATION_TAIL_REQUIRED", 503)
    uow, caller_hash = _uow(s), common.digest(vars(ctx))
    owner.quiet(s)
    product = _one(s, Product, Product.tenant_id == ctx.tenant_id, Product.id == pid, lock=True)
    scope = Scope(tenant_id=ctx.tenant_id, product_id=pid, project_id=data.project_id)
    caller, caller_until = controlled._caller(s, ctx, pid, write=True)
    _, project_stamp = controlled._project(s, ctx, scope)
    # Bind exact Current/scope before original IO. The actual registry below
    # proves every owner once; the final dependency clock fences that proof.
    owner.binding(s, ctx, pid, data.change_id, data.purpose, lock=True, verify_sources=False)
    value, _ = controlled.original(s, ctx, pid, data.source, CoverageMaterial)
    require(
        value.scope == scope
        and value.purpose == data.purpose
        and value.change_id == data.change_id
        and value.publisher_id == ctx.requester_id,
        status=403,
    )
    concrete = trust.check(s.get_bind(), scope, data.source, value, supplied=issuer)
    issuer_stamp, runtime = trust.stamp(concrete), old._runtime_stamp(s)
    auth, auth_until = controlled.authority(
        s, ctx, pid, scope, "change.impact.compute", data.purpose
    )
    require(value.nature == ("synthetic" if auth.get("synthetic") else "real"), status=403)
    row, request, _, binding = owner.binding(
        s,
        ctx,
        pid,
        data.change_id,
        data.purpose,
        material=value,
        lock=True,
        verify_sources=False,
    )
    # A new publication may anchor a still-current fixed origin, or its unchanged
    # canonical successors, never a user-supplied alternative root/version.
    epoch = owner.dependency_epoch(s, ctx, pid)
    temporal_stamp, temporal_until = owner.temporal(s, ctx, pid, scope)
    owned = registry.read_registry(s, ctx, pid, request)
    require(
        owned.closure_sha256 == value.closure_sha256
        and {v.identity for v in value.nodes}
        == {
            n["ref"]["kind"]
            + ":"
            + n["ref"]["id"]
            + ":"
            + str(n["ref"]["revision"])
            + ":"
            + (n["ref"]["key"] or "")
            for n in owned.projection["nodes"]
        }
    )
    sources = tuple(dict.fromkeys((data.source, *owned.sources, *request.sources)))
    reads = controlled._reads(
        old._source_reads(sources), owned.reads, auth["required_source_read_set"]
    )
    require(bool(reads), "MISSING_REQUIRED_EVIDENCE", 422)
    artifact_basis = controlled._source_guard(
        s, ctx, pid, value.visibility, value.owner_id, reads, sources
    )
    source_basis = {
        "artifact_basis": artifact_basis,
        "closure_sha256": owned.closure_sha256,
        "dependency_epoch": epoch,
        "temporal_sha256": temporal_stamp,
    }
    fingerprint = common.digest(
        {
            "operation": OPERATION,
            "tenant": str(ctx.tenant_id),
            "product": str(pid),
            "actor": str(ctx.requester_id),
            "issuer": issuer_stamp,
            "payload": data.model_dump(mode="json"),
        }
    )
    keys = list(
        s.scalars(
            select(RequestKey)
            .where(
                RequestKey.tenant_id == ctx.tenant_id,
                RequestKey.actor_id == ctx.requester_id,
                RequestKey.key == request_key,
            )
            .limit(2)
            .execution_options(populate_existing=True, autoflush=False)
        )
    )
    require(
        len(keys) <= 1 and (not keys or keys[0].digest == fingerprint), "DUPLICATE_INTENT_CONFLICT"
    )
    receipts = list(
        s.scalars(
            select(Receipt)
            .where(
                Receipt.tenant_id == ctx.tenant_id,
                Receipt.product_id == pid,
                Receipt.operation == OPERATION,
                Receipt.actor_id == ctx.actor_id,
                Receipt.intent_digest == fingerprint,
            )
            .limit(2)
            .execution_options(populate_existing=True, autoflush=False)
        )
    )
    require(len(receipts) <= 1, "INTEGRITY_MISMATCH")
    pointer, prior = owner.pointer(s, ctx, pid, scope, data.change_id, data.purpose, lock=True)
    saved_pointer = owner.pointer_stamp(pointer) if pointer is not None else None
    saved_prior = (
        common.digest(
            {
                v.name: getattr(prior, v.name)
                for v in prior.__table__.columns
                if v.name != "audience_dependencies"
            }
        )
        if prior is not None
        else None
    )

    def finish(saved, receipt, expected_row):
        # Complete the sole common group before the final current fence. No commit.
        s.flush()
        _same_uow(s, uow, ctx, caller_hash)
        require(
            trust.current(s.get_bind(), scope, supplied=issuer) is concrete
            and trust.stamp(concrete) == issuer_stamp
            and old._runtime_stamp(s) == runtime
        )
        fresh_p, fresh_row = owner.pointer(s, ctx, pid, scope, data.change_id, data.purpose)
        require(
            fresh_p.fact_id == saved.id
            and fresh_p.revision == saved.revision
            and fresh_p.epoch == saved.epoch
            and common.digest(
                {
                    v.name: getattr(fresh_row, v.name)
                    for v in fresh_row.__table__.columns
                    if v.name != "audience_dependencies"
                }
            )
            == expected_row
        )
        group = common_group(
            s, ctx, pid, fresh_row, operation=OPERATION, event=EVENT, actor=saved.actor_id
        )
        require(
            group["receipt"]["id"] == receipt.id
            and group["receipt"]["subject_type"] == FAMILY
            and group["receipt"]["command_id"] == saved.command_id
            and group["receipt"]["intent_digest"] == fingerprint
            and group["receipt"]["request_digest"] == fingerprint
        )
        require(
            owner.binding(
                s, ctx, pid, data.change_id, data.purpose, material=value, verify_sources=False
            )[3]
            == binding
        )
        require(
            controlled.authority(s, ctx, pid, scope, "change.impact.compute", data.purpose)[0]
            == auth
        )
        final_caller, final_caller_until = controlled._caller(s, ctx, pid, write=True)
        require(final_caller == caller and controlled._project(s, ctx, scope)[1] == project_stamp)
        require(owner.temporal(s, ctx, pid, scope)[0] == temporal_stamp)
        require(owner.dependency_epoch(s, ctx, pid) == epoch)
        require(
            trust.current(s.get_bind(), scope, supplied=issuer) is concrete
            and trust.stamp(concrete) == issuer_stamp
            and old._runtime_stamp(s) == runtime
        )
        _same_uow(s, uow, ctx, caller_hash)
        require(
            value.valid_from
            <= owner.clock()
            < earliest_deadline(
                value.valid_until,
                caller_until,
                final_caller_until,
                auth_until,
                temporal_until or value.valid_until,
                owned.valid_until or value.valid_until,
            )
        )
        return common.receipt_view(receipt)

    if receipts:
        require(
            prior is not None
            and prior.id == receipts[0].subject_id
            and (not keys or keys[0].receipt_id == receipts[0].id),
            "INTEGRITY_MISMATCH",
        )
        require(
            prior.material == value.model_dump(mode="json")
            and prior.material_sha256 == digest(value)
            and prior.issuer_stamp == issuer_stamp
            and prior.source_basis == source_basis
            and prior.input_snapshot["payload"] == data.model_dump(mode="json"),
            "SOURCE_STALE",
        )
        controlled.original_authority(s, ctx, pid, prior)
        group = common_group(
            s, ctx, pid, prior, operation=OPERATION, event=EVENT, actor=prior.actor_id
        )
        require(
            group["receipt"]["subject_type"] == FAMILY
            and group["receipt"]["intent_digest"] == fingerprint
            and group["receipt"]["command_id"] == prior.command_id
            and group["receipt"]["request_digest"] == fingerprint,
            "INTEGRITY_MISMATCH",
        )
        revision, publication_epoch = prior.revision, prior.epoch
    else:
        require(not keys, "INTEGRITY_MISMATCH")
        revision, publication_epoch = controlled.previous(
            pointer, prior, data.expected_previous_id, data.expected_previous_revision
        )
        require(
            prior is None
            or (prior.owner_id, prior.visibility, prior.purpose)
            == (value.owner_id, value.visibility, value.purpose)
        )
    # The complete registry was read once under the held model/dependency gates.
    # Direct source versions and the watermark fence the final append; rebuilding
    # the same closure here would repeat the T2 proof rather than strengthen it.
    require(owner.dependency_epoch(s, ctx, pid) == epoch)
    require(
        controlled.original(s, ctx, pid, data.source, CoverageMaterial)[0] == value
        and controlled._source_guard(
            s, ctx, pid, value.visibility, value.owner_id, reads, sources, io=False
        )
        == artifact_basis
    )
    require(
        controlled.authority(s, ctx, pid, scope, "change.impact.compute", data.purpose)[0] == auth
    )
    require(
        owner.binding(
            s, ctx, pid, data.change_id, data.purpose, material=value, verify_sources=False
        )[3]
        == binding
        and owner.temporal(s, ctx, pid, scope)[0] == temporal_stamp
    )
    fresh_pointer, fresh_prior = owner.pointer(s, ctx, pid, scope, data.change_id, data.purpose)
    require(
        (fresh_pointer is None) == (pointer is None)
        and (
            pointer is None
            or (
                owner.pointer_stamp(fresh_pointer) == saved_pointer
                and common.digest(
                    {
                        v.name: getattr(fresh_prior, v.name)
                        for v in fresh_prior.__table__.columns
                        if v.name != "audience_dependencies"
                    }
                )
                == saved_prior
            )
        )
    )
    require(
        controlled._caller(s, ctx, pid, write=True)[0] == caller
        and controlled._project(s, ctx, scope)[1] == project_stamp
        and old._runtime_stamp(s) == runtime
        and trust.current(s.get_bind(), scope, supplied=issuer) is concrete
    )
    require(owner.dependency_epoch(s, ctx, pid) == epoch)
    _same_uow(s, uow, ctx, caller_hash)
    at = owner.clock()
    require(
        value.valid_from
        <= at
        < earliest_deadline(
            value.valid_until,
            caller_until,
            auth_until,
            temporal_until or value.valid_until,
            owned.valid_until or value.valid_until,
        )
    )
    if receipts:
        if not keys:
            s.add(
                RequestKey(
                    tenant_id=ctx.tenant_id,
                    actor_id=ctx.actor_id,
                    key=request_key,
                    digest=fingerprint,
                    receipt_id=receipts[0].id,
                )
            )
        return finish(prior, receipts[0], saved_prior)
    fact = models.ChangeCoverageFact(
        id=uuid4(),
        tenant_id=ctx.tenant_id,
        product_id=pid,
        project_id=scope.project_id,
        owner_id=value.owner_id,
        visibility=value.visibility,
        revision=revision,
        epoch=publication_epoch,
        purpose=value.purpose,
        purpose_sha256=digest(value.purpose),
        previous_id=prior.id if prior else None,
        previous_revision=prior.revision if prior else None,
        actor_id=ctx.actor_id,
        command_id=command_id,
        operation=OPERATION,
        intent_digest=fingerprint,
        status="published",
        nature=value.nature,
        material=value.model_dump(mode="json"),
        material_sha256=digest(value),
        source=data.source.model_dump(mode="json"),
        sources=[v.model_dump(mode="json") for v in sources],
        required_source_read_set=reads,
        source_basis=deepcopy(source_basis),
        authority_snapshot=deepcopy(auth),
        input_snapshot={"payload": data.model_dump(mode="json"), "origin_binding": binding},
        valid_from=value.valid_from,
        valid_until=value.valid_until,
        created_at=at,
        change_id=value.change_id,
        origin_version_id=value.origin_version_id,
        origin_revision=value.origin_revision,
        dependency_epoch=epoch,
        closure_sha256=owned.closure_sha256,
        issuer_stamp=deepcopy(issuer_stamp),
    )
    s.add(fact)
    s.flush([fact])
    fact_digest = common.digest(
        {
            v.name: getattr(fact, v.name)
            for v in fact.__table__.columns
            if v.name != "audience_dependencies"
        }
    )
    if pointer is None:
        s.add(
            models.ChangeCoverageCurrent(
                tenant_id=ctx.tenant_id,
                product_id=pid,
                project_id=scope.project_id,
                owner_id=fact.owner_id,
                visibility=fact.visibility,
                change_id=fact.change_id,
                purpose_sha256=fact.purpose_sha256,
                fact_id=fact.id,
                revision=fact.revision,
                epoch=fact.epoch,
            )
        )
    else:
        pointer.fact_id, pointer.revision, pointer.epoch = fact.id, fact.revision, fact.epoch
    command = Command(
        command_id=command_id,
        idempotency_key=request_key,
        operation=OPERATION,
        category_id=ctx.category_id,
        product_id=pid,
        expected_revision=product.revision,
        source_read_set=reads,
        payload=data.model_dump(mode="json"),
    )
    receipt = common.append_receipt(
        s, ctx, command, FAMILY, fact, fingerprint, fingerprint, fact.visibility
    )
    s.add(
        RequestKey(
            tenant_id=ctx.tenant_id,
            actor_id=ctx.actor_id,
            key=request_key,
            digest=fingerprint,
            receipt_id=receipt.id,
        )
    )
    return finish(fact, receipt, fact_digest)
