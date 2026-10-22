"""Actual local ClamAV transport. This profile is not production qualification."""

import asyncio
import hashlib
import re

from pdos_next.evidence_security.types import (
    ScanConfiguration,
    ScannerIdentity,
    ScannerReply,
    ScanPolicy,
    ScanRequest,
    ScanStatus,
    SecurityFailure,
)

from .docker import DockerFailure, run_container

SCANNER_IMAGE = "sha256:388419d4ffc5caaa9c1557b81adf4608462d739560506a1288311e762978549e"
_VERSION = re.compile(r"ClamAV ([0-9]+\.[0-9]+\.[0-9]+)/([0-9]+)/([^\r\n]{1,80})\s*\Z")


class DockerClamAVTransport:
    """Fixed immutable image, actual observed identity, no configurable client argv."""

    def __init__(self):
        self._identity: ScannerIdentity | None = None

    async def observe_configuration(self, policy: ScanPolicy) -> ScanConfiguration:
        if not isinstance(policy, ScanPolicy):
            raise ValueError("A server-owned typed scan policy is required")
        try:
            result = await run_container(
                image=SCANNER_IMAGE,
                entrypoint="clamscan",
                arguments=("--version",),
                content=b"",
                timeout_seconds=policy.limits.timeout_seconds,
                stdout_maximum=4_096,
                user="clamav",
                memory_bytes=1_610_612_736,
            )
            match = _VERSION.fullmatch(result.stdout.decode("ascii", "strict").strip())
            if result.returncode != 0 or match is None:
                raise SecurityFailure("SCANNER_IDENTITY_UNAVAILABLE")
            identity = ScannerIdentity(
                scanner="clamav-container:" + SCANNER_IMAGE,
                engine_version=match[1],
                rules_version=match[2] + "/" + match[3],
            )
            if self._identity is not None and self._identity != identity:
                raise SecurityFailure("SCANNER_IDENTITY_CHANGED")
            self._identity = identity
            return ScanConfiguration(identity, policy)
        except (DockerFailure, UnicodeError) as exc:
            raise SecurityFailure("SCANNER_IDENTITY_UNAVAILABLE") from exc

    async def inspect(self, request: ScanRequest, content: bytes) -> ScannerReply:
        if not isinstance(request, ScanRequest):
            raise ValueError("A server-bound scan request is required")
        # Reply identity always comes from the actual immutable scanner, never
        # from trusting the request's scanner label.
        try:
            async with asyncio.timeout(request.policy.limits.timeout_seconds):
                if self._identity is None:
                    await self.observe_configuration(request.policy)
                assert self._identity is not None
                identity = self._identity
                if request.scanner != identity:
                    return ScannerReply(
                        request.request_id,
                        request.binding.object_ref,
                        identity,
                        ScanStatus.UNKNOWN,
                        "SCANNER_IDENTITY_MISMATCH",
                    )
                ref = request.binding.object_ref
                if (
                    not isinstance(content, bytes)
                    or not content
                    or len(content) != ref.size_bytes
                    or len(content) > request.policy.limits.max_input_bytes
                    or hashlib.sha256(content).hexdigest() != ref.content_sha256
                    or request.binding.source_active is not True
                ):
                    return ScannerReply(
                        request.request_id,
                        ref,
                        identity,
                        ScanStatus.UNKNOWN,
                        "SCAN_INPUT_MISMATCH",
                    )
                limits = request.policy.limits
                result = await run_container(
                    image=SCANNER_IMAGE,
                    entrypoint="clamscan",
                    arguments=(
                        "--quiet",
                        "--no-summary",
                        "--tempdir=/tmp",
                        "--official-db-only=yes",
                        "--bytecode-unsigned=no",
                        "--alert-exceeds-max=yes",
                        "--alert-encrypted=yes",
                        "--alert-macros=yes",
                        # ClamAV otherwise assumes a scan-time skip is clean.
                        # The parent deadline kills the entire owned container.
                        "--max-scantime=0",
                        f"--max-filesize={limits.max_input_bytes}",
                        f"--max-scansize={limits.max_zip_expanded_bytes + limits.max_input_bytes}",
                        f"--max-files={limits.max_zip_entries}",
                        "--max-recursion=32",
                        "-",
                    ),
                    content=content,
                    timeout_seconds=limits.timeout_seconds,
                    stdout_maximum=65_536,
                    user="clamav",
                    memory_bytes=1_610_612_736,
                )
                if result.returncode == 0:
                    status, code = ScanStatus.CLEAN, None
                elif result.returncode == 1:
                    status, code = ScanStatus.INFECTED, "MALWARE_DETECTED"
                elif result.returncode in (125, 126, 127):
                    status, code = ScanStatus.UNAVAILABLE, "SCANNER_UNAVAILABLE"
                else:
                    status, code = ScanStatus.UNKNOWN, "SCANNER_ERROR"
                return ScannerReply(request.request_id, ref, identity, status, code)
        except (DockerFailure, TimeoutError, SecurityFailure) as exc:
            # If identity was never observed, do not fabricate one from payload.
            if self._identity is None:
                raise SecurityFailure("SCANNER_IDENTITY_UNAVAILABLE") from exc
            code = getattr(exc, "code", "TIMEOUT")
            if code == "TIMEOUT":
                status, error = ScanStatus.TIMEOUT, "SCANNER_TIMEOUT"
            elif code == "UNAVAILABLE":
                status, error = ScanStatus.UNAVAILABLE, "SCANNER_UNAVAILABLE"
            else:
                status, error = ScanStatus.UNKNOWN, "SCANNER_" + code
            return ScannerReply(
                request.request_id, request.binding.object_ref, self._identity, status, error
            )
