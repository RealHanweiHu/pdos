"""Private S3-compatible object storage for source documents."""

from __future__ import annotations

from functools import lru_cache
from typing import Protocol, runtime_checkable

import boto3  # type: ignore[import-untyped]
from botocore.config import Config  # type: ignore[import-untyped]

from app.settings import get_settings


class DocumentObjectStore(Protocol):
    def put(self, *, object_key: str, content: bytes, media_type: str, sha256: str) -> None: ...

    def delete(self, *, object_key: str) -> None: ...


@runtime_checkable
class ReadableDocumentObjectStore(DocumentObjectStore, Protocol):
    def get(self, *, object_key: str, max_bytes: int) -> bytes: ...


class S3DocumentObjectStore:
    def __init__(self) -> None:
        settings = get_settings()
        addressing_style = "path" if settings.s3_force_path_style else "virtual"
        self._bucket = settings.s3_bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key_id.get_secret_value(),
            aws_secret_access_key=settings.s3_secret_access_key.get_secret_value(),
            config=Config(signature_version="s3v4", s3={"addressing_style": addressing_style}),
        )

    def put(self, *, object_key: str, content: bytes, media_type: str, sha256: str) -> None:
        self._client.put_object(
            Bucket=self._bucket,
            Key=object_key,
            Body=content,
            ContentLength=len(content),
            ContentType=media_type,
            Metadata={"sha256": sha256},
        )

    def get(self, *, object_key: str, max_bytes: int) -> bytes:
        if not 1 <= max_bytes <= 20 * 1024 * 1024:
            raise ValueError("invalid staged upload read bound")
        response = self._client.get_object(Bucket=self._bucket, Key=object_key)
        body = response["Body"]
        try:
            if int(response.get("ContentLength", 0)) > max_bytes:
                raise ValueError("staged upload exceeds read bound")
            content = body.read(max_bytes + 1)
            if len(content) > max_bytes:
                raise ValueError("staged upload exceeds read bound")
            return bytes(content)
        finally:
            body.close()

    def delete(self, *, object_key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=object_key)


@lru_cache
def get_document_object_store() -> DocumentObjectStore:
    return S3DocumentObjectStore()
