import hashlib
import os
import stat
from pathlib import Path
from typing import Any
from uuid import uuid4

from .types import ObjectRef, StorageFailure

SUPPORTED_MEDIA = frozenset(
    {
        "text/plain",
        "text/markdown",
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
)


def _reference(content: bytes, media_type: str, limit: int) -> ObjectRef:
    if not isinstance(content, bytes) or not content:
        raise StorageFailure("INVALID_BYTES", "A nonempty original byte sequence is required")
    if len(content) > limit:
        raise StorageFailure("FILE_TOO_LARGE", "Original exceeds the configured byte limit")
    if media_type not in SUPPORTED_MEDIA:
        raise StorageFailure("UNSUPPORTED_MEDIA_TYPE", "Original media type is not supported")
    identity, digest = uuid4(), hashlib.sha256(content).hexdigest()
    return ObjectRef(
        identity,
        1,
        digest,
        len(content),
        media_type,
        f"originals/{identity.hex}/v1/{digest}",
    )


def _verify(content: bytes, reference: ObjectRef, limit: int) -> bytes:
    if reference.size_bytes > limit or len(content) > limit:
        raise StorageFailure("FILE_TOO_LARGE", "Original exceeds the configured byte limit")
    if len(content) != reference.size_bytes or hashlib.sha256(content).hexdigest() != (
        reference.content_sha256
    ):
        raise StorageFailure("INTEGRITY_MISMATCH", "Stored original does not match its reference")
    return content


class LocalPrivateObjectStore:
    """A server-configured private directory, never a caller-supplied path or filename."""

    def __init__(self, root: Path | str, *, max_bytes: int = 10_000_000):
        if max_bytes < 1:
            raise ValueError("Positive storage limit required")
        original_root = Path(root)
        if original_root.is_symlink():
            raise StorageFailure("UNSAFE_STORAGE_ROOT", "Storage root must be a private directory")
        original_root.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.root = original_root.resolve()
        if not self.root.is_dir() or stat.S_IMODE(self.root.stat().st_mode) & 0o077:
            raise StorageFailure(
                "UNSAFE_STORAGE_ROOT", "Storage root must have private permissions"
            )
        self.max_bytes = max_bytes

    def _path(self, reference: ObjectRef) -> Path:
        # ObjectRef rejects keys that are not generated from its immutable identity.
        path = self.root / reference.server_storage_key
        if any(parent.is_symlink() for parent in (path, *path.parents) if parent != self.root):
            raise StorageFailure("UNSAFE_STORAGE_PATH", "Object path is unavailable")
        return path

    def put_new(self, content: bytes, *, media_type: str) -> ObjectRef:
        reference = _reference(content, media_type, self.max_bytes)
        path = self._path(reference)
        try:
            path.parent.mkdir(parents=True, mode=0o700, exist_ok=False)
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(path, flags, 0o600)
            with os.fdopen(fd, "wb") as original:
                original.write(content)
                original.flush()
                os.fsync(original.fileno())
        except FileExistsError as exc:
            raise StorageFailure("OBJECT_EXISTS", "Original objects cannot be overwritten") from exc
        except OSError as exc:
            raise StorageFailure(
                "STORAGE_UNAVAILABLE", "Original storage is unavailable", retryable=True
            ) from exc
        return reference

    def read_original(self, reference: ObjectRef) -> bytes:
        if reference.size_bytes > self.max_bytes:
            raise StorageFailure("FILE_TOO_LARGE", "Original exceeds the configured byte limit")
        path = self._path(reference)
        try:
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(fd, "rb") as original:
                if not stat.S_ISREG(os.fstat(original.fileno()).st_mode):
                    raise StorageFailure("UNSAFE_STORAGE_PATH", "Original must be a regular file")
                content = original.read(self.max_bytes + 1)
        except FileNotFoundError as exc:
            raise StorageFailure("OBJECT_NOT_FOUND", "Original object is unavailable") from exc
        except OSError as exc:
            raise StorageFailure(
                "STORAGE_UNAVAILABLE", "Original storage is unavailable", retryable=True
            ) from exc
        return _verify(content, reference, self.max_bytes)


class S3PrivateObjectStore:
    """Injected S3-compatible client and existing private bucket; creates no cloud resources."""

    def __init__(
        self, client: Any, *, bucket: str, prefix: str = "pdos-next", max_bytes: int = 10_000_000
    ):
        if not bucket or not prefix or prefix.startswith("/") or ".." in prefix.split("/"):
            raise ValueError("An explicit existing bucket and safe server prefix are required")
        if max_bytes < 1:
            raise ValueError("Positive storage limit required")
        self.client, self.bucket, self.prefix, self.max_bytes = (
            client,
            bucket,
            prefix.strip("/"),
            max_bytes,
        )

    def put_new(self, content: bytes, *, media_type: str) -> ObjectRef:
        reference = _reference(content, media_type, self.max_bytes)
        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=f"{self.prefix}/{reference.server_storage_key}",
                Body=content,
                ContentType=reference.media_type,
                IfNoneMatch="*",
                Metadata={"sha256": reference.content_sha256, "version": "1"},
            )
        except Exception as exc:
            response = getattr(exc, "response", {})
            if response.get("Error", {}).get("Code") in {
                "PreconditionFailed",
                "ConditionalRequestConflict",
            }:
                raise StorageFailure(
                    "OBJECT_EXISTS", "Original objects cannot be overwritten"
                ) from exc
            raise StorageFailure(
                "STORAGE_UNAVAILABLE", "Original storage is unavailable", retryable=True
            ) from exc
        return reference

    def read_original(self, reference: ObjectRef) -> bytes:
        if reference.size_bytes > self.max_bytes:
            raise StorageFailure("FILE_TOO_LARGE", "Original exceeds the configured byte limit")
        body = None
        try:
            response = self.client.get_object(
                Bucket=self.bucket,
                Key=f"{self.prefix}/{reference.server_storage_key}",
            )
            body = response["Body"]
            if response.get("ContentLength") != reference.size_bytes:
                raise StorageFailure(
                    "INTEGRITY_MISMATCH", "Stored original does not match its reference"
                )
            content = body.read(self.max_bytes + 1)
        except StorageFailure:
            raise
        except Exception as exc:
            response = getattr(exc, "response", {})
            if response.get("Error", {}).get("Code") in {"NoSuchKey", "404", "NotFound"}:
                raise StorageFailure("OBJECT_NOT_FOUND", "Original object is unavailable") from exc
            raise StorageFailure(
                "STORAGE_UNAVAILABLE", "Original storage is unavailable", retryable=True
            ) from exc
        finally:
            if body is not None:
                body.close()
        return _verify(content, reference, self.max_bytes)
