"""Real Human knowledge directory plus independent cursor coverage controls.

The six code sources are native category-visible Artifacts, not verified-answer
or T0 qualifications. The three undisclosed entries contain directory metadata only.
No padding is added to obtain a desired fragment or business-item count.
"""

import json
import re
from copy import deepcopy
from uuid import UUID, uuid4

from sqlalchemy import select

from pdos_next.agent_kernel.types import ModelTurn, ToolCall
from pdos_next.database import tenant_session
from pdos_next.domain.preproject import category_reads
from pdos_next.domain.preproject.category_models import KnowledgeCurrent, KnowledgeEntry
from pdos_next.domain.preproject.schemas import Reference
from pdos_next.models import Artifact
from pdos_next.providers.types import ProviderUsage
from tests.preproject.test_g0 import post, request

DIRECTORY_REGION = "eval-v0-ctx09-directory"
MECHANICS_REGION = "eval-v0-ctx09-mechanics"


def code_reference(source):
    return Reference.model_validate({
        key: source[key] for key in ("type", "id", "version", "line", "quote")
    }).model_dump(mode="json")


def native_directory(setup, question):
    disclosed = []
    for index in (1, 3):
        preview = json.loads(question["turns"][index]["content"])["preview"]
        disclosed.extend((int(number), code, state) for number, code, state in
                         re.findall(r"条目([1-6]) (Q-\d+) (已登记|待确认)", preview))
    assert [row[0] for row in disclosed] == list(range(1, 7))
    assert [row[1] for row in disclosed] == [f"Q-{number}" for number in range(301, 307)]

    def native_command(operation, payload):
        response = post(setup, request(setup, operation, payload))
        assert response.status_code == 200, response.text
        receipt = response.json()
        assert receipt["operation"] == operation
        assert receipt["writer_id"] == receipt["requester_id"] == str(setup.human)
        assert receipt["agent_run_id"] is None
        return receipt

    def add(payload):
        return native_command("category.knowledge.add", payload)

    registered = []
    for ordinal, code, state in disclosed:
        quote = f"{code}；合成登记状态：{state}。"
        receipt = native_command("evidence.artifact.register", {
            "title": f"CTX09 合成代码来源 {code}", "content": quote,
            "source_label": "CTX09 disclosed synthetic code source",
            "visibility": "category"})
        registered.append((ordinal, code, state, quote, receipt))
    faq = []
    with tenant_session(setup.engine, setup.tenant, actor_id=setup.human,
                        requester_id=setup.human, category_id=setup.category,
                        read_snapshot=True) as session:
        for ordinal, code, state, quote, receipt in registered:
            artifact = session.get(Artifact, UUID(receipt["subject_id"]))
            assert receipt["subject_type"] == "artifact" and artifact is not None
            assert artifact.tenant_id == setup.tenant and artifact.category_id == setup.category
            assert artifact.visibility == "category" and artifact.status == "active"
            assert receipt["subject_revision"] == artifact.revision
            assert artifact.content.splitlines()[0] == quote
            faq.append({"ordinal": ordinal, "code": code, "record_status": state,
                        "type": "artifact", "id": str(artifact.id),
                        "version": artifact.revision, "line": 1, "quote": quote,
                        "receipt_id": receipt["id"]})
    # Distinct native intents are required: identical placeholders are replayed
    # as one lineage even when command/idempotency keys differ.
    initial = [add({"kind": "boundary", "regions": [DIRECTORY_REGION], "content": {
        "definition": f"合成验收目录占位{slot}；正文未提供。"}}) for slot in range(1, 10)]
    assert len({receipt["result"]["lineage_id"] for receipt in initial}) == 9
    assert len({receipt["result"]["entry_id"] for receipt in initial}) == 9
    # Use actual server ordering, then legitimate native supersedes. Neither
    # lineage IDs nor historical rows are invented or written directly.
    ordered = sorted(initial, key=lambda receipt: UUID(receipt["result"]["lineage_id"]))
    entries = []
    for index, previous in enumerate(ordered):
        ordinal = index + 1
        source = faq[index] if index < 6 else None
        content = {
            "definition": (f"目录条目{ordinal} {source['code']} {source['record_status']}。"
                           if source else f"目录条目{ordinal}；本题未提供正文。"),
            "material": {"directory_ordinal": ordinal,
                         "body_state": "available" if source else "not_provided"},
        }
        refs = [code_reference(source)] if source else []
        receipt = add({"kind": "boundary", "regions": [DIRECTORY_REGION], "content": content,
                       "source_refs": refs,
                       "supersedes": {"lineage_id": previous["result"]["lineage_id"],
                                      "expected_version": previous["result"]["version"]}})
        entries.append({"ordinal": ordinal, "id": receipt["result"]["entry_id"],
                        "lineage_id": receipt["result"]["lineage_id"],
                        "version": receipt["result"]["version"],
                        "receipt_id": receipt["id"], "faq": source})
    with tenant_session(setup.engine, setup.tenant, actor_id=setup.human,
                        requester_id=setup.human, category_id=setup.category) as session:
        rows = list(session.scalars(select(KnowledgeEntry).join(KnowledgeCurrent, (
            KnowledgeCurrent.tenant_id == KnowledgeEntry.tenant_id)
            & (KnowledgeCurrent.category_id == KnowledgeEntry.category_id)
            & (KnowledgeCurrent.current_entry_id == KnowledgeEntry.id)).where(
                KnowledgeEntry.tenant_id == setup.tenant,
                KnowledgeEntry.category_id == setup.category,
                KnowledgeEntry.regions.contains([DIRECTORY_REGION]),
        ).order_by(KnowledgeEntry.lineage_id)))
        snapshot = category_reads.knowledge(session, setup.ctx, kind="boundary",
                                            region=DIRECTORY_REGION, page_size=9)
        assert len(rows) == len(snapshot["items"]) == 9 and snapshot["next_cursor"] is None
        assert [str(row.id) for row in rows] == [entry["id"] for entry in entries]
        assert [row["id"] for row in snapshot["items"]] == [entry["id"] for entry in entries]
        for row, entry in zip(rows, entries, strict=True):
            assert row.version == entry["version"] == 2
            assert row.source_refs == ([code_reference(entry["faq"])] if entry["faq"] else [])
        for source in faq:
            artifact = session.get(Artifact, UUID(source["id"]))
            assert artifact is not None and artifact.visibility == "category"
            assert artifact.tenant_id == setup.tenant and artifact.category_id == setup.category
            assert artifact.status == "active" and artifact.revision == source["version"]
            assert artifact.content.splitlines()[source["line"] - 1] == source["quote"]
    return {"entries": entries, "faq_sources": faq, "total_directory_objects": 9,
            "code_source_binding": "native_category_artifact_exact_line",
            "undisclosed_body_values_registered": False}


def complete_prefix_items(prefix):
    """Decode only complete top-level items actually present in a JSON prefix."""
    decoder, position = json.JSONDecoder(), 1

    def space(index):
        while index < len(prefix) and prefix[index].isspace():
            index += 1
        return index

    assert prefix.startswith("{")
    while True:
        position = space(position)
        key, position = decoder.raw_decode(prefix, position)
        position = space(position)
        assert prefix[position] == ":"
        position = space(position + 1)
        if key == "items":
            assert prefix[position] == "["
            position += 1
            break
        _, position = decoder.raw_decode(prefix, position)
        position = space(position)
        assert prefix[position] == ","
        position += 1
    items = []
    while True:
        position = space(position)
        if position == len(prefix) or prefix[position] == "]":
            return items
        try:
            item, position = decoder.raw_decode(prefix, position)
        except json.JSONDecodeError:
            return items
        assert isinstance(item, dict)
        items.append(item)
        position = space(position)
        if position == len(prefix) or prefix[position] == "]":
            return items
        assert prefix[position] == ","
        position += 1


class DirectoryControl:
    def __init__(self, mode):
        assert mode in {"natural_fragments", "native_cursor"}
        self.mode, self.pages, self.failure = mode, [], None
        self.third_cursor = None

    @staticmethod
    def call(name, arguments):
        return ModelTurn(calls=(ToolCall(id="directory-" + str(uuid4()), name=name,
                                       arguments=arguments),), usage=ProviderUsage(0, 0))

    @staticmethod
    def stop():
        return ModelTurn(structured={"status": "partial",
            "summary": "离线目录控制结束；未评价模型答案或补写未读正文。",
            "result": {}, "questions": [], "unfinished": ["目录的未读正文保持未知。"]},
            usage=ProviderUsage(0, 0))

    def turn(self, messages):
        values = [json.loads(row["content"]) for row in messages if row["role"] == "tool"]
        if not values:
            return self.call("category.knowledge.list", {"kind": "boundary",
                "region": DIRECTORY_REGION, "page_size": 3 if self.mode == "native_cursor" else 9})
        last = values[-1]
        if "error" in last:
            self.failure = deepcopy(last)
            return self.stop()
        self.pages.append(deepcopy(last))
        if self.mode == "native_cursor":
            assert "format" not in last and len(last["items"]) == 3
            assert len(self.pages) in {1, 2} and last["next_cursor"]
            if len(self.pages) == 2:
                self.third_cursor = last["next_cursor"]
            return self.call("category.knowledge.list", {"kind": "boundary",
                "region": DIRECTORY_REGION, "page_size": 3, "cursor": last["next_cursor"]})
        if last.get("format") == "json_fragment":
            assert last["total_items"] == 9 and last["page"] in {1, 2}
            if last["read_more"]:
                return self.call("result.read", last["read_more"]["arguments"])
        else:
            assert len(last["items"]) == 9
        return self.stop()

    def object_coverage(self):
        if not self.pages:
            return []
        if self.pages[0].get("format") != "json_fragment":
            return [self.pages[0]["items"]]
        prefix, result = "", []
        for page in self.pages:
            prefix += page["preview"]
            result.append(complete_prefix_items(prefix))
        return result
