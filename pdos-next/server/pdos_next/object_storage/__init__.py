"""Private original-byte storage; authorization belongs to the calling domain service."""

from .adapters import LocalPrivateObjectStore, S3PrivateObjectStore
from .types import ArtifactRef, ObjectRef, ObjectStore, StorageFailure

__all__ = [
    "ArtifactRef",
    "LocalPrivateObjectStore",
    "ObjectRef",
    "ObjectStore",
    "S3PrivateObjectStore",
    "StorageFailure",
]
