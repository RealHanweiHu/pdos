"""Unsafe historical Artifact-hoisting counterexample only; never an adoption source.

Only these two archived functions may be AST loaded by the explicit negative
interleaving test, bound to actual authority globals. Actual assess/helper are
always imported directly; no candidate production body is loaded.
"""

from uuid import UUID

from sqlalchemy import inspect, select

from pdos_next.domain.professional_authority.models import ProfessionalFact
from pdos_next.domain.professional_authority.service import _HASH_FIELDS, _material, _reads, digest
from pdos_next.models import Artifact, OriginalSecurity


def _batch_identity_rows(s, model, identities):
    """One local read only; pending rows keep the original get behavior.

    Plain JSONB in-place edits need a material check before populate_existing.
    This collection is never retained outside this caller or used as authority.
    """
    identities = tuple(dict.fromkeys(identities))
    if not identities:
        return {}
    selected = set(identities)
    pending = any(isinstance(row, model) for row in (*s.new, *s.dirty, *s.deleted))
    if not pending and model is ProfessionalFact:
        for row in s.identity_map.values():
            if not isinstance(row, ProfessionalFact):
                continue
            state = inspect(row)
            values = state.dict
            if "id" not in values:
                pending = True
                break
            if values["id"] not in selected:
                continue
            if not {*_HASH_FIELDS, "fact_sha256"} <= values.keys():
                pending = True
                break
            try:
                unchanged = digest(_material(row)) == row.fact_sha256
            except (TypeError, ValueError, AttributeError):
                unchanged = False
            if not unchanged:
                pending = True
                break
    if pending:
        return None
    query = (
        select(model)
        .where(model.id.in_(identities))
        .execution_options(populate_existing=True, autoflush=False)
    )
    with s.no_autoflush:
        return {row.id: row for row in s.scalars(query)}


def _evidence(s, ctx, product_id, sources):
    from pdos_next.domain.supply_execution.service import _sources

    reads = _reads(sources)
    refs, private = _sources(s, ctx, product_id, reads, references=sources)
    source_rows = _batch_identity_rows(s, Artifact, (UUID(read["artifact_id"]) for read in reads))
    epochs = []
    for read in reads:
        source = (
            s.get(Artifact, UUID(read["artifact_id"]))
            if source_rows is None
            else source_rows.get(UUID(read["artifact_id"]))
        )
        if source.original_id is not None:
            safety = s.scalar(
                select(OriginalSecurity).where(
                    OriginalSecurity.original_id == source.original_id,
                    OriginalSecurity.tenant_id == ctx.tenant_id,
                    OriginalSecurity.product_id == product_id,
                )
            )
            epochs.append(
                {
                    "original_id": str(source.original_id),
                    "security_epoch": safety.epoch if safety else None,
                    "source_state": safety.source_state if safety else None,
                    "disposition": safety.disposition if safety else None,
                }
            )
    return (
        reads,
        private,
        {"refs": [refs[key].model_dump(mode="json") for key in sorted(refs)], "security": epochs},
    )
