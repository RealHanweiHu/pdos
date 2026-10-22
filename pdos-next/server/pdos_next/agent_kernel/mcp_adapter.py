"""MCP graph bridge: actual loaded skills, bounded discovery and durable isolated reads."""

from uuid import UUID, uuid5

from pydantic import ValidationError
from sqlalchemy import select

from pdos_next.clock import now
from pdos_next.errors import DomainError
from pdos_next.service import digest

from . import policy
from .bindings import ModelBinding
from .execution import validate_skill_load
from .mcp import McpPorts, McpService
from .mcp_binding import connector_binding, redact_credential, validate_arguments, validate_result
from .mcp_schemas import McpListInput, McpReadInput, parse_input
from .models import AgentToolCall, McpConnector, McpToolGrant
from .proposal_context import check
from .read_execution import ReadBinding


class McpReadAdapter:
    def __init__(
        self, store, catalog, *, resolve_secret=None, transport=None, artifacts=None, graph=None
    ):
        self.store, self.catalog = store, catalog
        self.resolve_secret, self.transport = resolve_secret, transport
        self.artifacts, self.graph = artifacts, graph

    def loaded(self, scope, intent_key):
        # BoundHost has already claimed this exact read after verifying the model row.
        # Read the immutable proof, rather than looking for a later skill_loaded event.
        with self.store.transaction(scope) as (session, _):
            call = session.scalar(
                select(AgentToolCall).where(
                    AgentToolCall.run_id == scope.run_id,
                    AgentToolCall.call_key == intent_key,
                )
            )
            try:
                binding = ReadBinding.model_validate(call.execution_binding)
                if binding.call_key != intent_key or binding.isolation != "main":
                    raise ValueError
                model = session.get(AgentToolCall, binding.model_call_id)
                actual = ModelBinding.model_validate(model.execution_binding)
                if (
                    model.state != "completed"
                    or model.run_id != scope.run_id
                    or model.tenant_id != scope.tenant_id
                    or actual.isolation != "main"
                ):
                    raise ValueError
            except (AttributeError, ValidationError, TypeError, ValueError):
                raise DomainError("FORBIDDEN_SCOPE", "MCP 读取缺少实际模型与技能账本。") from None
            keys = set()
            for loaded in actual.loaded_skills:
                validate_skill_load(session, scope, loaded)
                skill = self.catalog.load(
                    loaded.key,
                    scope,
                    lambda bound, item: policy.skill_enabled(session, bound, item),
                )
                if skill.version != loaded.version or skill.digest != loaded.digest:
                    raise DomainError("VERSION_CONFLICT", "MCP 授权所用技能内容已变化。")
                keys.add(skill.key)
            return keys

    def discover(self, scope, arguments, *, intent_key):
        data, keys = parse_input(McpListInput, arguments), self.loaded(scope, intent_key)
        with self.store.transaction(scope) as (session, _):
            query = (
                select(McpToolGrant, McpConnector)
                .join(
                    McpConnector,
                    (
                        (McpToolGrant.connector_id == McpConnector.id)
                        & (McpToolGrant.tenant_id == McpConnector.tenant_id)
                    ),
                )
                .where(
                    McpConnector.tenant_id == scope.tenant_id,
                    McpConnector.active.is_(True),
                    McpToolGrant.active.is_(True),
                    McpToolGrant.expires_at > now(),
                    McpToolGrant.skill_key.in_(keys),
                )
                .order_by(McpToolGrant.id)
                .limit(data.page_size + 1)
            )
            if data.cursor is not None:
                query = query.where(McpToolGrant.id > data.cursor)
            if data.connector_id is not None:
                query = query.where(McpConnector.id == data.connector_id)
            rows = session.execute(query).all()
            items = []
            for grant, connector in rows[: data.page_size]:
                spec = connector.tools.get(grant.tool)
                if (
                    not isinstance(spec, dict)
                    or spec.get("kind") != "read"
                    or grant.connector_binding_digest != connector_binding(connector, grant.tool)
                ):
                    continue
                items.append(
                    {
                        "connector_id": str(connector.id),
                        "provider": connector.key,
                        "tool": grant.tool,
                        "description": spec.get("description", ""),
                        "input_schema": spec["input_schema"],
                        "output_schema": spec.get("output_schema"),
                        "grant_id": str(grant.id),
                        "grant_revision": grant.revision,
                        "skill_key": grant.skill_key,
                    }
                )
        return {
            "tools": items,
            "taint": "admitted_metadata",
            "next_cursor": str(rows[data.page_size - 1][0].id)
            if len(rows) > data.page_size
            else None,
        }

    def _ready(self, *, storage_only=False):
        if storage_only:
            if self.artifacts is None:
                raise DomainError("SOURCE_UNAVAILABLE", "原 MCP 私有作业存储不可用。")
            return
        if any(
            value is None
            for value in (
                self.resolve_secret,
                self.transport,
                self.artifacts,
                self.graph,
            )
        ):
            raise DomainError("SOURCE_UNAVAILABLE", "MCP 传输、凭据或隔离作业存储尚未配置。")

    def _target(self, scope, data, keys):
        check(self.store, scope)
        with self.store.transaction(scope) as (session, _):
            connector, spec, grants = policy.mcp_admission(
                session,
                scope.child("mcp"),
                data.connector_id,
                data.tool,
                loaded_skills=keys,
            )
            if spec.get("kind") != "read":
                raise DomainError(
                    "NAMED_DECISION_REQUIRED", "此入口只读取；外发须实际具名授权路径。"
                )
            validate_arguments(spec, data.arguments)
            policy.egress(session, scope, connector.key)
            return connector_binding(connector, data.tool), spec, grants

    def resume(self, scope, arguments, *, intent_key):
        self._ready()
        data, keys = parse_input(McpReadInput, arguments), self.loaded(scope, intent_key)
        binding, spec, _ = self._target(scope, data, keys)
        with self.store.transaction(scope) as (session, _):
            parent_id = session.scalar(
                select(AgentToolCall.id).where(
                    AgentToolCall.run_id == scope.run_id,
                    AgentToolCall.call_key == intent_key,
                )
            )
        job = uuid5(scope.run_id, "mcp.read:" + intent_key)
        raw_id, started_id = uuid5(job, "raw"), uuid5(job, "network-started")
        request_digest = digest([str(data.connector_id), data.tool, data.arguments, binding])

        def transport(endpoint, credential, tool, parameters):
            if self.artifacts._path(scope, raw_id).exists():
                saved = self.artifacts.get(scope, raw_id)
                if saved.get("kind") != "mcp_raw" or saved.get("request_digest") != request_digest:
                    raise DomainError("SOURCE_STALE", "原 MCP 结果不属于当前目标和参数。")
                return saved["raw"]
            if self.artifacts._path(scope, started_id).exists():
                raise DomainError(
                    "EXTERNAL_OUTCOME_UNKNOWN", "原 MCP 读取响应未落盘，须核对后发起新请求。"
                )
            # Fence before dispatch. A crash cannot silently repeat a network request.
            self.artifacts.put(
                scope,
                started_id,
                {
                    "kind": "mcp_network_started",
                    "request_digest": request_digest,
                },
            )
            raw = redact_credential(
                self.transport(endpoint, credential, tool, parameters), credential
            )
            validate_result(spec, raw)
            self.artifacts.put(
                scope,
                raw_id,
                {
                    "kind": "mcp_raw",
                    "request_digest": request_digest,
                    "raw": raw,
                },
            )
            return raw

        def extract(bound, raw, actual):
            current, _, _ = self._target(scope, data, keys)
            if current != binding:
                raise DomainError("SOURCE_STALE", "MCP 目标或工具合同已变化。")
            return self.graph(bound, raw, {**actual, "name": data.tool}, job_id=job)

        service = McpService(
            self.store,
            McpPorts(
                self.resolve_secret,
                transport,
                extract,
            ),
        )
        result = service.call(
            scope.child("mcp"),
            connector_id=data.connector_id,
            tool=data.tool,
            arguments=data.arguments,
            loaded_skills=keys,
            intent_key="mcp-dispatch:" + str(job),
            resume_read=True,
            parent_read_call_id=parent_id,
        )
        current, _, _ = self._target(scope, data, keys)
        if current != binding:
            raise DomainError("SOURCE_STALE", "MCP 目标或工具合同已变化。")
        return {**result, "job_id": str(job), "taint": "external_untrusted"}

    def restore(self, scope, arguments, previous):
        self._ready(storage_only=True)
        data = parse_input(McpReadInput, arguments)
        try:
            job = UUID(previous["job_id"])
            with self.store.transaction(scope) as (session, _):
                call = session.get(AgentToolCall, UUID(previous["call_id"]))
                if (
                    call is None
                    or call.run_id != scope.run_id
                    or call.tenant_id != scope.tenant_id
                    or call.call_key != "mcp-dispatch:" + str(job)
                    or call.state != "completed"
                    or call.result
                    != {k: v for k, v in previous.items() if k not in {"job_id", "taint"}}
                ):
                    raise ValueError
                dispatch = call.execution_binding
                parent = session.get(AgentToolCall, UUID(dispatch["parent_read_call_id"]))
                keys = self.loaded(scope, parent.call_key)
            binding, _, _ = self._target(scope, data, keys)
            saved = self.artifacts.get(scope, uuid5(job, "raw"))
            if (
                saved.get("kind") != "mcp_raw"
                or saved.get("request_digest")
                != digest(
                    [
                        str(data.connector_id),
                        data.tool,
                        data.arguments,
                        binding,
                    ]
                )
                or digest(saved["raw"]) != previous["raw_digest"]
            ):
                raise ValueError
        except (AttributeError, KeyError, TypeError, ValueError):
            raise DomainError("SOURCE_STALE", "原 MCP 结果或调用证明不可核对。") from None
        return previous

    def handlers(self):
        # BoundHost selects resumable compositions; these slots declare availability.
        def unbound(*_):
            raise DomainError("FORBIDDEN_SCOPE", "MCP 入口须绑定实际主图调用。")

        return {"mcp.tools.list": unbound, "mcp.read": unbound}

    def resumes(self):
        return {"mcp.tools.list": self.discover, "mcp.read": self.resume}
