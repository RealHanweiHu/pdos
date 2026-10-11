"""Local, server-bound upload facts; none of these facts conveys database authority."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from pdos_next.object_storage.types import ObjectRef

JournalState = Literal["prepared", "bytes_written", "unknown", "registered", "aborted"]
RegistrationState = Literal["unknown", "registered", "aborted"]
ByteStatus = Literal["intact", "missing", "corrupt", "unavailable"]


@dataclass(frozen=True, slots=True)
class JournalScope:
    tenant_id: UUID
    product_id: UUID | None
    category_id: UUID | None = None

    def __post_init__(self):
        if (
            not isinstance(self.tenant_id, UUID)
            or (self.product_id is not None and not isinstance(self.product_id, UUID))
            or (self.category_id is not None and not isinstance(self.category_id, UUID))
            or (self.product_id is None and self.category_id is None)
        ):
            raise ValueError("Journal scope requires server-bound UUIDs")

    def to_dict(self):
        return {
            "tenant_id": str(self.tenant_id),
            "product_id": str(self.product_id) if self.product_id else None,
            "category_id": str(self.category_id) if self.category_id else None,
        }


@dataclass(frozen=True, slots=True)
class UploadInspection:
    upload_id: UUID
    scope: JournalScope
    requester_id: UUID
    reference: ObjectRef
    revision: int
    state: JournalState
    registration_state: RegistrationState
    byte_status: ByteStatus
    created_at: datetime
    updated_at: datetime
    recovery_required: bool
    error_code: str | None = None
    registration_id: UUID | None = None
    terminal_evidence_ref: str | None = None

    def to_dict(self, *, include_internal: bool = False):
        # ObjectRef.as_dict includes a legacy static scan label. This journal has
        # no scanner authority, so serialize the byte identity explicitly.
        ref = self.reference
        result = {
            "upload_id": str(self.upload_id),
            "scope": self.scope.to_dict(),
            "requester_id": str(self.requester_id),
            "reference": {
                "id": str(ref.id),
                "version": ref.version,
                "content_sha256": ref.content_sha256,
                "size_bytes": ref.size_bytes,
                "media_type": ref.media_type,
            },
            "revision": self.revision,
            "state": self.state,
            "registration_state": self.registration_state,
            "byte_status": self.byte_status,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "recovery_required": self.recovery_required,
            "error_code": self.error_code,
            "registration_id": str(self.registration_id) if self.registration_id else None,
        }
        if include_internal:
            result["terminal_evidence_ref"] = self.terminal_evidence_ref
            result["reference"]["server_storage_key"] = ref.server_storage_key
        return result


@dataclass(frozen=True, slots=True)
class InventoryPage:
    scope: JournalScope
    items: tuple[UploadInspection, ...]
    has_more: bool
    next_cursor: str | None
    complete: bool
    unavailable_count: int = 0

    def to_dict(self):
        return {
            "scope": self.scope.to_dict(),
            "items": [item.to_dict() for item in self.items],
            "has_more": self.has_more,
            "next_cursor": self.next_cursor,
            "complete": self.complete,
            "unavailable_count": self.unavailable_count,
        }
