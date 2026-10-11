"""Private work artifacts and the research host bridge; no business snapshot registration."""

import asyncio
import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from uuid import UUID

from pdos_next.errors import DomainError
from pdos_next.research.types import Snapshot
from pdos_next.service import digest


class ResearchArtifacts:
    def __init__(self, root, *, current):
        self.root, self.current = Path(root), current
        self.root.mkdir(parents=True, mode=0o700, exist_ok=True)

    def _path(self, scope, identity):
        self.current(scope)
        # Every path component is a server UUID; tool strings never become filesystem paths.
        directory = self.root / str(UUID(str(scope.tenant_id))) / str(UUID(str(scope.run_id)))
        directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        if directory.is_symlink():
            raise DomainError("FORBIDDEN_SCOPE", "运行作业目录不允许符号链接。")
        return directory / (str(UUID(str(identity))) + ".json")

    def save_snapshot(self, scope, snapshot):
        value = asdict(snapshot)
        self.put(scope, snapshot.id, {"kind": "public_web_snapshot", "value": value})
        return str(snapshot.id)

    def put(self, scope, identity, value):
        path = self._path(scope, identity)
        encoded = json.loads(json.dumps(value, default=str))
        body = json.dumps({"payload": encoded, "digest": digest(encoded)}, ensure_ascii=False)
        if path.exists():
            if self.get(scope, identity) != encoded:
                raise DomainError("DUPLICATE_INTENT_CONFLICT", "作业引用已有不同内容。")
            return str(identity)
        fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".pending-")
        try:
            with os.fdopen(fd, "w") as stream:
                stream.write(body)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o600)
            try:
                os.link(temporary, path)
            except FileExistsError:
                if self.get(scope, identity) != encoded:
                    raise DomainError(
                        "DUPLICATE_INTENT_CONFLICT", "作业引用已有不同内容。"
                    ) from None
        finally:
            os.unlink(temporary)
        return str(identity)

    def get(self, scope, identity):
        path = self._path(scope, identity)
        if path.is_symlink() or not path.is_file():
            raise DomainError("SOURCE_UNAVAILABLE", "原运行作业引用不可用。")
        value = json.loads(path.read_text())
        if value["digest"] != digest(value["payload"]):
            raise DomainError("SOURCE_UNAVAILABLE", "作业内容哈希不匹配。")
        return value["payload"]

    def snapshot(self, scope, identity):
        from datetime import datetime

        raw = dict(self.get(scope, identity)["value"])
        raw["id"] = UUID(raw["id"])
        raw["retrieved_at"] = datetime.fromisoformat(raw["retrieved_at"])
        snapshot = Snapshot(**raw)
        import hashlib

        if snapshot.content_hash != hashlib.sha256(snapshot.markdown.encode()).hexdigest():
            raise DomainError("SOURCE_UNAVAILABLE", "快照正文与引用哈希不同。")
        return snapshot


class ResearchReadAdapter:
    def __init__(self, tool_host, artifacts: ResearchArtifacts, *, user_messages):
        self.tool_host, self.artifacts, self.user_messages = tool_host, artifacts, user_messages

    def __call__(self, scope, arguments, *, name):
        # URLs are extracted from actual persisted human messages at the host.
        for message in self.user_messages(scope):
            self.tool_host.service.register_user_message(scope, message)
        result = asyncio.run(self.tool_host.call(scope, name, arguments))
        if name == "research.fanout":
            self.artifacts.put(
                scope, UUID(result["job_id"]), {"kind": "research_ledger", "value": result}
            )
        return result

    def handlers(self):
        from functools import partial

        return {
            name: partial(self, name=name)
            for name in ("research.search", "research.fanout", "research.read")
        }
