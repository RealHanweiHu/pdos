from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


class StorageFailure(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable

    def as_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "retryable": self.retryable}


@dataclass(frozen=True, slots=True)
class ObjectRef:
    id: UUID
    version: int
    content_sha256: str
    size_bytes: int
    media_type: str
    server_storage_key: str

    def __post_init__(self):
        if self.version != 1 or self.size_bytes < 1:
            raise ValueError("Original objects require version 1 and nonempty bytes")
        if len(self.content_sha256) != 64 or any(
            ch not in "0123456789abcdef" for ch in self.content_sha256
        ):
            raise ValueError("Invalid SHA-256")
        expected = f"originals/{self.id.hex}/v1/{self.content_sha256}"
        if self.server_storage_key != expected:
            raise ValueError("Object key must be generated from the server object identity")

    def as_dict(self, *, include_storage_key: bool = False) -> dict:
        result = {
            "id": str(self.id),
            "version": self.version,
            "content_sha256": self.content_sha256,
            "size_bytes": self.size_bytes,
            "media_type": self.media_type,
            "scan_status": "not_scanned",
        }
        if include_storage_key:
            result["server_storage_key"] = self.server_storage_key
        return result


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    artifact_id: UUID
    artifact_version: int
    object_ref: ObjectRef

    def __post_init__(self):
        if self.artifact_version < 1:
            raise ValueError("Artifact version must be positive")

    def as_dict(self) -> dict:
        return {
            "artifact_id": str(self.artifact_id),
            "artifact_version": self.artifact_version,
            "object_ref": self.object_ref.as_dict(),
        }


class ObjectStore(Protocol):
    def put_new(self, content: bytes, *, media_type: str) -> ObjectRef: ...

    def read_original(self, reference: ObjectRef) -> bytes: ...
