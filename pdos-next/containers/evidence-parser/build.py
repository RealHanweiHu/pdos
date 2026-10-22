"""Build from an already retrieved official Python base with a secret-free context.

Run with the server's existing Python interpreter. This copies ONLY the two pure
parser source files and the files in this directory; no repository-wide Docker
context, .env, business package, host site-packages or database files are sent.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path

DIRECTORY = Path(__file__).resolve().parent
SERVER = DIRECTORY.parents[1] / "server"
ALLOWED_BASES = ("python:3.12-slim", "public.ecr.aws/docker/library/python:3.12-slim")
PIN = re.compile(
    r"(?:python|docker.io/library/python|public.ecr.aws/docker/library/python)@sha256:[0-9a-f]{64}\Z"
)


def _read(command: list[str]) -> str:
    return subprocess.run(
        command, check=True, capture_output=True, text=True, timeout=30
    ).stdout.strip()


def _download_wheels(directory: Path) -> dict[str, str]:
    # Download, do not install anything in the host runtime or change its locks.
    # Verify PyPI's published SHA256 and use only pure-Python wheels.
    hashes = {}
    for package, version in (("pypdf", "6.19.0"), ("openpyxl", "3.1.5"), ("et-xmlfile", "2.0.0")):
        with urllib.request.urlopen(
            f"https://pypi.org/pypi/{package}/{version}/json", timeout=30
        ) as response:
            metadata = json.loads(response.read(2_000_000))
        matches = [
            value
            for value in metadata["urls"]
            if value["filename"].endswith("py3-none-any.whl")
            and value["url"].startswith("https://files.pythonhosted.org/")
        ]
        if len(matches) != 1:
            raise RuntimeError("A unique pinned pure-Python wheel is required")
        wheel = matches[0]
        with urllib.request.urlopen(wheel["url"], timeout=60) as response:
            content = response.read(20_000_001)
        digest = hashlib.sha256(content).hexdigest()
        if len(content) > 20_000_000 or digest != wheel["digests"]["sha256"]:
            raise RuntimeError("Pinned parser dependency hash mismatch")
        filename = wheel["filename"]
        if Path(filename).name != filename:
            raise RuntimeError("Invalid dependency filename")
        (directory / filename).write_bytes(content)
        hashes[filename] = digest
    return hashes


def main():
    arguments = argparse.ArgumentParser()
    arguments.add_argument("--base", choices=ALLOWED_BASES, default=ALLOWED_BASES[0])
    base = arguments.parse_args().base
    digests = json.loads(
        _read(["docker", "image", "inspect", base, "--format", "{{json .RepoDigests}}"])
    )
    matches = sorted(value for value in digests if isinstance(value, str) and PIN.fullmatch(value))
    legacy = not matches
    if legacy:
        lock = json.loads((DIRECTORY / "base-image.json").read_text())
        actual_id = _read(["docker", "image", "inspect", base, "--format", "{{.Id}}"])
        if (
            lock["repository"] != "docker.io/library/python"
            or lock["tag"] != "3.12-slim"
            or lock["image_id"] != actual_id
            or re.fullmatch(r"sha256:[0-9a-f]{64}", actual_id) is None
            or lock["transport"] != "anonymous_official_https_digest_verified_docker_load"
        ):
            raise RuntimeError("A locally verified official Python base digest is required")
        # The legacy builder accepts the local content-addressed config ID. This
        # avoids resolving a mutable tag or repeating the failing daemon network.
        pinned_base = actual_id
    else:
        pinned_base = matches[0]
    source = SERVER / "pdos_next/evidence_processing"
    hashes = {
        name: hashlib.sha256((source / name).read_bytes()).hexdigest()
        for name in ("types.py", "parsers.py")
    }
    with tempfile.TemporaryDirectory(prefix="pdos-parser-context-") as temporary:
        context = Path(temporary)
        pure = context / "pdos_next/evidence_processing"
        pure.mkdir(parents=True)
        (context / "pdos_next/__init__.py").write_text("")
        (pure / "__init__.py").write_text("")
        for name in hashes:
            shutil.copyfile(source / name, pure / name)
        for name in ("Dockerfile", "requirements.txt", "parser_worker.py"):
            shutil.copyfile(DIRECTORY / name, context / name)
        wheels = context / "wheels"
        wheels.mkdir()
        wheel_hashes = _download_wheels(wheels)
        environment = {
            key: value
            for key in ("PATH", "HOME", "USER")
            if (value := os.environ.get(key)) is not None
        }
        if legacy:
            environment["DOCKER_BUILDKIT"] = "0"
        subprocess.run(
            [
                "docker",
                "build",
                "--tag",
                "pdos-evidence-parser:local-v1",
                "--build-arg",
                "PYTHON_BASE=" + pinned_base,
                str(context),
            ],
            check=True,
            timeout=600,
            env=environment,
        )
    image_id = _read(
        ["docker", "image", "inspect", "pdos-evidence-parser:local-v1", "--format", "{{.Id}}"]
    )
    if re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is None:
        raise RuntimeError("Built immutable image identity unavailable")
    artifact = {
        "image_id": image_id,
        "base_image": pinned_base,
        "parser_version": "pdos-evidence-v1",
        "source_sha256": hashes,
        "entrypoint_sha256": hashlib.sha256(
            (DIRECTORY / "parser_worker.py").read_bytes()
        ).hexdigest(),
        "dependencies": {"pypdf": "6.19.0", "openpyxl": "3.1.5", "et-xmlfile": "2.0.0"},
        "wheel_sha256": wheel_hashes,
        "state": "built_local_unqualified",
    }
    path = SERVER / "pdos_next/security_runtime/parser-image.json"
    path.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"image_id": image_id, "state": artifact["state"]}))


if __name__ == "__main__":
    main()
