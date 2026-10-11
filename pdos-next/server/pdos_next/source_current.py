"""Current provenance of an owner's explicit direct artifact references."""

from pdos_next.errors import DomainError
from pdos_next.schemas.verification.contracts import SourceRef


def direct_source_basis(s, ctx, product, refs, read_set):
    """Return the existing source-basis JSON without following historical sources.

    The caller supplies server-resolved scope and its complete direct SourceRefs.
    Read-set entries not referenced here remain the caller's independent guards.
    No ref's required read set or upstream parent is loaded by this helper.
    """
    from pdos_next.domain.quality_execution.evidence import check_source, merge_reads

    references = tuple(
        ref if isinstance(ref, SourceRef) else SourceRef.model_validate(ref) for ref in refs
    )
    if not references:
        return [], False
    pid = getattr(product, "id", product)
    expected = {read["artifact_id"]: read["expected_revision"] for read in merge_reads(read_set)}
    for ref in references:
        if ref.kind != "artifact":
            # Preserve the owner's unsupported-source guard and error contract.
            check_source(s, ctx, pid, ref)
        revision = expected.get(str(ref.id))
        if revision is None:
            raise DomainError("MISSING_REQUIRED_EVIDENCE", "直接来源缺少精确声明的读取版本。", 422)
        if revision != ref.revision:
            raise DomainError("SOURCE_STALE", "直接来源与声明的读取版本不一致。")

    basis, private = {}, False
    for ref in references:
        # check_source validates the exact line/quote, source_for visibility and
        # current revision, immutable content, original safety and registration.
        # Its existing proof/context caches remain responsible for raw reuse.
        _reads, current, is_private = check_source(s, ctx, pid, ref)
        basis[str(ref.id)] = current[0]
        private |= is_private
    return [basis[identity] for identity in sorted(basis)], private
