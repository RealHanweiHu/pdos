"""Recover an official Python base when the local daemon registry path is unavailable.

Uses only anonymous public registry auth, verifies every OCI content digest, sends
no business data, and loads one exact linux/arm64 official image. Does not alter
Docker daemon configuration, read credentials, or print the anonymous bearer token.
"""

import gzip
import hashlib
import json
import subprocess
import tarfile
import tempfile
import urllib.request
from pathlib import Path

REGISTRY = "https://registry-1.docker.io/v2/library/python"
DIRECTORY = Path(__file__).resolve().parent
ACCEPT = (
    "application/vnd.oci.image.index.v1+json,"
    "application/vnd.docker.distribution.manifest.list.v2+json,"
    "application/vnd.oci.image.manifest.v1+json,"
    "application/vnd.docker.distribution.manifest.v2+json"
)


def main():
    authorization = urllib.request.urlopen(
        "https://auth.docker.io/token?service=registry.docker.io&scope=repository:library/python:pull",
        timeout=30,
    )
    token = json.loads(authorization.read(100_000))["token"]

    def read(path: str, maximum: int = 2_000_000) -> bytes:
        request = urllib.request.Request(
            REGISTRY + path, headers={"Authorization": "Bearer " + token, "Accept": ACCEPT}
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            data = response.read(maximum + 1)
        if len(data) > maximum:
            raise RuntimeError("Official registry response exceeded its download budget")
        return data

    index_bytes = read("/manifests/3.12-slim")
    index = json.loads(index_bytes)
    candidates = [
        value
        for value in index["manifests"]
        if value["platform"].get("os") == "linux"
        and value["platform"].get("architecture") == "arm64"
        and value["platform"].get("variant", "v8") == "v8"
    ]
    if len(candidates) != 1:
        raise RuntimeError("A unique official linux/arm64 base is required")
    manifest_digest = candidates[0]["digest"]
    manifest_bytes = read("/manifests/" + manifest_digest)
    if "sha256:" + hashlib.sha256(manifest_bytes).hexdigest() != manifest_digest:
        raise RuntimeError("Official image manifest digest mismatch")
    manifest = json.loads(manifest_bytes)
    config_digest = manifest["config"]["digest"]
    with tempfile.TemporaryDirectory(prefix="pdos-official-python-") as temporary:
        directory = Path(temporary)
        config = read("/blobs/" + config_digest)
        if "sha256:" + hashlib.sha256(config).hexdigest() != config_digest:
            raise RuntimeError("Official image configuration digest mismatch")
        config_path = directory / (config_digest.removeprefix("sha256:") + ".json")
        config_path.write_bytes(config)
        layers = []
        downloaded = 0
        expanded = 0
        for layer in manifest["layers"]:
            blob = read("/blobs/" + layer["digest"], 100_000_000)
            downloaded += len(blob)
            if downloaded > 250_000_000:
                raise RuntimeError("Official base exceeds the download budget")
            if "sha256:" + hashlib.sha256(blob).hexdigest() != layer["digest"]:
                raise RuntimeError("Official image layer digest mismatch")
            folder = directory / layer["digest"].removeprefix("sha256:")
            folder.mkdir()
            compressed = folder / "layer.gz"
            compressed.write_bytes(blob)
            layer_path = folder / "layer.tar"
            with gzip.open(compressed, "rb") as stream, layer_path.open("wb") as target:
                while chunk := stream.read(1_000_000):
                    expanded += len(chunk)
                    if expanded > 500_000_000:
                        raise RuntimeError("Official base exceeds the expansion budget")
                    target.write(chunk)
            layers.append(str(layer_path.relative_to(directory)))
        archive_manifest = directory / "manifest.json"
        archive_manifest.write_text(
            json.dumps(
                [{"Config": config_path.name, "RepoTags": ["python:3.12-slim"], "Layers": layers}]
            )
        )
        archive = directory / "official-python.tar"
        with tarfile.open(archive, "w") as target:
            for name in [config_path.name, "manifest.json", *layers]:
                target.add(directory / name, arcname=name, recursive=False)
        subprocess.run(["docker", "load", "--input", str(archive)], check=True, timeout=120)
    actual = subprocess.run(
        ["docker", "image", "inspect", "python:3.12-slim", "--format", "{{.Id}}"],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.strip()
    if actual != config_digest:
        raise RuntimeError("Loaded official base image differs from its verified config")
    artifact = {
        "repository": "docker.io/library/python",
        "tag": "3.12-slim",
        "platform": "linux/arm64/v8",
        "index_digest": "sha256:" + hashlib.sha256(index_bytes).hexdigest(),
        "manifest_digest": manifest_digest,
        "image_id": config_digest,
        "layer_digests": [layer["digest"] for layer in manifest["layers"]],
        "transport": "anonymous_official_https_digest_verified_docker_load",
    }
    (DIRECTORY / "base-image.json").write_text(json.dumps(artifact, indent=2) + "\n")
    print(json.dumps({"image_id": actual, "manifest_digest": manifest_digest}))


if __name__ == "__main__":
    main()
