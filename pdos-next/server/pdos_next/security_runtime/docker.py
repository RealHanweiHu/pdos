"""Bounded Docker client transport; document bytes never become shell code or mounts.

The host process needs its local Docker daemon. The document container receives no
daemon socket, host directory, credential environment, devices, or network.
"""

import asyncio
import os
from dataclasses import dataclass
from uuid import uuid4


class DockerFailure(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class DockerResult:
    returncode: int
    stdout: bytes


def _client_environment() -> dict[str, str]:
    # Docker Desktop's selected local context is discovered by the host CLI. No
    # host environment variable is passed with docker --env into the container.
    return {
        key: value
        for key in ("PATH", "HOME", "USER", "LANG", "TMPDIR")
        if (value := os.environ.get(key)) is not None
    }


async def _bounded_read(stream: asyncio.StreamReader, maximum: int) -> bytes:
    data = bytearray()
    while chunk := await stream.read(16_384):
        if len(data) + len(chunk) > maximum:
            raise DockerFailure("OUTPUT_LIMIT")
        data.extend(chunk)
    return bytes(data)


async def _send(process: asyncio.subprocess.Process, content: bytes) -> None:
    assert process.stdin is not None
    try:
        for offset in range(0, len(content), 65_536):
            process.stdin.write(content[offset : offset + 65_536])
            await process.stdin.drain()
    except (BrokenPipeError, ConnectionResetError):
        # A container may return a bounded failure before reading the full request.
        pass
    finally:
        process.stdin.close()


async def _discard(stream: asyncio.StreamReader) -> None:
    # Unread pipes can keep Process.wait() pending when its transport is paused.
    # After killing the client, discard incrementally without retaining content.
    while await stream.read(16_384):
        pass


async def _remove_owned(name: str) -> bool:
    """Remove exactly the generated name, never prune or inspect other containers."""
    process = None
    try:
        async with asyncio.timeout(5):
            # Cancelled startup can leave no container. Confirm that exact name
            # twice; a general daemon failure never establishes safe absence.
            for attempt in range(2):
                process = await asyncio.create_subprocess_exec(
                    "docker",
                    "container",
                    "rm",
                    "--force",
                    name,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,
                    env=_client_environment(),
                )
                assert process.stderr is not None
                result, diagnostic = await asyncio.gather(
                    process.wait(), _bounded_read(process.stderr, 8_192)
                )
                if result == 0:
                    return True
                absent = ("Error response from daemon: No such container: " + name).encode()
                if result != 1 or diagnostic.strip() != absent:
                    return False
                if attempt == 0:
                    await asyncio.sleep(0.05)
            return True
    except (TimeoutError, OSError, DockerFailure):
        return False
    finally:
        if process is not None and process.returncode is None:
            process.kill()
            await process.wait()


async def run_container(
    *,
    image: str,
    entrypoint: str,
    arguments: tuple[str, ...],
    content: bytes,
    timeout_seconds: float,
    stdout_maximum: int,
    user: str,
    memory_bytes: int,
    pids: int = 32,
    cpus: int = 2,
) -> DockerResult:
    """Internal server-only runner. All callers supply fixed image/entrypoint/options.

    The deadline includes client startup, stdin transfer and both output streams.
    On timeout/cancellation/overflow, force removal and process reaping occur before
    the call returns. Cleanup has its own small bounded grace period; if the daemon
    cannot confirm removal, fail closed with CLEANUP_UNCONFIRMED.
    """
    name = "pdos-evidence-" + uuid4().hex
    process = None
    tasks: list[asyncio.Task] = []
    cancelled = False
    try:
        async with asyncio.timeout(timeout_seconds):
            process = await asyncio.create_subprocess_exec(
                "docker",
                "run",
                "--name",
                name,
                "--pull",
                "never",
                "--network",
                "none",
                "--read-only",
                "--user",
                user,
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges:true",
                "--pids-limit",
                str(pids),
                "--memory",
                str(memory_bytes),
                "--memory-swap",
                str(memory_bytes),
                "--cpus",
                str(cpus),
                "--ulimit",
                "nofile=64:64",
                "--ulimit",
                "core=0:0",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,nodev,size=33554432,mode=1777",
                "--workdir",
                "/tmp",
                "--interactive",
                "--entrypoint",
                entrypoint,
                image,
                *arguments,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=_client_environment(),
                limit=65_536,
            )
            assert process.stdout is not None and process.stderr is not None
            tasks = [
                asyncio.create_task(_send(process, content)),
                asyncio.create_task(_bounded_read(process.stdout, stdout_maximum)),
                asyncio.create_task(_bounded_read(process.stderr, 65_536)),
                asyncio.create_task(process.wait()),
            ]
            _, stdout, _, returncode = await asyncio.gather(*tasks)
            return DockerResult(returncode, stdout)
    except TimeoutError as exc:
        raise DockerFailure("TIMEOUT") from exc
    except OSError as exc:
        raise DockerFailure("UNAVAILABLE") from exc
    except asyncio.CancelledError:
        cancelled = True
        raise
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        # Removing a finished container also ensures there is no retained input
        # filesystem. Use no --rm race so successful removal is positively known.
        if process is not None and process.returncode is None:
            process.kill()
        # Stop the host client before removing the container. Otherwise a run
        # still starting could create/start the same name after the remove call.
        discard = []
        if process is not None:
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    discard.append(asyncio.create_task(_discard(stream)))
        removed = await asyncio.shield(_remove_owned(name))
        if process is not None:
            try:
                async with asyncio.timeout(1):
                    await process.wait()
                    await asyncio.gather(*discard)
            except TimeoutError as exc:
                raise DockerFailure("CLEANUP_UNCONFIRMED") from exc
            finally:
                for task in discard:
                    if not task.done():
                        task.cancel()
                if discard:
                    await asyncio.gather(*discard, return_exceptions=True)
        if process is not None and not removed:
            # Do not mask task cancellation, but never return successful bytes if
            # daemon cleanup could not be verified.
            if not cancelled:
                raise DockerFailure("CLEANUP_UNCONFIRMED")
