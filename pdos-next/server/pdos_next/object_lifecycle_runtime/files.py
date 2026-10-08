"""Private descriptor-based lifecycle metadata. Never writes original byte paths."""

import fcntl
import hashlib
import json
import os
import stat
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4


class RuntimeFailure(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def seal(value):
    return {**value, "sha256": digest(value)}


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate metadata key")
        result[key] = value
    return result


class PrivateFiles:
    def __init__(self, journal_root, deadline):
        self.deadline = deadline
        self.fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in Path(journal_root).absolute().parts[1:]:
                following = os.open(
                    part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=self.fd
                )
                os.close(self.fd)
                self.fd = following
            self._private(self.fd, directory=True)
            try:
                os.mkdir("lifecycle-runtime-v1", 0o700, dir_fd=self.fd)
                os.fsync(self.fd)
            except FileExistsError:
                pass
            following = os.open(
                "lifecycle-runtime-v1", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=self.fd
            )
            os.close(self.fd)
            self.fd = following
            self._private(self.fd, directory=True)
            for name in ("objects", "operations", "locks"):
                with self.directory((name,), create=True):
                    pass
        except (OSError, RuntimeFailure):
            os.close(self.fd)
            raise RuntimeFailure("LIFECYCLE_METADATA_UNAVAILABLE") from None

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def check(self):
        if time.monotonic() >= self.deadline:
            raise RuntimeFailure("LIFECYCLE_IO_TIMEOUT")

    @staticmethod
    def _private(fd, *, directory=False):
        info = os.fstat(fd)
        kind = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
        if (
            not kind
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o077
            or (not directory and info.st_nlink != 1)
        ):
            raise RuntimeFailure("LIFECYCLE_METADATA_UNSAFE")

    @contextmanager
    def directory(self, parts, *, create=False):
        self.check()
        fd = os.dup(self.fd)
        try:
            for part in parts:
                if not isinstance(part, str) or part in ("", ".", "..") or "/" in part:
                    raise RuntimeFailure("LIFECYCLE_METADATA_UNSAFE")
                if create:
                    try:
                        os.mkdir(part, 0o700, dir_fd=fd)
                        os.fsync(fd)
                    except FileExistsError:
                        pass
                following = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                self._private(following, directory=True)
                os.close(fd)
                fd = following
            yield fd
        finally:
            os.close(fd)

    @contextmanager
    def locked(self, object_id, operation_id=None, *, shared=False):
        with self.directory(("locks",)) as folder:
            descriptors = []
            try:
                names = ["object-" + object_id.hex]
                if operation_id is not None:
                    names.append("operation-" + operation_id.hex)
                for name in names:
                    try:
                        # One creator; O_EXCL also rejects a final symlink. A
                        # concurrent first access opens the existing lock through
                        # the separate no-follow path, like the upload journal.
                        fd = os.open(
                            name,
                            os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
                            0o600,
                            dir_fd=folder,
                        )
                    except FileExistsError:
                        fd = os.open(name, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=folder)
                    descriptors.append(fd)
                    self._private(fd)
                    operation = fcntl.LOCK_SH if shared else fcntl.LOCK_EX
                    while True:
                        self.check()
                        try:
                            fcntl.flock(fd, operation | fcntl.LOCK_NB)
                            break
                        except BlockingIOError:
                            time.sleep(min(0.01, max(0, self.deadline - time.monotonic())))
                yield
            finally:
                for fd in reversed(descriptors):
                    os.close(fd)

    def read(self, parts):
        self.check()
        try:
            with self.directory(parts[:-1]) as folder:
                fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=folder)
                try:
                    self._private(fd)
                    with os.fdopen(fd, "rb", closefd=False) as stream:
                        raw = stream.read(65_537)
                finally:
                    os.close(fd)
        except FileNotFoundError:
            return None
        if len(raw) > 65_536:
            raise RuntimeFailure("LIFECYCLE_METADATA_CORRUPT")
        try:
            value = json.loads(raw, object_pairs_hook=unique)
            expected = value.pop("sha256")
            if not isinstance(expected, str) or digest(value) != expected:
                raise ValueError("Metadata digest mismatch")
            return {**value, "sha256": expected}
        except (ValueError, KeyError, TypeError, AttributeError):
            raise RuntimeFailure("LIFECYCLE_METADATA_CORRUPT") from None

    def write_new(self, parts, value):
        self.check()
        content = canonical(value)
        if len(content) > 65_536:
            raise RuntimeFailure("LIFECYCLE_METADATA_LIMIT")
        with self.directory(parts[:-1], create=True) as folder:
            fd = os.open(
                parts[-1],
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=folder,
            )
            try:
                view = memoryview(content)
                while view:
                    self.check()
                    count = os.write(fd, view)
                    if count <= 0:
                        raise RuntimeFailure("LIFECYCLE_METADATA_UNAVAILABLE")
                    view = view[count:]
                os.fsync(fd)
            finally:
                os.close(fd)
            os.fsync(folder)
        self.check()

    def replace_head(self, parts, value):
        # Only an access marker pointer is replaced. No original, attempt, event
        # or terminal file is ever overwritten or deleted.
        temporary = (*parts[:-1], "head-" + uuid4().hex + ".tmp")
        self.write_new(temporary, value)
        self.check()
        with self.directory(parts[:-1]) as folder:
            os.replace(temporary[-1], parts[-1], src_dir_fd=folder, dst_dir_fd=folder)
            os.fsync(folder)
        self.check()

    def names(self, parts):
        try:
            with self.directory(parts) as folder:
                names = os.listdir(folder)
        except FileNotFoundError:
            return None
        if len(names) > 2_100:
            raise RuntimeFailure("LIFECYCLE_METADATA_LIMIT")
        return tuple(sorted(names))
