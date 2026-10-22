"""Consume committed Build facts and owner watermarks without reallocating history."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select

from pdos_next.domain.build_operational_facts import service as operational
from pdos_next.domain.build_operational_facts.models import BuildOperationalFact
from pdos_next.domain.build_operational_facts.schemas import FactInput
from pdos_next.domain.professional_authority import service as professional
from pdos_next.domain.professional_authority.models import ProfessionalCurrent
from pdos_next.errors import DomainError
from pdos_next.request_proof import scoped_rows, snapshot_get


def _require(condition, reason="OPERATIONAL_FACTS_CHANGED"):
    if not condition:
        raise DomainError(reason, "已开工事实的当前指针、直接来源或水位需要重新核对。")


def authority_watermarks(s, ctx, product_id, project_id, snapshot, at, *, retained=False):
    """A signed decision retains its qualification; new constrained acts compare Current."""
    _require(
        snapshot.get("authorized") is True and snapshot.get("qualified") is True,
        "PROFESSIONAL_AUTHORITY_CHANGED",
    )
    _require(
        snapshot.get("scope")
        == {
            "tenant_id": str(ctx.tenant_id),
            "product_id": str(product_id),
            "project_id": str(project_id),
        },
        "PROFESSIONAL_AUTHORITY_CHANGED",
    )
    refs = snapshot.get("fact_refs")
    _require(isinstance(refs, list) and bool(refs), "PROFESSIONAL_AUTHORITY_CHANGED")
    if retained:
        # The release owner fixed this qualification in its signed immutable
        # decision. Historical evaluation grants no present execution action.
        return
    subject = UUID(snapshot["subject_id"])
    pointers = scoped_rows(
        s,
        (ProfessionalCurrent, product_id, project_id, subject),
        select(ProfessionalCurrent)
        .where(
            ProfessionalCurrent.tenant_id == ctx.tenant_id,
            ProfessionalCurrent.product_id == product_id,
            ProfessionalCurrent.project_id == project_id,
            ProfessionalCurrent.subject_id == subject,
        )
        .order_by(ProfessionalCurrent.id),
    )
    indexed = {str(row.series_id): row for row in pointers}
    registry = getattr(s.get_bind(), "_pdos_professional_issuers", {})
    for ref in refs:
        pointer = indexed.get(ref["series_id"])
        _require(pointer is not None, "PROFESSIONAL_AUTHORITY_CHANGED")
        summary = pointer.summary
        issuer = registry.get(ref["issuer_key"])
        _require(
            str(pointer.fact_id) == ref["id"]
            and pointer.fact_revision == ref["revision"]
            and pointer.epoch == ref["epoch"]
            and summary["fact_sha256"] == ref["fact_sha256"]
            and summary["state"] == "active"
            and datetime.fromisoformat(summary["valid_from"])
            <= at
            < datetime.fromisoformat(summary["valid_until"])
            and isinstance(issuer, professional.IssuerContext)
            and issuer._token is professional._CAPABILITY
            and issuer.tenant_id == ctx.tenant_id
            and issuer.product_id == product_id
            and issuer.project_id in {None, project_id}
            and issuer.version == ref["issuer_version"]
            and issuer.epoch == ref["issuer_epoch"],
            "PROFESSIONAL_AUTHORITY_CHANGED",
        )


def reservation_watermarks(s, ctx, product_id, build, assessment, saved, scope, at):
    """Compare the exact committed reservation and its referenced physical facts.

    Foreign capacity remains the reservation owner's locked responsibility for
    new allocations. Another lawful allocation does not reallocate this Build.
    """
    proof, _ = operational.reservation_basis(
        s, ctx, product_id, build.id, scope, saved.id, saved.intent_digest
    )
    _require(proof["facts_revision"] == saved.reservations["facts_revision"])
    pointer = operational._pointer(s, ctx, product_id, build.id)
    _require(pointer is not None)
    refs = assessment.result["fact_refs"]
    _require(len(refs) == 1)
    ref = refs[0]
    _require(
        str(pointer.fact_id) == ref["id"] == proof["fact_id"]
        and pointer.fact_revision == ref["revision"]
        and pointer.epoch == ref["epoch"]
    )
    fact = snapshot_get(s, BuildOperationalFact, pointer.fact_id, scope_id=product_id)
    _require(
        fact is not None
        and fact.tenant_id == ctx.tenant_id
        and fact.product_id == product_id
        and fact.project_id == build.project_id
        and fact.build_id == build.id
        and fact.fact_sha256 == ref["sha256"] == proof["fact_sha256"]
        and fact.state == "active"
        and fact.valid_from <= at
        and (fact.valid_until is None or at < fact.valid_until)
    )
    issuer = getattr(s.get_bind(), "_pdos_operational_issuers", {}).get(fact.issuer_key)
    operational._issuer(s, ctx, product_id, build.project_id, issuer)
    _require(issuer.version == fact.issuer_version and issuer.epoch == fact.issuer_epoch)
    data = FactInput.model_validate(fact.data)
    _require(data.scope.model_dump(mode="json") == proof["scope"])
    specs = operational._assets(data, ctx.tenant_id)
    assets = operational._locked_assets(s, ctx, specs, lock=False)
    for _, identity, _, _, revision, physical in specs:
        asset = assets.get(identity)
        _require(
            asset is not None
            and asset.revision == revision
            and asset.data_sha256 == operational.digest(physical)
            and asset.data["state"] == "active"
        )
    expected = proof.get("decision_watermarks")
    _require(isinstance(expected, list), "RESERVATION_PROOF_MISSING")
    actual = []
    for resource in data.resources:
        for decision in resource.facts:
            current = operational._proof(s, ctx, issuer, fact, resource, decision, at)
            _require(
                current is not None
                and current.current is True
                and (current.valid_until is None or at < current.valid_until)
            )
            actual.append(
                {
                    "resource": str(resource.resource.id),
                    "kind": decision.kind,
                    "operation_id": decision.operation_id,
                    "proof": current.model_dump(mode="json"),
                }
            )
    _require(actual == expected)
