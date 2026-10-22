"""Scoped object comparison as an ordinary read; no computed-Claim authority."""

from uuid import UUID

from pydantic import model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from pdos_next.database import tenant_session
from pdos_next.domain.preproject import spec_compare, views
from pdos_next.domain.preproject.category_models import KnowledgeCurrent, KnowledgeEntry
from pdos_next.domain.preproject.category_service import parameter_version
from pdos_next.domain.preproject.models import Proposal, ProposalSource
from pdos_next.domain.preproject.schemas import Reference
from pdos_next.domain.products.models import DefinitionRevision
from pdos_next.domain.products.variant_models import Variant
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Claim, Product, UploadedOriginal
from pdos_next.service import digest, require_access

from .domain_reads import _public_definition
from .execution import check_run_binding
from .m3_extracted_match import ExtractionRows, compare_extracted
from .m3_object_reads import _public_proposal, _public_sources, _references
from .models import AgentRun, AgentSession, PublicWebSnapshot


class AgentSpecCompareInput(spec_compare.SpecCompareInput):
    extraction_ref: ExtractionRows | None = None

    @model_validator(mode="after")
    def extracted_products_only(self):
        if self.extraction_ref is not None and (
            self.parameter_ids or any(subject.type != "product" for subject in self.subjects)
        ):
            raise ValueError(
                "Extracted requirements compare selected product subjects without parameter filters"
            )
        return self


SCHEMAS = {"calc.spec_compare": AgentSpecCompareInput}


def _unavailable():
    raise DomainError(
        "SOURCE_UNAVAILABLE",
        "规格比较资料不在本次运行的可用范围内，请核对提案、来源与共享对象。",
        403,
        detail={"reason": "private_material_context_binding_required"},
    )


def _head(s, ctx, model, identity, *fields):
    """Only privacy/identity metadata is selected before an object's body is read."""
    columns = ("id", "tenant_id", "category_id", *fields)
    proof = None
    key = ("m3-object-head", model, identity, columns)
    if isinstance(s, Session) and s.info.get("read_snapshot"):
        from pdos_next.request_proof import request_proof

        proof = request_proof(s)
        if key in proof.read_rows:
            return proof.read_rows[key]
    row = (
        s.execute(
            select(*(getattr(model, field) for field in columns)).where(
                model.id == identity,
                model.tenant_id == ctx.tenant_id,
                model.category_id == ctx.category_id,
            )
        )
        .mappings()
        .first()
    )
    if not row:
        _unavailable()
    if (
        row["id"] != identity
        or row["tenant_id"] != ctx.tenant_id
        or row["category_id"] != ctx.category_id
    ):
        _unavailable()
    if proof is not None:
        proof.read_rows[key] = row
    return row


class _PublicObjects:
    def __init__(self, session, ctx):
        self.s, self.ctx = session, ctx
        self.seen = set()

    def product(self, identity):
        row = _head(self.s, self.ctx, Product, identity, "visibility")
        if row["visibility"] != "category":
            _unavailable()
        require_access(self.s, self.ctx, identity)

    def target(self, product_id, variant_id=None):
        self.product(product_id)
        if variant_id is not None:
            row = _head(self.s, self.ctx, Variant, variant_id, "product_id", "visibility")
            if row["product_id"] != product_id or row["visibility"] != "category":
                _unavailable()
        return False

    def definition(self, identity, version):
        row = _head(
            self.s, self.ctx, DefinitionRevision, identity, "visibility", "product_id", "revision"
        )
        if row["visibility"] != "category" or row["revision"] != version:
            _unavailable()
        self.product(row["product_id"])
        _public_definition(self.s, self.ctx, {"id": identity, "revision": version})

    def knowledge(self, identity, version=None, *, competitor=False):
        row = _head(
            self.s, self.ctx, KnowledgeEntry, identity, "kind", "version", "lineage_id", "action"
        )
        if row["action"] == "withdraw" or (version is not None and row["version"] != version):
            _unavailable()
        if competitor:
            current = self.s.get(KnowledgeCurrent, (self.ctx.tenant_id, row["lineage_id"]))
            if (
                not current
                or current.category_id != self.ctx.category_id
                or current.status != "active"
                or row["kind"] != "competitor"
                or current.current_entry_id != identity
                or current.current_version != row["version"]
            ):
                _unavailable()
        # Knowledge has category visibility by schema. Its nested references still
        # need their own head checks; a source_ref inside metrics is not optional.
        body = self.s.get(KnowledgeEntry, identity)
        self.refs(_references({"source_refs": body.source_refs, "content": body.content}))
        self.parameters(body.content)

    def parameters(self, value):
        if isinstance(value, dict):
            if value.get("parameter_id") and value.get("parameter_version"):
                parameter_version(
                    self.s, self.ctx, UUID(str(value["parameter_id"])), value["parameter_version"]
                )
            for child in value.values():
                self.parameters(child)
        elif isinstance(value, list):
            for child in value:
                self.parameters(child)

    def refs(self, refs):
        checked = []
        for ref in refs:
            key = (ref.type, ref.id, ref.version)
            if key in self.seen:
                continue
            self.seen.add(key)
            if ref.type in {"artifact", "original"}:
                row = _head(
                    self.s,
                    self.ctx,
                    Artifact,
                    ref.id,
                    "visibility",
                    "product_id",
                    "original_id",
                    "revision",
                    "status",
                )
                if (
                    row["visibility"] != "category"
                    or row["revision"] != ref.version
                    or row["status"] != "active"
                ):
                    _unavailable()
                if row["product_id"]:
                    self.product(row["product_id"])
                if row["original_id"]:
                    original = _head(
                        self.s,
                        self.ctx,
                        UploadedOriginal,
                        row["original_id"],
                        "visibility",
                        "product_id",
                    )
                    if original["visibility"] != "category":
                        _unavailable()
                    if original["product_id"]:
                        self.product(original["product_id"])
            elif ref.type == "snapshot":
                row = _head(self.s, self.ctx, PublicWebSnapshot, ref.id, "visibility", "status")
                if (
                    row["visibility"] != "category"
                    or ref.version != 1
                    or row["status"] not in {"ok", "partial"}
                ):
                    _unavailable()
            elif ref.type == "claim":
                row = _head(
                    self.s,
                    self.ctx,
                    Claim,
                    ref.id,
                    "privacy",
                    "visibility",
                    "status",
                    "revision",
                    "source_kind",
                    "artifact_id",
                    "snapshot_id",
                    "source_revision",
                )
                if (
                    row["privacy"] != "shared"
                    or row["visibility"] != "category"
                    or row["status"] != "active"
                    or row["revision"] != ref.version
                ):
                    _unavailable()
                self.refs(
                    [
                        Reference(
                            type=row["source_kind"],
                            id=row["snapshot_id"]
                            if row["source_kind"] == "snapshot"
                            else row["artifact_id"],
                            version=row["source_revision"],
                        )
                    ]
                )
            elif ref.type == "knowledge":
                self.knowledge(ref.id, ref.version)
            elif ref.type == "definition":
                self.definition(ref.id, ref.version)
            elif ref.type == "parameter":
                parameter_version(self.s, self.ctx, ref.id, ref.version)
            checked.append(ref)
        # Existing ordinary readers retain scan/version/current authority checks.
        _public_sources(self.s, self.ctx, checked)

    def proposal(self, identity):
        head = _head(
            self.s,
            self.ctx,
            Proposal,
            identity,
            "effective_visibility",
            "private_source_count",
            "customer_identities",
            "baseline_product_id",
            "baseline_definition_id",
            "baseline_definition_revision",
        )
        if (
            head["effective_visibility"] != "category"
            or head["private_source_count"]
            or head["customer_identities"]
        ):
            _unavailable()
        roots = list(
            self.s.scalars(
                select(ProposalSource).where(
                    ProposalSource.tenant_id == self.ctx.tenant_id,
                    ProposalSource.category_id == self.ctx.category_id,
                    ProposalSource.proposal_id == identity,
                )
            )
        )
        if any(root.privacy != "shared" for root in roots):
            _unavailable()
        self.refs(
            Reference(type=root.source_type, id=root.source_id, version=root.source_version)
            for root in roots
        )
        if head["baseline_product_id"]:
            self.product(head["baseline_product_id"])
        if head["baseline_definition_id"]:
            self.definition(head["baseline_definition_id"], head["baseline_definition_revision"])
        row = self.s.get(Proposal, identity)
        document = views.read(self.s, self.ctx, identity)
        self.refs(_references(document))  # Includes an actual frozen submission.
        self.parameters(document)
        _public_proposal(self.s, self.ctx, row, document)

    def definition_head(self, row):
        """Guard only the actual candidate selected by the baseline owner.

        The baseline reader invokes this before reading candidate contents. Its
        existing selection/fallback order remains exclusively domain-owned.
        """
        self.definition(row.id, row.revision)


class _RunObjects(_PublicObjects):
    """Read exact proposal-bound sources; other objects retain public preflight."""

    def __init__(self, session, ctx, scope, run):
        super().__init__(session, ctx)
        from .proposal_context import reference_key, stored_references, validate

        validate(session, scope, run)
        self.scope, self.run = scope, run
        self.keys = {reference_key(ref) for ref in stored_references(run)[1]} | {
            ("original", raw["artifact_id"], raw["expected_revision"]) for raw in run.read_sources
        }
        identities = {ref.id for ref in stored_references(run)[1] if ref.type == "definition"}
        from .proposal_context import _heads

        heads = _heads(
            session,
            ctx,
            DefinitionRevision,
            identities,
            ("product_id", "variant_id", "revision", "visibility"),
        )
        self.targets = {(row.product_id, row.variant_id) for row in heads.values()}

    def product(self, identity):
        row = _head(self.s, self.ctx, Product, identity, "visibility")
        if row["visibility"] != "category" and (
            not self.run.private_context
            or not any(target[0] == identity for target in self.targets)
        ):
            _unavailable()
        require_access(self.s, self.ctx, identity)

    def target(self, product_id, variant_id=None):
        self.product(product_id)
        row = _head(self.s, self.ctx, Product, product_id, "visibility")
        private = row["visibility"] != "category"
        if variant_id is not None:
            variant = _head(self.s, self.ctx, Variant, variant_id, "product_id", "visibility")
            if variant["product_id"] != product_id:
                _unavailable()
            private |= variant["visibility"] != "category"
        if private and (
            not self.run.private_context or (product_id, variant_id) not in self.targets
        ):
            _unavailable()
        return private

    def definition(self, identity, version):
        if ("definition", str(identity), version) not in self.keys:
            return super().definition(identity, version)
        row = _head(self.s, self.ctx, DefinitionRevision, identity, "product_id", "revision")
        if row["revision"] != version:
            _unavailable()
        self.product(row["product_id"])

    def baseline_sources_current(self, view):
        """Reuse only a fixed bound definition under the current RR source proof."""
        from pdos_next.domain.preproject.baseline import _source_references
        from pdos_next.request_proof import request_proof

        from .proposal_context import KEY, reference_key

        if (
            not isinstance(self.s, Session)
            or not self.s.info.get("read_snapshot")
            or (KEY, self.run.id) not in request_proof(self.s).read_rows
            or ("definition", str(view["id"]), view["revision"]) not in self.keys
        ):
            return False
        refs = list(_source_references(view))
        if view.get("derived_from_definition_id"):
            refs.append(
                Reference(
                    type="definition",
                    id=view["derived_from_definition_id"],
                    version=view["derived_from_definition_revision"],
                )
            )
        parent = view.get("parent_definition_id")
        if parent and not any(
            kind == "definition" and identity == str(parent) for kind, identity, _ in self.keys
        ):
            return False
        return all(reference_key(ref) in self.keys for ref in refs)

    def refs(self, refs):
        from .proposal_context import reference_key

        # Bound sources were checked by the same RR snapshot's metadata watermarks.
        # The domain comparison still owns ordinary quote/value/current checks.
        typed = (
            ref if isinstance(ref, Reference) else Reference.model_validate(ref) for ref in refs
        )
        super().refs(ref for ref in typed if reference_key(ref) not in self.keys)

    def proposal(self, identity):
        from pdos_next.request_proof import request_proof

        from .proposal_context import validate

        if identity != self.run.proposal_id:
            raise DomainError("FORBIDDEN_SCOPE", "比较提案不属于当前运行。", 403)
        validate(self.s, self.scope, self.run)
        proof = request_proof(self.s)
        key = ("run-proposal-document", self.run.id, identity)
        if key not in proof.read_rows:
            document = views.read(self.s, self.ctx, identity)
            validate(self.s, self.scope, self.run, extra_value=document)
            self.parameters(document)
            proof.read_rows[key] = document
        return proof.read_rows[key]


def _objects(session, ctx, scope, run):
    from .proposal_context import KEY

    if run.proposal_id is not None and KEY in getattr(run, "versions", {}):
        return _RunObjects(session, ctx, scope, run)
    if (
        run.private_context
        or run.customer_identities
        or {"customer", "customer_original"}.intersection(run.data_categories)
    ):
        _unavailable()
    return _PublicObjects(session, ctx)


class SpecCompareReads:
    def __init__(self, store, commands, catalog=None):
        self.store, self.commands, self.catalog = store, commands, catalog

    def handlers(self):
        return {"calc.spec_compare": self.call}

    def restores(self):
        return {"calc.spec_compare": self.restore}

    def call(self, scope, arguments):
        payload = AgentSpecCompareInput.model_validate(arguments)
        if scope.category_id is None:
            raise DomainError("FORBIDDEN_SCOPE", "规格比较须绑定当前品类。", 403)
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
                raise DomainError("FORBIDDEN_SCOPE", "比较未绑定实际会话范围。", 403)
            self.store.authority(session, scope)
            if payload.extraction_ref is not None:
                from .extract_service import ExtractionService

                if self.catalog is None:
                    raise DomainError("SOURCE_UNAVAILABLE", "抽取结果核对端口尚未绑定。", 503)
                ctx = self.commands.context(scope)
                public = _PublicObjects(session, ctx)
                result = compare_extracted(
                    session,
                    ctx,
                    scope,
                    payload,
                    extraction=ExtractionService(self.store, self.commands, self.catalog),
                    public=public,
                )
                final = _PublicObjects(session, ctx)
                final.refs(_references(result["products"]))
                final.parameters(result["products"])
                self.store.authority(session, scope)
                check_run_binding(session.get(AgentRun, scope.run_id), scope, for_write=False)
                return result
            ctx = self.commands.context(scope)
            require_access(session, ctx, scope.product_id)
            try:
                public = _objects(session, ctx, scope, run)
                public.refs(_references(run.read_sources))
                for subject in payload.subjects:
                    if subject.type == "proposal":
                        if run.proposal_id != subject.id:
                            raise DomainError("FORBIDDEN_SCOPE", "比较提案不属于当前运行。", 403)
                        public.proposal(subject.id)
                    elif subject.type == "product":
                        if run.product_id is not None and run.product_id != subject.id:
                            raise DomainError("FORBIDDEN_SCOPE", "比较型号不属于当前运行。", 403)
                        public.product(subject.id)
                    else:
                        public.knowledge(subject.id, competitor=True)
                result = spec_compare.compare(
                    session,
                    ctx,
                    spec_compare.SpecCompareInput.model_validate(
                        payload.model_dump(exclude={"extraction_ref"})
                    ),
                    before_definition_read=public.definition_head,
                )
                # Do not reuse the preflight seen set: every returned source gets
                # an ordinary access/currentness check before it crosses the port.
                final = _objects(session, ctx, scope, run)
                final.refs(_references(result))
                final.parameters(result)
            except DomainError as error:
                if (error.detail or {}).get(
                    "reason"
                ) == "private_material_context_binding_required":
                    _unavailable()
                raise
            self.store.authority(session, scope)
            check_run_binding(session.get(AgentRun, scope.run_id), scope, for_write=False)
            return result

    def restore(self, scope, arguments, previous):
        result = self.call(scope, arguments)
        if digest(result) != digest(previous):
            raise DomainError("SOURCE_STALE", "规格比较来源或内容已变化，请重新读取。")
        return result
