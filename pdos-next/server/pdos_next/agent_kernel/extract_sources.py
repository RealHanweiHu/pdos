"""Shared sealed-source construction for isolated extraction reads.

The seal is the only text authority for both evidence.artifact.read and
evidence.extract dispatch; it is rebuilt from current server state every time,
never carried across calls.
"""

from pdos_next.errors import DomainError
from pdos_next.models import UploadedOriginal
from pdos_next.service import source_for

from .extract_read_ledger import ArtifactSeal


def seal_for(session, ctx, product_id, artifact_id, expected_revision):
    """Return (seal, artifact) for the fixed mounted version, or raise.

    RLS, tenant/category scope, current revision and scan state are enforced by
    source_for and the tenant session; this adds only the original parse facts.
    """
    source = source_for(session, ctx, product_id, artifact_id, expected_revision)
    original = session.get(UploadedOriginal, source.original_id) if source.original_id else None
    if source.original_id and original is None:
        raise DomainError("SOURCE_UNAVAILABLE", "原件元数据不可用。", 403)
    seal = ArtifactSeal.from_server(
        artifact_id=source.id,
        revision=source.revision,
        content_hash=source.content_hash,
        text=source.content,
        total_lines=len(source.content.splitlines()),
        locator_map=original.locator_map if original else [],
        parse_status=original.status if original else "parsed",
        parse_code=original.parse_code if original else None,
    )
    return seal, source
