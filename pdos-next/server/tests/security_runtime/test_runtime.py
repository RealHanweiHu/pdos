"""Pure transport boundary cases; fake processes here are not scan qualification."""

import asyncio
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from pdos_next.evidence_processing.parsers import parse_in_worker
from pdos_next.evidence_processing.types import ParseFailure, ParseLimits
from pdos_next.evidence_security.types import (
    ScanBinding,
    ScanLimits,
    ScannerIdentity,
    ScanPolicy,
    ScanRequest,
    ScanStatus,
    SecurityFailure,
)
from pdos_next.object_storage.types import ObjectRef
from pdos_next.security_runtime import docker, parser, scanner


def request(content=b"synthetic original"):
    identity = ScannerIdentity("fake-test-only", "1", "2")
    object_id, digest = uuid4(), hashlib.sha256(content).hexdigest()
    ref = ObjectRef(
        object_id, 1, digest, len(content), "text/plain", f"originals/{object_id.hex}/v1/{digest}"
    )
    binding = ScanBinding(ref, uuid4(), uuid4(), uuid4(), 1, "acl1", "audience1", True)
    return ScanRequest(uuid4(), binding, identity, ScanPolicy(), datetime.now(UTC))


@pytest.mark.parametrize(
    "exit_code,status",
    [
        (0, ScanStatus.CLEAN),
        (1, ScanStatus.INFECTED),
        (2, ScanStatus.UNKNOWN),
        (125, ScanStatus.UNAVAILABLE),
        (137, ScanStatus.UNKNOWN),
    ],
)
def test_only_real_transport_exit_zero_may_certify_clean(monkeypatch, exit_code, status):
    transport = scanner.DockerClamAVTransport()
    intent = request()
    transport._identity = intent.scanner
    calls = []

    async def run(**kwargs):
        calls.append(kwargs)
        return docker.DockerResult(exit_code, b"diagnostic deliberately never returned")

    monkeypatch.setattr(scanner, "run_container", run)
    reply = asyncio.run(transport.inspect(intent, b"synthetic original"))
    assert reply.status == status
    assert reply.scanner == intent.scanner
    assert reply.object_ref == intent.binding.object_ref
    assert reply.request_id == intent.request_id
    assert reply.error_code is None if exit_code == 0 else reply.error_code is not None
    assert calls[0]["image"] == scanner.SCANNER_IMAGE
    assert calls[0]["user"] == "clamav"
    assert "--max-scantime=0" in calls[0]["arguments"]
    assert "--alert-exceeds-max=yes" in calls[0]["arguments"]


def test_configuration_is_observed_not_copied_from_request(monkeypatch):
    async def run(**kwargs):
        assert kwargs["arguments"] == ("--version",)
        return docker.DockerResult(0, b"ClamAV 1.5.4/28123/Mon Sep 14 06:24:19 2026\n")

    monkeypatch.setattr(scanner, "run_container", run)
    transport = scanner.DockerClamAVTransport()
    config = asyncio.run(transport.observe_configuration(ScanPolicy()))
    assert scanner.SCANNER_IMAGE in config.scanner.scanner
    assert config.scanner.engine_version == "1.5.4"
    assert config.scanner.rules_version == "28123/Mon Sep 14 06:24:19 2026"
    intent = request()
    reply = asyncio.run(transport.inspect(intent, b"synthetic original"))
    assert reply.status == ScanStatus.UNKNOWN
    assert reply.error_code == "SCANNER_IDENTITY_MISMATCH"
    assert reply.scanner == config.scanner


def test_missing_actual_identity_never_echoes_untrusted_request(monkeypatch):
    async def run(**kwargs):
        raise docker.DockerFailure("UNAVAILABLE")

    monkeypatch.setattr(scanner, "run_container", run)
    with pytest.raises(SecurityFailure, match="SCANNER_IDENTITY_UNAVAILABLE"):
        asyncio.run(scanner.DockerClamAVTransport().inspect(request(), b"synthetic original"))


@pytest.mark.parametrize("content", [b"different", b"", "not bytes"])
def test_direct_transport_checks_exact_input_identity(monkeypatch, content):
    intent = request()
    transport = scanner.DockerClamAVTransport()
    transport._identity = intent.scanner

    async def forbidden(**kwargs):
        pytest.fail("Mismatched bytes reached scanner")

    monkeypatch.setattr(scanner, "run_container", forbidden)
    reply = asyncio.run(transport.inspect(intent, content))
    assert reply.status == ScanStatus.UNKNOWN
    assert reply.error_code == "SCAN_INPUT_MISMATCH"


def test_timeout_is_not_clean_and_diagnostics_are_not_returned(monkeypatch):
    intent = request()
    transport = scanner.DockerClamAVTransport()
    transport._identity = intent.scanner

    async def run(**kwargs):
        raise docker.DockerFailure("TIMEOUT")

    monkeypatch.setattr(scanner, "run_container", run)
    reply = asyncio.run(transport.inspect(intent, b"synthetic original"))
    assert reply.status == ScanStatus.TIMEOUT
    assert reply.error_code == "SCANNER_TIMEOUT"


def test_output_reader_rejects_overflow_before_full_communicate():
    async def run():
        stream = asyncio.StreamReader()
        stream.feed_data(b"x" * 20_000)
        # No EOF: collecting a complete response would hang indefinitely.
        with pytest.raises(docker.DockerFailure, match="OUTPUT_LIMIT"):
            await docker._bounded_read(stream, 100)

    asyncio.run(run())


class FakeWriter:
    def write(self, chunk):
        pass

    async def drain(self):
        pass

    def close(self):
        pass


class FakeProcess:
    def __init__(self, output=b"", *, hang=False):
        self.stdin = FakeWriter()
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.stdout.feed_data(output)
        self.stdout.feed_eof()
        self.stderr.feed_eof()
        self.returncode = None if hang else 0
        self.hang = hang
        self.killed = False

    async def wait(self):
        if self.hang and not self.killed:
            await asyncio.Event().wait()
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9


@pytest.mark.parametrize("failure", ["timeout", "overflow", "cancel", "cleanup", "timeout_cleanup"])
def test_runner_removes_only_its_owned_container_and_reaps(monkeypatch, failure):
    calls, removed = [], []
    processes = []

    async def create(*args, **kwargs):
        calls.append((args, kwargs))
        process = FakeProcess(
            b"x" * 200 if failure == "overflow" else b"ok",
            hang=failure in ("timeout", "cancel", "timeout_cleanup"),
        )
        processes.append(process)
        return process

    async def remove(name):
        removed.append(name)
        return failure not in ("cleanup", "timeout_cleanup")

    monkeypatch.setattr(docker.asyncio, "create_subprocess_exec", create)
    monkeypatch.setattr(docker, "_remove_owned", remove)

    async def run():
        task = asyncio.create_task(
            docker.run_container(
                image=scanner.SCANNER_IMAGE,
                entrypoint="clamscan",
                arguments=("-",),
                content=b"synthetic",
                timeout_seconds=0.01,
                stdout_maximum=100,
                user="clamav",
                memory_bytes=1_610_612_736,
            )
        )
        if failure == "cancel":
            await asyncio.sleep(0)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            code = {
                "timeout": "TIMEOUT",
                "overflow": "OUTPUT_LIMIT",
                "cleanup": "CLEANUP_UNCONFIRMED",
                "timeout_cleanup": "CLEANUP_UNCONFIRMED",
            }[failure]
            with pytest.raises(docker.DockerFailure, match=code):
                await task

    asyncio.run(run())
    args, kwargs = calls[0]
    assert removed == [args[args.index("--name") + 1]]
    assert removed[0].startswith("pdos-evidence-")
    assert "--network" in args and args[args.index("--network") + 1] == "none"
    assert "--read-only" in args
    assert "--cap-drop" in args and args[args.index("--cap-drop") + 1] == "ALL"
    assert "no-new-privileges:true" in args
    assert "--volume" not in args and "--mount" not in args and "--env" not in args
    assert "--pull" in args and args[args.index("--pull") + 1] == "never"
    assert kwargs["stdout"] == asyncio.subprocess.PIPE
    assert processes[0].returncode is not None


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_sha256", "a" * 64),
        ("scan_status", "clean"),
        ("media_type", "application/pdf"),
        ("status", "success"),
    ],
)
def test_parser_rejects_identity_and_security_protocol_drift(field, value):
    content = b"A\rB\xe2\x80\xa8\rC\n"
    result = parse_in_worker(content, "text/plain", ParseLimits()).as_dict()
    result[field] = value
    with pytest.raises(ParseFailure, match="invalid response"):
        parser._decode(
            json.dumps({"ok": True, "result": result}).encode(),
            content,
            "text/plain",
            ParseLimits(),
        )


def test_parser_preserves_line_locations_without_claiming_scan():
    content = b"A\rB\xe2\x80\xa8\rC\n"
    parsed = parse_in_worker(content, "text/plain", ParseLimits())
    output = json.dumps({"ok": True, "result": parsed.as_dict()}).encode()
    result = parser._decode(output, content, "text/plain", ParseLimits())
    assert result.text == content.decode()
    assert [segment.location.line for segment in result.segments] == [1, 2, 3, 4]
    assert [segment.text for segment in result.segments] == ["A", "B", "", "C"]
    assert result.scan_status == "not_scanned"


def test_no_built_image_means_no_host_fallback(monkeypatch, tmp_path):
    config = tmp_path / "parser-image.json"
    config.write_text('{"image_id":null}')
    monkeypatch.setattr(parser, "_CONFIG_PATH", config)
    with pytest.raises(ParseFailure) as failure:
        parser.DockerParserRunner().parse(b"synthetic", media_type="text/plain")
    assert failure.value.code == "ISOLATION_UNAVAILABLE"


def test_image_override_and_unbounded_limits_are_not_public_parameters():
    with pytest.raises(TypeError):
        parser.DockerParserRunner(image="client-image")
    with pytest.raises(TypeError):
        scanner.DockerClamAVTransport(image="client-image")
    limits = replace(ParseLimits(), timeout_seconds=float("nan"))
    with pytest.raises(ValueError, match="finite"):
        parser._validate(b"synthetic", "text/plain", limits)
    with pytest.raises(ValueError):
        ScanLimits(timeout_seconds=float("nan"))
