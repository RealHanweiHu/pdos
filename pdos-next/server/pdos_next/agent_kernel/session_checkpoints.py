"""One persisted conversation thread, with Run-scoped checkpoint namespaces.

LangGraph owns its internal subgraph namespaces. The adapter adds a storage-only
Run prefix and removes it from returned configs, preserving the public saver
protocol and the existing interrupt/pending-write behavior.
"""

from langgraph.checkpoint.base import BaseCheckpointSaver, CheckpointTuple

from pdos_next.errors import DomainError

LAYOUT_KEY = "checkpoint_layout"
SESSION_LAYOUT = "session-run-ns/v1"


def main_checkpoint_config(scope, layout=None):
    if layout is None:
        return {"configurable": {
            "thread_id": f"xiaopai:{scope.tenant_id}:{scope.session_id}:{scope.run_id}",
            "checkpoint_ns": "",
        }}
    if layout != SESSION_LAYOUT:
        raise DomainError("VERSION_CONFLICT", "原运行的检查点布局无法识别，不能改用其他线程。")
    return {"configurable": {
        "thread_id": f"xiaopai:{scope.tenant_id}:{scope.session_id}",
        "checkpoint_ns": f"run:{scope.run_id}",
    }}


class SessionRunSaver(BaseCheckpointSaver):
    def __init__(self, saver, scope):
        super().__init__(serde=saver.serde)
        self.saver, self.scope = saver, scope
        address = main_checkpoint_config(scope, SESSION_LAYOUT)["configurable"]
        self.thread, self.prefix = address["thread_id"], address["checkpoint_ns"]

    @property
    def config_specs(self):
        return self.saver.config_specs

    def with_allowlist(self, extra_allowlist):
        return SessionRunSaver(self.saver.with_allowlist(extra_allowlist), self.scope)

    def get_next_version(self, current, channel):
        return self.saver.get_next_version(current, channel)

    def _storage(self, config):
        if config is None:
            config = {"configurable": {"thread_id": self.thread}}
        values = config.get("configurable", {})
        if values.get("thread_id") != self.thread:
            raise DomainError("FORBIDDEN_SCOPE", "检查点不属于当前服务器会话。", 403)
        namespace = values.get("checkpoint_ns", "")
        if not isinstance(namespace, str) or namespace.startswith("run:"):
            raise DomainError("FORBIDDEN_SCOPE", "检查点须使用当前运行的内部命名空间。", 403)
        return {**config, "configurable": {**values, "checkpoint_ns": self.prefix + (
            "|" + namespace if namespace else ""
        )}}

    def _public(self, config):
        if config is None:
            return None
        values = config["configurable"]
        namespace = values.get("checkpoint_ns", "")
        if values.get("thread_id") != self.thread or not (
            namespace == self.prefix or namespace.startswith(self.prefix + "|")
        ):
            raise DomainError("FORBIDDEN_SCOPE", "检查点返回了其他运行的地址。", 403)
        namespace = namespace[len(self.prefix):].removeprefix("|")
        return {**config, "configurable": {**values, "checkpoint_ns": namespace}}

    def _tuple(self, value):
        if value is None:
            return None
        if value.metadata.get("pdos_run_id") != str(self.scope.run_id):
            raise DomainError("FORBIDDEN_SCOPE", "检查点未绑定当前实际运行。", 403)
        return CheckpointTuple(
            self._public(value.config), value.checkpoint, value.metadata,
            self._public(value.parent_config), value.pending_writes,
        )

    def get_tuple(self, config):
        return self._tuple(self.saver.get_tuple(self._storage(config)))

    def list(self, config, *, filter=None, before=None, limit=None):
        for value in self.saver.list(
            self._storage(config), filter=filter,
            before=self._storage(before) if before else None, limit=limit,
        ):
            yield self._tuple(value)

    def put(self, config, checkpoint, metadata, new_versions):
        saved = self.saver.put(self._storage(config), checkpoint, {
            **metadata, "pdos_run_id": str(self.scope.run_id),
            "pdos_session_id": str(self.scope.session_id), "pdos_checkpoint_layout": SESSION_LAYOUT,
        }, new_versions)
        return self._public(saved)

    def put_writes(self, config, writes, task_id, task_path=""):
        return self.saver.put_writes(self._storage(config), writes, task_id, task_path)
