"""Execute one saved personal Run with a scripted model client (no provider, no egress).

Everything except the model is real: registered kernel graph, tool registry, pinned-source
reads under the requester's RLS, citation ledger, isolated extract child and server answer.
Usage: execute_run.py <run_id>
"""
import json, os, sys
from dataclasses import replace
from uuid import UUID
sys.path.insert(0, os.path.dirname(__file__))
from common import STATE, env  # noqa: E402
os.environ.update(env())
from sqlalchemy.orm import Session  # noqa: E402
from pdos_next.core.database import engine_for  # noqa: E402
from pdos_next.agent.kernel.models import AgentRun  # noqa: E402
from pdos_next.agent.kernel.bootstrap import Bootstrap, RuntimePorts  # noqa: E402
from pdos_next.agent.kernel.graph import AgentKernel  # noqa: E402
from pdos_next.agent.kernel.host import BoundHost  # noqa: E402
from pdos_next.agent.kernel.types import ModelTurn, ToolCall  # noqa: E402
from pdos_next.agent.enterprise_search.assistant_graph import AssistantExtractGraph  # noqa: E402
from pdos_next.providers.types import ProviderUsage  # noqa: E402
from tests.agent.kernel.test_gateway import configured_route  # noqa: E402

class ScriptedClient:
    def __init__(self, ids): self.ids = ids
    def close(self): pass
    def turn(self, _route, **kwargs):
        names = {row["name"] for row in kwargs["tools"]}
        values = [json.loads(row["content"]) for row in kwargs["messages"] if row["role"] == "tool"]
        usage = ProviderUsage(10, 2)
        if names == {"assistant.passage.read", "result.read"}:
            cid = json.loads(kwargs["messages"][0]["content"])["context"]["citation_id"]
            if not values or values[-1].get("next_cursor") is not None:
                cursor = values[-1]["next_cursor"] if values else 0
                return ModelTurn(calls=(ToolCall(id="passage", name="assistant.passage.read",
                    arguments={"citation_id": cid, "cursor": cursor, "page_chars": 2000}),), usage=usage)
            text = "".join(v.get("text", "") for v in values)
            line = next((l.strip() for l in text.splitlines() if l.strip()), text.strip())
            quote = line[:24]
            return ModelTurn(structured={"status": "completed", "summary": "已提取", "questions": [], "unfinished": [],
                "result": {"rows": [{"citation_id": cid, "statement": f"资料写明：{quote}", "quote": quote}]}}, usage=usage)
        if not values:
            return ModelTurn(calls=(ToolCall(id="pinned", name="assistant.materials.read",
                arguments={"artifact_ids": self.ids}),), usage=usage)
        last = values[-1]
        if "items" in last and last["items"]:
            return ModelTurn(calls=(ToolCall(id="extract", name="assistant.extract",
                arguments={"citation_ids": [item["citation_id"] for item in last["items"]][:8]}),), usage=usage)
        rows = last.get("rows", [])
        ids = list(dict.fromkeys(row["citation_id"] for row in rows))
        summary = "按你携带的资料：" + "；".join(row["statement"] for row in rows) if rows else "携带的资料当前都不可读。"
        return ModelTurn(structured={"status": "completed", "summary": summary, "questions": [], "unfinished": [],
            "result": {"assistant": {"citation_ids": ids}}}, usage=usage)

run_id = UUID(sys.argv[1])
admin, engine = engine_for(STATE["admin_url"]), engine_for(STATE["app_url"])
with Session(admin) as s:
    run = s.get(AgentRun, run_id)
    assert run is not None and run.category_id is None, "personal run required"
    ids = [ref["artifact_id"] for ref in run.read_sources]
    tenant, requester, writer, goal = run.tenant_id, run.requester_id, run.writer_id, run.goal
import asyncio  # noqa: E402
from common import OBJECTS  # noqa: E402
from pdos_next.bootstrap.security import local_runtime  # noqa: E402
from pdos_next.originals.lifecycle.worker import configure_lifecycle  # noqa: E402
from pdos_next.originals.security import configure  # noqa: E402
from pdos_next.originals.store import OriginalStore  # noqa: E402
store = OriginalStore(str(OBJECTS))
configure_lifecycle(engine, store, allow_local_profile=True)  # same wiring as the Temporal worker
configure(engine, asyncio.run(local_runtime(store)))
owner = Bootstrap(engine, ports=RuntimePorts(provider_client=ScriptedClient(ids), preload=lambda _: ()))
owner.route_for = lambda _scope: replace(configured_route(), context_window_tokens=200_000)
owner.provider_for = lambda *_args: "synthetic-assistant-no-egress"
scope = owner.store.scope(tenant_id=tenant, requester_id=requester, writer_id=writer, category_id=None, run_id=run_id)
host = BoundHost(owner.store, replace(owner.adapters(), cost_required=False))
owner._assistant_adapter.graph = AssistantExtractGraph(host, owner._assistant_adapter)
output = AgentKernel(host, owner.registry).execute(scope, goal=goal, execution_key={"scripted-e2e": str(run_id)})["output"]
print("status", output["status"], "cited", len(output["result"].get("assistant", {}).get("citation_ids", [])))
