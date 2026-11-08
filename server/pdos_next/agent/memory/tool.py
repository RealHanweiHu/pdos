"""Read-tool adapter for memory.search; the person and range come from the Run."""

from pdos_next.agent.kernel.tool_arguments import tool_arguments

from .recall import MemorySearchInput, search


def memory_search(store):
    def handler(scope, arguments):
        payload = tool_arguments(MemorySearchInput, arguments)
        with store.transaction(scope, lock=True) as (session, run):
            return search(session, run, payload)

    return handler
