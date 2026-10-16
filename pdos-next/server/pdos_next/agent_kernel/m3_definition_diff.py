"""Run-bound definition comparison: ordinary reads, never adoption or Claim proof.

Private material requires the host's exact source binding. Restore repeats
authorization and current-content reads, without acquiring adoption authority.
"""

from copy import deepcopy
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from pdos_next.database import tenant_session
from pdos_next.domain.preproject import baseline
from pdos_next.domain.products import definitions, variants
from pdos_next.domain.products.models import DefinitionRevision
from pdos_next.errors import DomainError
from pdos_next.schema_base import StrictModel
from pdos_next.schemas.products.derivation import DerivationRequest
from pdos_next.service import digest, require_access

from .domain_reads import FixedBaseline, ProposedProposal
from .execution import check_run_binding
from .m3_object_reads import _references
from .m3_spec_compare import _head, _objects, _RunObjects, _unavailable
from .models import AgentRun, AgentSession


class FixedDefinition(StrictModel):
    product_id: UUID
    definition_id: UUID
    definition_revision: int = Field(gt=0)
    variant_id: UUID | None = None


class ComparisonBaseline(FixedBaseline):
    variant_id: UUID | None = None


class ThreeWay(StrictModel):
    old_parent: FixedDefinition
    new_parent: FixedDefinition
    child: FixedDefinition


class DefinitionDiffInput(StrictModel):
    baseline: ComparisonBaseline | None = None
    proposed: ProposedProposal | FixedDefinition | None = None
    three_way: ThreeWay | None = None
    areas: list[Literal["specification", "bom", "certification", "tooling"]] = Field(
        default_factory=lambda: ["specification", "bom", "certification", "tooling"]
    )

    @model_validator(mode="after")
    def exclusive_mode(self):
        if self.three_way is not None:
            if self.baseline is not None or self.proposed is not None:
                raise ValueError("three_way and baseline/proposed are mutually exclusive")
        elif self.baseline is None or self.proposed is None:
            raise ValueError("baseline and proposed must be supplied together")
        if isinstance(self.proposed, ProposedProposal) and self.baseline.variant_id is not None:
            raise ValueError("Proposal mode retains its original baseline contract")
        return self


SCHEMAS = {"calc.derivation_diff": DefinitionDiffInput}


def calculate(payload, old, new, child):
    """Project already authorized current views through the sole variants engine."""
    snapshots = []
    for view in (old, new, child):
        projected = deepcopy(view)
        for spec in projected.get("specs", []):
            # These are persistence watermarks, never comparison business fields.
            spec.pop("item_id", None)
            spec.pop("item_version", None)
        snapshots.append(
            variants.snapshot_from_definition(projected, variant_id=view.get("variant_id"))
        )
    request = DerivationRequest(
        old_parent=snapshots[0],
        new_parent=snapshots[1],
        child=snapshots[2],
        pinned_parent=snapshots[0].ref,
    )
    try:
        result = variants.compare_snapshots(
            request, allow_same_parent=payload.three_way is None
        ).model_dump(mode="json")
    except variants.DerivationError as error:
        raise DomainError("VALIDATION_FAILED", str(error), 422) from error
    selected = "specification" in payload.areas
    return {
        **result,
        "engine": "products.variants.compare_snapshots",
        "derivation_request_digest": result["request_digest"],
        # Full views include item-version metadata, beyond the engine's content DTO.
        "request_digest": digest(
            {"inputs": payload.model_dump(mode="json"), "views": [old, new, child]}
        ),
        "differences": [
            {"area": "specification", **row}
            for row in result["differences"]
            if selected and row["path"].startswith("specs/")
        ],
        "areas": payload.areas,
        "unavailable_blocks": [area for area in payload.areas if area != "specification"],
        "blocks": {
            area: {"status": "unknown", "items": [], "reason": "definition_binding_unavailable"}
            for area in payload.areas
            if area != "specification"
        },
    }


class DefinitionDiffReads:
    def __init__(self, store, commands, proposal_reads):
        self.store, self.commands, self.proposal_reads = store, commands, proposal_reads

    def handlers(self):
        return {"calc.derivation_diff": self.call}

    def restores(self):
        return {"calc.derivation_diff": self.restore}

    @staticmethod
    def _public_definition(public, identity, revision):
        try:
            public.definition(identity, revision)
        except DomainError as error:
            if (
                error.code == "FORBIDDEN_SCOPE"
                and error.detail.get("reason") == "private_material_context_binding_required"
            ):
                _unavailable()
            raise

    def _read(self, session, ctx, scope, public, ref):
        if scope.product_id is not None and ref.product_id != scope.product_id:
            raise DomainError("FORBIDDEN_SCOPE", "定义不属于本次型号运行。", 403)
        public.product(ref.product_id)
        head = _head(
            session,
            ctx,
            DefinitionRevision,
            ref.definition_id,
            "product_id",
            "variant_id",
            "revision",
            "visibility",
        )
        if (
            head["product_id"] != ref.product_id
            or head["variant_id"] != ref.variant_id
            or head["revision"] != ref.definition_revision
        ):
            raise DomainError("VERSION_CONFLICT", "定义固定范围或版本已变化。")
        self._public_definition(public, ref.definition_id, ref.definition_revision)
        # All head and nested source privacy checks happen before the body read.
        row = session.get(DefinitionRevision, ref.definition_id)
        view = definitions.definition_view(session, ctx, row)
        if (
            str(view["id"]) != str(ref.definition_id)
            or str(view["product_id"]) != str(ref.product_id)
            or str(view["category_id"]) != str(ctx.category_id)
            or view["revision"] != ref.definition_revision
            or str(view.get("variant_id")) != str(ref.variant_id)
        ):
            raise DomainError("VERSION_CONFLICT", "定义读取结果与固定身份不一致。")
        baseline.validate_sources(session, ctx, view)
        return view

    def call(self, scope, arguments):
        payload = DefinitionDiffInput.model_validate(arguments)
        if scope.category_id is None:
            raise DomainError("FORBIDDEN_SCOPE", "定义比较须绑定当前品类。", 403)
        with tenant_session(
            self.store.engine,
            scope.tenant_id,
            actor_id=scope.writer_id,
            requester_id=scope.requester_id,
            category_id=scope.category_id,
            read_snapshot=True,
        ) as session:
            run = session.get(AgentRun, scope.run_id)
            check_run_binding(run, scope, for_write=False)
            owner = session.get(AgentSession, run.session_id)
            if (
                not owner
                or owner.tenant_id != run.tenant_id
                or owner.owner_id != run.requester_id
                or any(
                    getattr(owner, field) != getattr(run, field)
                    for field in ("category_id", "product_id", "proposal_id")
                )
            ):
                raise DomainError("FORBIDDEN_SCOPE", "定义比较未绑定实际会话。", 403)
            self.store.authority(session, scope)
            ctx = self.commands.context(scope)
            require_access(session, ctx, scope.product_id)
            public = _objects(session, ctx, scope, run)
            public.refs(_references(run.read_sources))
            if isinstance(payload.proposed, ProposedProposal):
                if run.proposal_id != payload.proposed.proposal_id:
                    raise DomainError("FORBIDDEN_SCOPE", "比较提案不属于当前运行。", 403)
                public.proposal(payload.proposed.proposal_id)
                # Preserve the existing proposal contract and result classification.
                arguments = {
                    "baseline": payload.baseline.model_dump(mode="json", exclude={"variant_id"}),
                    "proposed": payload.proposed.model_dump(mode="json"),
                    "areas": payload.areas,
                }
                if isinstance(public, _RunObjects):
                    from .domain_reads import DerivationDiffInput

                    result = self.proposal_reads._baseline_call(
                        scope,
                        DerivationDiffInput.model_validate(arguments),
                        name="calc.derivation_diff",
                        session=session,
                    )
                else:
                    result = self.proposal_reads.call(scope, arguments, name="calc.derivation_diff")
                self.store.authority(session, scope)
                check_run_binding(session.get(AgentRun, scope.run_id), scope, for_write=False)
                return result
            if payload.three_way:
                refs = payload.three_way
                old, new, child = [
                    self._read(session, ctx, scope, public, ref)
                    for ref in (refs.old_parent, refs.new_parent, refs.child)
                ]
                parent_id = child.get("derived_from_definition_id") or child.get(
                    "parent_definition_id"
                )
                if (
                    str(parent_id) != str(refs.old_parent.definition_id)
                    or child.get("derived_from_definition_id")
                    and child.get("derived_from_definition_revision")
                    != refs.old_parent.definition_revision
                ):
                    raise DomainError("VERSION_CONFLICT", "子定义没有绑定所选旧父版。")
            else:
                public.product(payload.baseline.product_id)
                if scope.product_id is not None and payload.baseline.product_id != scope.product_id:
                    raise DomainError("FORBIDDEN_SCOPE", "基线不属于本次型号运行。", 403)
                if payload.baseline.definition_id is not None:
                    head = _head(
                        session,
                        ctx,
                        DefinitionRevision,
                        payload.baseline.definition_id,
                        "product_id",
                        "variant_id",
                        "revision",
                    )
                    if (
                        head["product_id"] != payload.baseline.product_id
                        or head["variant_id"] != payload.baseline.variant_id
                        or head["revision"] != payload.baseline.definition_revision
                    ):
                        raise DomainError("VERSION_CONFLICT", "定义固定范围或版本已变化。")
                    # The domain read can legitimately hide an unreadable definition.
                    # Check its fixed privacy roots before interpreting an empty baseline
                    # as a version change; this never reads the definition body.
                    self._public_definition(
                        public, payload.baseline.definition_id, payload.baseline.definition_revision
                    )
                result = baseline.read_baseline(
                    session,
                    ctx,
                    payload.baseline.product_id,
                    definition_revision=payload.baseline.definition_revision,
                    variant_id=payload.baseline.variant_id,
                    before_definition_read=public.definition_head,
                    include_blocks=False,
                )
                old = result.get("definition")
                if (
                    old is None
                    or old["revision"] != payload.baseline.definition_revision
                    or payload.baseline.definition_id is not None
                    and str(old["id"]) != str(payload.baseline.definition_id)
                ):
                    raise DomainError("VERSION_CONFLICT", "固定基线不存在或已变化。")
                baseline.validate_sources(session, ctx, old)
                new = old
                child = self._read(session, ctx, scope, public, payload.proposed)
            result = calculate(payload, old, new, child)
            final = _objects(session, ctx, scope, run)
            for view in (old, new, child):
                final.refs(_references(view))
                final.parameters(view)
            self.store.authority(session, scope)
            check_run_binding(session.get(AgentRun, scope.run_id), scope, for_write=False)
            return result

    def restore(self, scope, arguments, previous):
        result = self.call(scope, arguments)
        if digest(result) != digest(previous):
            raise DomainError("SOURCE_STALE", "定义比较内容或来源已变化，请重新读取。")
        return result
