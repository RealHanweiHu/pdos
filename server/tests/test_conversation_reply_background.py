"""Viewing disconnects cannot close resources owned by background reply work."""

import asyncio
from contextlib import AsyncExitStack
from threading import Event
from uuid import uuid4

import pytest
from fastapi import BackgroundTasks, FastAPI, Request, Response

from app.ai import conversation_reply
from app.api.ai import get_application_gateway
from app.api.conversations import router, stream_conversation_reply


@pytest.mark.parametrize("fails", [False, True])
def test_reply_task_owns_gateway_until_completion_after_viewer_disconnect(monkeypatch, fails):
    entered, release = Event(), Event()
    lifecycle = []
    gateway = object()

    def managed_gateway(request: Request):
        assert request.scope["pdos_preproject_goal"] == "category"
        lifecycle.append("opened")
        try:
            yield gateway
        finally:
            lifecycle.append("closed")

    def answer(self, *args):
        assert self.gateway is gateway
        entered.set()
        assert release.wait(5)
        assert lifecycle == ["opened"]
        lifecycle.append("work_finished")
        if fails:
            raise RuntimeError("synthetic-private-error")
        return {"status": "answered", "answer": "原回复完成"}

    monkeypatch.setattr(
        conversation_reply, "authorize", lambda *args: (None, {"preproject_goal": "category"})
    )
    monkeypatch.setattr(conversation_reply.ConversationReplies, "answer", answer)

    async def run():
        app = FastAPI()
        app.dependency_overrides[get_application_gateway] = managed_gateway
        route = next(r for r in router.routes if r.name == "stream_conversation_reply")
        async with AsyncExitStack() as request_stack:
            request = Request(
                {
                    "type": "http",
                    "method": "POST",
                    "path": route.path,
                    "query_string": b"",
                    "headers": [],
                    "app": app,
                    "route": route,
                    "fastapi_inner_astack": request_stack,
                    "fastapi_function_astack": request_stack,
                }
            )
            response = await stream_conversation_reply(
                uuid4(), uuid4(), request, Response(), BackgroundTasks(), object(), object()
            )
            iterator = response.body_iterator
            assert "已收到" in await anext(iterator)
            assert await asyncio.to_thread(entered.wait, 5)
            tasks = tuple(app.state.conversation_reply_tasks)
            assert len(tasks) == 1
            await iterator.aclose()
        # The HTTP request has gone away; the task still owns its connection.
        assert lifecycle == ["opened"]
        try:
            release.set()
            await asyncio.wait_for(asyncio.gather(*tasks), timeout=5)
            assert lifecycle == ["opened", "work_finished", "closed"]
            assert not app.state.conversation_reply_tasks
        finally:
            release.set()

    asyncio.run(run())
