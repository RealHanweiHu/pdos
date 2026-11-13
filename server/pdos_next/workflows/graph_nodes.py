"""Activity-side shell for LangGraph nodes run by the Temporal LangGraph plugin (P100).

The plugin runs a plain function node on a thread with no event loop, where
``activity.heartbeat`` cannot be called. This shell is the async node the plugin sees:
it heartbeats on the loop, runs the existing synchronous node body on a thread with the
caller's context, tells that thread to stop when Temporal gives the attempt up, and maps
errors so that only failures known to have sent nothing are retried.

State and context that reach a node are identifiers and run data. Engines, gateways and
credentials stay in the worker-level dependencies below and never enter either.
"""

import asyncio
import logging
import traceback
from contextvars import copy_context
from threading import Event

from pdos_agent_runtime.graph import registered_graph_context
from sqlalchemy.exc import OperationalError
from temporalio import activity
from temporalio.exceptions import ApplicationError

from pdos_next.errors import DomainError

HEARTBEAT_SECONDS = 10
_dependencies = {}


def configure_graph_dependencies(**values):
    """Worker start-up only: live objects the node bodies rebuild their ports from."""
    _dependencies.update(values)


def dependency(name):
    try:
        return _dependencies[name]
    except KeyError:
        raise DomainError("SOURCE_UNAVAILABLE", "执行图依赖未在本 worker 配置。") from None


def _guarded(body, state, context, stop):
    try:
        with registered_graph_context("xiaopai"):
            return body(state, context, stop)
    except DomainError as error:
        # The run's ledgers decide what happened; Temporal must not repeat the node.
        raise ApplicationError(error.message, type=error.code, non_retryable=True) from None
    except OperationalError:
        # The business database was unreachable. Node bodies claim their ledger row
        # before any outbound call, so a repeat replays or stops there (P100 §5.2).
        raise
    except Exception as error:
        if type(error).__module__.startswith("langgraph."):
            raise  # interrupt() and graph control flow belong to the plugin
        # Frames and exception type are diagnostic; values stay private.
        logging.getLogger(__name__).error(
            "Unexpected %s in graph node %s: %s", type(error).__name__, body.__qualname__,
            "".join(traceback.format_tb(error.__traceback__)),
        )
        raise ApplicationError(
            "执行未完成，已提交结果保留，请核对运行记录。",
            type="INTERNAL_ERROR", non_retryable=True,
        ) from None


def activity_node(body):
    """Wrap ``body(state, context, stop)`` as the node function given to ``add_node``.

    ``stop`` is set once Temporal cancels or times out this attempt; a long body checks
    it at its safe points. The wrapper keeps the body's module and qualified name, which
    the plugin uses as the node's identity in its continue-as-new cache.
    """

    async def node(state, runtime):
        stop = Event()
        context = copy_context()
        loop = asyncio.get_running_loop()

        async def beat():
            while True:
                await asyncio.sleep(HEARTBEAT_SECONDS)
                activity.heartbeat()

        beating = asyncio.create_task(beat())
        work = loop.run_in_executor(
            None, lambda: context.run(_guarded, body, state, dict(runtime.context or {}), stop)
        )
        try:
            return await asyncio.shield(work)
        except asyncio.CancelledError:
            # The thread cannot be interrupted; let it reach a safe point before the
            # next attempt may start (the per-run lease covers a slow stop, D243).
            stop.set()
            await asyncio.wait([work], timeout=HEARTBEAT_SECONDS)
            raise
        finally:
            beating.cancel()

    node.__module__, node.__qualname__, node.__name__ = (
        body.__module__, body.__qualname__, body.__name__,
    )
    return node
