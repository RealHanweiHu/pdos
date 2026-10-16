"""Server-owned proposal source closure, bound once and rechecked before model egress."""

from types import SimpleNamespace
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import load_only

from pdos_next.contracts import SourceRead
from pdos_next.database import tenant_session
from pdos_next.domain.preproject import baseline
from pdos_next.domain.preproject.access import fail, proposal
from pdos_next.domain.preproject.category_models import KnowledgeEntry
from pdos_next.domain.preproject.claim_access import resolve, source_privacy
from pdos_next.domain.preproject.models import ProposalSource
from pdos_next.domain.preproject.schemas import Reference
from pdos_next.domain.products.models import DefinitionRevision
from pdos_next.models import Artifact, Claim, Product
from pdos_next.request_proof import request_proof, scoped_rows
from pdos_next.service import Context, source_for

from .execution import check_run_binding
from .m3_object_reads import _references
from .models import AgentRun, PublicWebSnapshot

KEY = "proposal_context"


def _outbound_unavailable():
    fail(
        "FORBIDDEN_SCOPE",
        "private_material_context_binding_required",
        "当前提案的完整资料范围尚未绑定此运行，请重新委派以核对当前来源与权限。",
        403,
    )


def check(store, scope):
    if scope.proposal_id is None:
        return
    with tenant_session(
        store.engine,
        scope.tenant_id,
        actor_id=scope.writer_id,
        requester_id=scope.requester_id,
        category_id=scope.category_id,
        read_snapshot=True,
    ) as session:
        run = session.get(AgentRun, scope.run_id)
        check_run_binding(run, scope, for_write=False)
        store.authority(session, scope)
        if not run.versions.get(KEY):
            _outbound_unavailable()
        validate(session, scope, run)


def reference_key(ref):
    return ("original" if ref.type == "artifact" else ref.type, str(ref.id), ref.version)


def collect(session, ctx, row, value, *, extra_value=None):
    """Use the ordinary fixed-tree validator; no model-supplied scope or privacy facts."""
    roots = list(
        session.scalars(
            select(ProposalSource).where(
                ProposalSource.tenant_id == ctx.tenant_id,
                ProposalSource.category_id == ctx.category_id,
                ProposalSource.proposal_id == row.id,
            )
        )
    )
    refs = list(_references(value))
    refs.extend(_references(extra_value))
    if row.baseline_definition_id:
        refs.append(
            Reference(
                type="definition",
                id=row.baseline_definition_id,
                version=row.baseline_definition_revision,
            )
        )
    closed = []
    baseline.validate_sources(session, ctx, None, extra_refs=refs, resolved_references=closed)
    by_key = {reference_key(ref): ref for ref in closed}
    if any(
        (root.source_type, str(root.source_id), root.source_version) not in by_key for root in roots
    ):
        _outbound_unavailable()
    private = bool(
        row.effective_visibility != "category"
        or row.private_source_count
        or row.customer_identities
        or any(root.privacy != "shared" for root in roots)
    )
    categories = {"customer" if row.customer_identities else "internal"}
    reads = {}
    for ref in by_key.values():
        if ref.type in {"artifact", "original"}:
            head = session.get(Artifact, ref.id)
            if not head:
                _outbound_unavailable()
            source = source_for(session, ctx, head.product_id, ref.id, ref.version)
            private |= (
                source_privacy(
                    session, ctx, SimpleNamespace(source_kind="artifact", artifact_id=source.id)
                )
                != "shared"
            )
            if source.original_id:
                categories.add("customer_original")
            reads[source.id] = {
                **SourceRead(artifact_id=source.id, expected_revision=source.revision).model_dump(
                    mode="json"
                ),
                "product_id": str(source.product_id) if source.product_id else None,
            }
        elif ref.type == "claim":
            claim = resolve(session, ctx, ref.id, ref.version, approved=True)
            private |= claim.privacy != "shared" or claim.visibility != "category"
        elif ref.type == "snapshot":
            source = session.get(PublicWebSnapshot, ref.id)
            private |= source.visibility != "category"
        elif ref.type == "definition":
            definition = session.get(DefinitionRevision, ref.id)
            product = session.get(Product, definition.product_id)
            private |= definition.visibility != "category" or product.visibility != "category"
    return SimpleNamespace(
        private_context=private,
        data_categories=tuple(sorted(categories)),
        customer_identities=tuple(row.customer_identities),
        read_sources=[reads[key] for key in sorted(reads, key=str)],
        references=[by_key[key].model_dump(mode="json") for key in sorted(by_key)],
    )


def binding(ctx, row, facts):
    return {
        "kind": "proposal-context/v1",
        "tenant_id": str(ctx.tenant_id),
        "category_id": str(ctx.category_id),
        "requester_id": str(ctx.requester_id),
        "proposal_id": str(row.id),
        "references": facts.references,
    }


def bound_head(run, row):
    """Reject an unbound private head before loading any body."""
    stored = getattr(run, "versions", {}).get(KEY)
    if (
        row.effective_visibility != "category"
        or row.private_source_count
        or row.customer_identities
    ) and not stored:
        _outbound_unavailable()
    return stored


def _heads(session, ctx, model, identities, fields):
    """Batch only current metadata, retaining the RR request's ordinary RLS proof."""
    proof = request_proof(session)
    key = ("outbound-heads", model, tuple(sorted(identities, key=str)))
    if key not in proof.read_rows:
        rows = (
            {
                row.id: row
                for row in session.scalars(
                    select(model)
                    .where(
                        model.tenant_id == ctx.tenant_id,
                        model.category_id == ctx.category_id,
                        model.id.in_(identities),
                    )
                    .options(
                        load_only(
                            model.id,
                            model.tenant_id,
                            model.category_id,
                            *(getattr(model, name) for name in fields),
                        )
                    )
                )
            }
            if identities
            else {}
        )
        if rows.keys() != identities:
            _outbound_unavailable()
        proof.read_rows[key] = rows
        if model is Artifact:
            for identity, row in rows.items():
                proof.read_rows.setdefault((Artifact, identity), row)
    return proof.read_rows[key]


def _watermarks(session, ctx, run, refs):
    """Compare the bound read-set's current heads; never reconstruct upstream bodies."""
    by_type = {}
    for ref in refs:
        by_type.setdefault(ref.type, {})[ref.id] = ref.version
    reads = {UUID(raw["artifact_id"]): raw for raw in run.read_sources}
    artifacts = _heads(
        session,
        ctx,
        Artifact,
        set(reads),
        ("product_id", "revision", "status", "original_id", "visibility", "owner_id"),
    )
    for identity, source in artifacts.items():
        ref = reads[identity]
        if (str(source.product_id) if source.product_id else None) != ref["product_id"]:
            _outbound_unavailable()
        source_for(session, ctx, source.product_id, identity, ref["expected_revision"])
        if (source.original_id and "customer_original" not in run.data_categories) or (
            source_privacy(
                session, ctx, SimpleNamespace(source_kind="artifact", artifact_id=identity)
            )
            != "shared"
            and not run.private_context
        ):
            _outbound_unavailable()
    for ref in refs:
        if ref.type in {"artifact", "original"} and (
            ref.id not in reads or reads[ref.id]["expected_revision"] != ref.version
        ):
            _outbound_unavailable()
    for model, kind, fields, version_field in (
        (
            Claim,
            "claim",
            ("product_id", "proposal_id", "revision", "status", "privacy", "visibility"),
            "revision",
        ),
        (PublicWebSnapshot, "snapshot", ("status", "visibility"), None),
        (
            DefinitionRevision,
            "definition",
            ("product_id", "variant_id", "revision", "visibility"),
            "revision",
        ),
        (KnowledgeEntry, "knowledge", ("version", "action"), "version"),
    ):
        versions = by_type.get(kind, {})
        for identity, row in _heads(session, ctx, model, set(versions), fields).items():
            if version_field and getattr(row, version_field) != versions[identity]:
                _outbound_unavailable()
            if kind == "claim":
                if row.status != "active":
                    _outbound_unavailable()
                private = row.privacy != "shared" or row.visibility != "category"
                if private and row.proposal_id:
                    proposal(session, ctx, row.proposal_id)
            elif kind == "snapshot":
                if versions[identity] != 1 or row.status not in {"ok", "partial"}:
                    _outbound_unavailable()
                private = row.visibility != "category"
            elif kind == "definition":
                product = session.get(Product, row.product_id)
                if not product:
                    _outbound_unavailable()
                private = row.visibility != "category" or product.visibility != "category"
            else:
                if row.action == "withdraw":
                    _outbound_unavailable()
                private = False
            if private and not run.private_context:
                _outbound_unavailable()


def stored_references(run):
    stored = run.versions.get(KEY)
    if (
        not isinstance(stored, dict)
        or set(stored)
        != {"kind", "tenant_id", "category_id", "requester_id", "proposal_id", "references"}
        or any(
            stored[key] != value
            for key, value in {
                "kind": "proposal-context/v1",
                "tenant_id": str(run.tenant_id),
                "category_id": str(run.category_id),
                "requester_id": str(run.requester_id),
                "proposal_id": str(run.proposal_id),
            }.items()
        )
    ):
        _outbound_unavailable()
    try:
        refs = [Reference.model_validate(raw) for raw in stored["references"]]
    except (TypeError, ValueError):
        _outbound_unavailable()
    return stored, refs


def validate(session, scope, run, *, extra_value=None):
    if run.proposal_id is None:
        return
    ctx = Context(
        scope.tenant_id,
        scope.writer_id,
        scope.requester_id,
        category_id=scope.category_id,
        agent_run_id=scope.run_id,
        cancel_epoch=scope.cancel_epoch,
    )
    row = proposal(session, ctx, run.proposal_id)
    stored = bound_head(run, row)
    if stored is None:
        return  # The public-only tool ports retain their existing public-source guard.
    stored, refs = stored_references(run)
    keys = {reference_key(ref) for ref in refs} | {
        ("original", raw["artifact_id"], raw["expected_revision"]) for raw in run.read_sources
    }
    roots = scoped_rows(
        session,
        (KEY, row.id),
        select(ProposalSource).where(
            ProposalSource.tenant_id == ctx.tenant_id,
            ProposalSource.category_id == ctx.category_id,
            ProposalSource.proposal_id == row.id,
        ),
    )
    if (
        (row.effective_visibility != "category" or row.private_source_count)
        and not run.private_context
        or row.customer_identities
        and "customer" not in run.data_categories
        or not set(row.customer_identities) <= set(run.customer_identities)
        or any(
            (root.source_type, str(root.source_id), root.source_version) not in keys
            for root in roots
        )
        or not {reference_key(ref) for ref in _references(extra_value)} <= keys
    ):
        _outbound_unavailable()
    # Once per read snapshot, shared by metadata, item and history projections.
    proof = request_proof(session)
    marker = (KEY, run.id)
    if marker not in proof.read_rows:
        _watermarks(session, ctx, run, refs)
        proof.read_rows[marker] = True


def admit_created(session, subject, receipt):
    """Admit only a receipt-backed domain result, atomically in its existing UOW.

    Both producers already own the Run lock and source proof. This adds no
    authority, original read, data category, model qualification or business row.
    Receipt replay returns directly; no second admission is needed after commit.
    """
    if isinstance(subject, Claim):
        kind, operation, run_id = "claim", "evidence.claim.record", subject.run_id
    elif isinstance(subject, PublicWebSnapshot):
        kind, operation, run_id = (
            "snapshot",
            "research.snapshot.register",
            subject.registered_by_run_id,
        )
    else:
        return
    run = session.get(AgentRun, run_id) if run_id else None
    if run is None or run.proposal_id is None or KEY not in run.versions:
        return  # Legacy/test runs have no proposal context to extend.
    stored, refs = stored_references(run)
    if (
        subject.tenant_id != run.tenant_id
        or subject.category_id != run.category_id
        or subject.receipt_id != receipt.id
        or receipt.subject_id != subject.id
        or receipt.tenant_id != run.tenant_id
        or receipt.category_id != run.category_id
        or receipt.operation != operation
        or receipt.subject_revision != 1
        or receipt.subject_type != ("claim" if kind == "claim" else "public_web_snapshot")
        or receipt.requester_id != run.requester_id
        or receipt.agent_run_id != run.id
    ):
        _outbound_unavailable()
    known = {reference_key(ref) for ref in refs} | {
        ("original", raw["artifact_id"], raw["expected_revision"]) for raw in run.read_sources
    }
    additions = [Reference(type=kind, id=subject.id, version=1)]
    if kind == "claim":
        if (
            subject.proposal_id != run.proposal_id
            or subject.revision != 1
            or subject.status != "active"
            or subject.writer_id != run.writer_id
            or (
                (subject.privacy != "shared" or subject.visibility != "category")
                and not run.private_context
            )
        ):
            return
        source = Reference(
            type=subject.source_kind,
            id=subject.artifact_id if subject.source_kind == "artifact" else subject.snapshot_id,
            version=subject.source_revision,
        )
        if source.type == "artifact" and reference_key(source) not in known:
            return  # A derived fact cannot introduce an unbound customer original.
        if source.type == "snapshot":
            snapshot = session.get(PublicWebSnapshot, source.id)
            if (
                not snapshot
                or snapshot.tenant_id != run.tenant_id
                or snapshot.category_id != run.category_id
                or source.version != 1
                or snapshot.status not in {"ok", "partial"}
                or snapshot.visibility != "category"
                and not (run.private_context and snapshot.registered_by_run_id == run.id)
            ):
                return
            from .snapshot_read_ledger import _registration

            _registration(session, snapshot)
        additions.append(source)
    elif subject.visibility != ("private" if run.private_context else "category"):
        _outbound_unavailable()
    merged = {reference_key(ref): ref for ref in refs}
    for ref in additions:
        merged.setdefault(reference_key(ref), ref)
    if len(merged) != len(refs):
        run.versions = {
            **run.versions,
            KEY: {
                **stored,
                "references": [merged[key].model_dump(mode="json") for key in sorted(merged)],
            },
        }
