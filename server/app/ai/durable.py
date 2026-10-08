"""Shared LangGraph + Temporal entry boundary for original PDOS capabilities."""

import json
import os
from collections.abc import Callable, Mapping
from functools import wraps
from inspect import signature
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from pdos_agent_runtime.client import DurableRuntime, RuntimeUnavailable
from pdos_agent_runtime.graph import execute_graph, in_agent_graph
from pdos_agent_runtime.store import RuntimeStore
from sqlalchemy import Engine

from app.ai.durable_codec import decode, encode
from app.ai.durable_registry import ENTRIES


def configured_runtime(
    environment: Mapping[str, str] | None = None, *, engine: Engine | None = None
) -> DurableRuntime | None:
    values = os.environ if environment is None else environment
    if os.environ.get("PDOS_AGENT_RUNTIME_MODE") == "injected-test":
        from sqlalchemy.engine import make_url

        from app.db.test_safety import configured_test_database_url, require_test_database_url

        expected = make_url(configured_test_database_url())
        if engine is None or engine.url.database != "pdos_test":
            raise ValueError("Injected test runtime requires the verified isolated test database")
        require_test_database_url(engine.url.render_as_string(hide_password=False))
        if (engine.url.host, engine.url.port) != (expected.host, expected.port):
            raise ValueError("Injected test runtime target mismatch")
        return None
    required = (
        "PDOS_AGENT_RUNTIME_DATABASE_URL",
        "PDOS_AGENT_RUNTIME_DB_MARKER",
        "PDOS_TEMPORAL_ADDRESS",
        "PDOS_TEMPORAL_NAMESPACE",
    )
    if any(not values.get(key) for key in required):
        path = Path(
            values.get(
                "PDOS_AGENT_RUNTIME_CONFIG_PATH",
                str(
                    Path(__file__).resolve().parents[3]
                    / ".local"
                    / "agent-runtime"
                    / "environment.json"
                ),
            )
        )
        if path.exists():
            if path.stat().st_mode & 0o077:
                raise RuntimeUnavailable("Agent 私有运行配置权限不符合要求。")
            configuration = json.loads(path.read_text())
            values = {
                **configuration["environment"],
                **{k: v for k, v in values.items() if k not in required or v},
            }
    if any(not values.get(key) for key in required):
        raise RuntimeUnavailable("Agent 尚未配置 LangGraph + Temporal 持久执行服务。")
    store = RuntimeStore(values[required[0]], realm="pdos", marker=values[required[1]])
    return DurableRuntime(
        store,
        address=values[required[2]],
        namespace=values[required[3]],
        task_queue="pdos-agent-v1",
    )


def resource(owner: Any) -> tuple[Any, Any]:
    gateway = getattr(owner, "gateway", getattr(owner, "_gateway", None))
    if gateway is None and hasattr(owner, "_model_invoker"):
        gateway = getattr(owner._model_invoker, "_gateway", None)
    engine = getattr(owner, "engine", getattr(owner, "_engine", None))
    return engine, gateway


def tenant(values: dict[str, Any], engine: Any) -> Any:
    from app.auth.repository import AuthContext

    for value in values.values():
        if isinstance(value, AuthContext):
            return value.tenant.id
    if values.get("tenant_id"):
        return values["tenant_id"]
    for key in ("row", "run", "claim"):
        row = values.get(key)
        if row is not None:
            return (row.values if key == "claim" else row)["tenant_id"]
    if values.get("run_id"):
        from sqlalchemy import select

        from app.db.schema import tables

        with engine.connect() as connection:
            return connection.execute(
                select(tables.agent_runs.c.tenant_id).where(
                    tables.agent_runs.c.id == values["run_id"]
                )
            ).scalar_one()
    raise ValueError("Agent entry must bind an explicit server tenant")


def agent_entry[**P, R](function: Callable[P, R]) -> Callable[P, R]:
    key = function.__module__ + ":" + function.__qualname__
    if key not in ENTRIES:
        raise ValueError("Agent entrypoint is missing from the fixed runtime inventory")
    params = signature(function)

    @wraps(function)
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
        if in_agent_graph():
            return function(*args, **kwargs)
        values = dict(params.bind(*args, **kwargs).arguments)
        owner = values.pop("self", None)
        if owner is None:
            engine, gateway = values.get("engine"), values.get("gateway")
        else:
            engine, gateway = resource(owner)
        runtime = getattr(gateway, "durable_runtime", None)
        if runtime is None:
            # Explicitly injected unit-test providers still execute the actual graph.
            # Configured production gateways always attach the durable runtime.
            result = execute_graph(
                lambda _: {"value": encode(function(*args, **kwargs))},
                {},
                thread_id="injected-test:" + str(uuid4()),
            )
            return cast(R, decode(result["value"], engine=engine))
        scope = tenant(values, engine)
        emit = next((v for v in values.values() if callable(v)), None)
        if owner is None:
            values.pop("engine", None)
            values.pop("gateway", None)
        payload = {"arguments": encode(values)}
        keeper = getattr(gateway, "application_lease_keeper", None)
        if keeper is not None:
            for row_name in ("row", "run"):
                row = values.get(row_name)
                if row is not None and keeper.token(scope, row["id"]) is not None:
                    payload["lease"] = {
                        "tenant_id": str(scope),
                        "run_id": str(row["id"]),
                        "owner_id": str(keeper.owner_id),
                        "token": str(keeper.token(scope, row["id"])),
                    }
        result = runtime.submit(
            scope, key, payload, emit=emit, verify=lambda: verify_request(values, engine)
        )
        verify_request(values, engine)
        if key == "app.ai.conversation_reply:ConversationReplies.answer":
            from app.ai.conversation_reply import read_reply

            return cast(
                R,
                read_reply(
                    cast(Engine, engine),
                    values["context"],
                    values["conversation_id"],
                    values["message_id"],
                ),
            )
        return cast(R, decode(result["value"], engine=engine))

    wrapped.__dict__["agent_runtime_entry"] = key
    return wrapped


def verify_request(values: dict[str, Any], engine: Any) -> None:
    from app.auth.repository import AuthContext, AuthRepository

    context = None

    for value in values.values():
        if isinstance(value, AuthContext):
            context = decode(encode(value), engine=engine)
    if context is None and values.get("tenant_id") and values.get("actor_user_id"):
        context = AuthRepository(engine).find_user_context(values["actor_user_id"])
        if (
            context is None
            or context.tenant.id != values["tenant_id"]
            or not context.user.is_active
            or context.tenant.status != "active"
            or (
                values.get("auth_version") is not None
                and context.user.auth_version != values["auth_version"]
            )
        ):
            raise PermissionError("Original requester authority is no longer current")
    if context is None:
        return  # Event/queued execution revalidates the server-owned run/lease in its domain.
    if values.get("project_id"):
        from app.auth.project_access import ProjectAccessService, SqlProjectAccessRepository
        from app.auth.roles import Action

        ProjectAccessService(SqlProjectAccessRepository(engine)).authorize(
            context=context,
            project_id=values["project_id"],
            action=Action.PROJECT_VIEW,
        )
    if values.get("space_id"):
        from app.domain.product_workspace import _space

        with engine.connect() as connection:
            _space(connection, context, values["space_id"])
    if values.get("conversation_id"):
        from app.ai.conversation_reply import authorize

        authorize(engine, context, values["conversation_id"], values["message_id"])
