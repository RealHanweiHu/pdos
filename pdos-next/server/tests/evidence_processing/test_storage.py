import io
import os
from dataclasses import FrozenInstanceError, replace
from uuid import uuid4

import pytest

from pdos_next.object_storage import (
    ArtifactRef,
    LocalPrivateObjectStore,
    S3PrivateObjectStore,
    StorageFailure,
)


def test_local_original_is_private_immutable_and_hash_verified(tmp_path):
    store = LocalPrivateObjectStore(tmp_path / "private")
    content = b"\nSynthetic original\n"
    reference = store.put_new(content, media_type="text/plain")
    artifact = ArtifactRef(uuid4(), 1, reference)
    assert store.read_original(reference) == content
    assert artifact.as_dict()["object_ref"]["scan_status"] == "not_scanned"
    assert "server_storage_key" not in reference.as_dict()
    assert os.stat(store.root).st_mode & 0o777 == 0o700
    assert os.stat(store.root / reference.server_storage_key).st_mode & 0o777 == 0o600
    with pytest.raises(FrozenInstanceError):
        reference.size_bytes = 1
    second = store.put_new(content, media_type="text/plain")
    assert second.id != reference.id
    assert second.content_sha256 == reference.content_sha256
    assert store.read_original(reference) == content
    with pytest.raises(ValueError):
        replace(reference, server_storage_key="../other")
    with pytest.raises(ValueError):
        replace(reference, version=2)


def test_stored_bytes_tamper_symlink_and_missing_are_refused(tmp_path):
    store = LocalPrivateObjectStore(tmp_path / "private")
    reference = store.put_new(b"original", media_type="text/plain")
    path = store.root / reference.server_storage_key
    path.write_bytes(b"tampered")
    with pytest.raises(StorageFailure) as failure:
        store.read_original(reference)
    assert failure.value.code == "INTEGRITY_MISMATCH"
    path.unlink()
    with pytest.raises(StorageFailure) as failure:
        store.read_original(reference)
    assert failure.value.code == "OBJECT_NOT_FOUND"
    outside = tmp_path / "outside"
    outside.write_bytes(b"original")
    path.symlink_to(outside)
    with pytest.raises(StorageFailure) as failure:
        store.read_original(reference)
    assert failure.value.code == "UNSAFE_STORAGE_PATH"


def test_local_storage_rejects_public_root_and_unbounded_original(tmp_path):
    root = tmp_path / "public"
    root.mkdir(mode=0o755)
    with pytest.raises(StorageFailure) as failure:
        LocalPrivateObjectStore(root)
    assert failure.value.code == "UNSAFE_STORAGE_ROOT"
    store = LocalPrivateObjectStore(tmp_path / "private", max_bytes=5)
    for content, media, code in [
        (b"abcdef", "text/plain", "FILE_TOO_LARGE"),
        (b"abcd", "application/x-python", "UNSUPPORTED_MEDIA_TYPE"),
        (b"", "text/plain", "INVALID_BYTES"),
    ]:
        with pytest.raises(StorageFailure) as failure:
            store.put_new(content, media_type=media)
        assert failure.value.code == code


class FakeS3:
    def __init__(self):
        self.objects = {}
        self.requests = []

    def put_object(self, **request):
        self.requests.append(request)
        assert request["IfNoneMatch"] == "*"
        assert (request["Bucket"], request["Key"]) not in self.objects
        self.objects[request["Bucket"], request["Key"]] = request["Body"]

    def get_object(self, **request):
        self.requests.append(request)
        content = self.objects[request["Bucket"], request["Key"]]
        return {"ContentLength": len(content), "Body": io.BytesIO(content)}


def test_s3_client_is_injected_uses_generated_key_and_conditional_put():
    client = FakeS3()
    store = S3PrivateObjectStore(client, bucket="synthetic-private", prefix="synthetic/pdos-next")
    reference = store.put_new(b"original", media_type="application/pdf")
    assert store.read_original(reference) == b"original"
    assert client.requests[0]["Key"] == f"synthetic/pdos-next/{reference.server_storage_key}"
    assert client.requests[0]["Metadata"]["sha256"] == reference.content_sha256
    client.objects["synthetic-private", client.requests[0]["Key"]] = b"tampered"
    with pytest.raises(StorageFailure) as failure:
        store.read_original(reference)
    assert failure.value.code == "INTEGRITY_MISMATCH"


def test_s3_bad_prefix_and_unknown_failure_do_not_expose_source_or_credentials():
    with pytest.raises(ValueError):
        S3PrivateObjectStore(FakeS3(), bucket="synthetic", prefix="../unsafe")

    class BrokenS3:
        def put_object(self, **request):
            raise RuntimeError("SECRET credential and source bytes")

    store = S3PrivateObjectStore(BrokenS3(), bucket="synthetic")
    with pytest.raises(StorageFailure) as failure:
        store.put_new(b"original", media_type="text/plain")
    assert failure.value.code == "STORAGE_UNAVAILABLE"
    assert "SECRET" not in failure.value.message and failure.value.retryable
