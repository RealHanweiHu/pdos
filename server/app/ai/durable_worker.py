"""Host-owned adapters. Temporal cannot supply imports, secrets or authority."""

import asyncio
import importlib
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from inspect import signature
from typing import Any, cast

from pdos_agent_runtime.activity import AgentActivities
from pdos_agent_runtime.followup import ProjectFollowup
from pdos_agent_runtime.workflow import AgentWork
from temporalio.client import Client
from temporalio.worker import Worker

from app.ai.durable import configured_runtime, verify_request
from app.ai.durable_codec import decode, encode
from app.ai.durable_followup import FollowupActivities
from app.ai.durable_registry import ENTRIES
from app.db.engine import get_engine


def handlers(engine: Any) -> dict[str, Any]:
    def adapter(key: str) -> Any:
        def call(payload: Any, emit: Any) -> dict[str, Any]:
            from app.ai.application_gateway import configured_application_gateway

            module, symbol = key.split(":")
            with ExitStack() as stack:
                if symbol.startswith("AgentExecutor."):
                    from app.ai.runtime_factory import configured_agent_runtime

                    owner = stack.enter_context(configured_agent_runtime()).executor
                    selected_engine, gateway = (
                        owner._engine,
                        cast(Any, owner._model_invoker)._gateway,
                    )
                else:
                    selected_engine = engine
                    arguments = decode(payload["arguments"], engine=engine, emit=emit)
                    preproject = False
                    if key == "app.ai.conversation_reply:ConversationReplies.answer":
                        from app.ai.conversation_reply import authorize

                        _, message = authorize(
                            engine,
                            arguments["context"],
                            arguments["conversation_id"],
                            arguments["message_id"],
                        )
                        preproject = bool(message["preproject_goal"])
                    gateway = stack.enter_context(
                        configured_application_gateway(
                            engine,
                            preproject=preproject,
                            request_timeout_seconds=90.0
                            if symbol == "TestPlanSuggestionService.create"
                            else 30.0,
                            max_structured_attempts=1
                            if symbol == "TestPlanSuggestionService.create"
                            else 2,
                        )
                    )
                    owner = None
                args = decode(payload["arguments"], engine=selected_engine, emit=emit)
                verify_request(args, selected_engine)
                if payload.get("lease"):
                    gateway.application_lease_keeper.attach_existing(payload["lease"])
                target = importlib.import_module(module)
                if "." in symbol:
                    class_name, method = symbol.split(".")
                    cls = getattr(target, class_name)
                    if owner is None:
                        constructor = signature(cls).parameters
                        dependencies = {"engine": engine, "gateway": gateway}
                        if "object_store" in constructor:
                            from app.storage.documents import get_document_object_store

                            dependencies["object_store"] = get_document_object_store()
                        if "embedding_gateway" in constructor:
                            from app.ai.embeddings import (
                                EmbeddingError,
                                configured_embedding_gateway,
                            )

                            try:
                                dependencies["embedding_gateway"] = stack.enter_context(
                                    configured_embedding_gateway()
                                )
                            except EmbeddingError as error:
                                if error.code != "EMBEDDING_NOT_CONFIGURED":
                                    raise
                                dependencies["embedding_gateway"] = None
                        owner = cls(**{k: v for k, v in dependencies.items() if k in constructor})
                    result = getattr(owner, method)(**args)
                else:
                    result = getattr(target, symbol)(engine=engine, gateway=gateway, **args)
                verify_request(args, selected_engine)
                return {"value": encode(result)}

        return call

    return {key: adapter(key) for key in ENTRIES}


async def main() -> None:
    runtime = configured_runtime()
    if runtime is None:
        raise RuntimeError("A Temporal worker requires a durable runtime")
    engine = get_engine()
    client = await Client.connect(runtime.address, namespace=runtime.namespace)
    activities = AgentActivities(runtime.store, handlers(engine), checkpoint_url=runtime.store.url)
    followups = FollowupActivities(engine)
    try:
        with ThreadPoolExecutor(max_workers=8) as executor:
            worker = Worker(
                client,
                task_queue=runtime.task_queue,
                workflows=[AgentWork, ProjectFollowup],
                activities=[activities.execute, followups.execute],
                activity_executor=executor,
            )
            await worker.run()
    finally:
        engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
