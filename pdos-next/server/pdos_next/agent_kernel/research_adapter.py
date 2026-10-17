"""Private work artifacts and the research host bridge; no business snapshot registration."""

import asyncio
import json
import os
import re
import tempfile
from copy import deepcopy
from dataclasses import asdict, fields
from pathlib import Path
from uuid import UUID, uuid5

from pdos_next.errors import DomainError
from pdos_next.research.service import ResearchChild
from pdos_next.research.tools import FanoutInput, SearchInput
from pdos_next.research.types import ResearchTask, Snapshot, SnapshotReference
from pdos_next.research.web import ResearchError, canonical_url
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
        try:
            value = json.loads(path.read_text())
            if set(value) != {"payload", "digest"} or value["digest"] != digest(value["payload"]):
                raise ValueError("Artifact checksum differs")
            return value["payload"]
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise DomainError("SOURCE_UNAVAILABLE", "原运行作业内容无法核对。") from exc

    def snapshot(self, scope, identity):
        import hashlib
        from datetime import datetime

        try:
            stored = self.get(scope, identity)
            if set(stored) != {"kind", "value"} or stored["kind"] != "public_web_snapshot":
                raise ValueError("Wrong snapshot artifact kind")
            raw = dict(stored["value"])
            raw["id"] = UUID(raw["id"])
            raw["retrieved_at"] = datetime.fromisoformat(raw["retrieved_at"])
            snapshot = Snapshot(**raw)
            if (
                snapshot.id != UUID(str(identity))
                or snapshot.content_hash != hashlib.sha256(snapshot.markdown.encode()).hexdigest()
            ):
                raise ValueError("Snapshot identity or body changed")
            return snapshot
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            raise DomainError("SOURCE_UNAVAILABLE", "原运行快照正文与元数据无法核对。") from exc


class ResearchReadAdapter:
    def __init__(self, tool_host, artifacts: ResearchArtifacts, *, user_messages, read_refs=None):
        self.tool_host, self.artifacts, self.user_messages = tool_host, artifacts, user_messages
        self.read_refs = read_refs

    def resume(self, scope, arguments, *, intent_key):
        identity = uuid5(scope.run_id, "research.fanout:" + intent_key)
        if self.artifacts._path(scope, identity).exists():
            saved = self.artifacts.get(scope, identity)
            if saved.get("kind") != "research_ledger":
                raise DomainError("SOURCE_UNAVAILABLE", "原研究作业引用类型不一致。")
            return self.restore_fanout(scope, arguments, saved["value"])
        return self(scope, arguments, name="research.fanout", job_id=identity)

    def __call__(self, scope, arguments, *, name, job_id=None):
        # URLs are extracted from actual persisted human messages at the host.
        for message in self.user_messages(scope):
            self.tool_host.service.register_user_message(scope, message)
        def pin_plan(tasks):
            self.artifacts.put(scope, uuid5(job_id, "research_plan"), {
                "kind": "research_plan", "tasks": [asdict(task) for task in tasks],
            })

        result = asyncio.run(
            self.tool_host.call(scope, name, arguments, job_id=job_id, pin_plan=pin_plan)
            if job_id is not None else self.tool_host.call(scope, name, arguments)
        )
        if name == "research.search":
            # The tool host retains its list contract; the persisted read uses
            # the same object envelope as the isolated research graph.
            return {"hits": result, "provider": self.tool_host.service.search_adapter.provider}
        if name == "research.fanout":
            if "snapshot_read_refs" in result:
                raise DomainError("SOURCE_UNAVAILABLE", "研究结果不能自行声明服务器读取引用。")
            result = {
                **result,
                "snapshot_digests": {
                    ref["id"]: digest(asdict(self.artifacts.snapshot(scope, UUID(ref["id"]))))
                    for ref in result["snapshots"]
                },
            }
            self._fanout_material(scope, arguments, result)
            if self.read_refs is not None:
                result["snapshot_read_refs"] = self._snapshot_read_refs(scope, result)
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

    def restores(self):
        """Rehydrate completed reads without issuing search or starting another job."""
        return {
            "research.search": self.restore_search,
            "research.fanout": self.restore_fanout,
        }

    def restore_search(self, scope, arguments, previous):
        from .research_read_ledger import restore_search

        data = SearchInput.model_validate(arguments)
        child = ResearchChild(self.tool_host.service, scope, ResearchTask("replay", data.query))
        try:
            return restore_search(child, data.query, previous, current=self.artifacts.current)
        except ResearchError as exc:
            raise DomainError("SOURCE_UNAVAILABLE", "原搜索回执无法核对。") from exc

    def _fanout_material(self, scope, arguments, previous):
        """Validate every retained document and quoted page before restoring any authority."""
        self.artifacts.current(scope)
        try:
            data = FanoutInput.model_validate(arguments)
            if (
                set(previous) - {"snapshot_read_refs"} != {
                    "job_id", "status", "ledger", "coverage", "failures", "snapshots",
                    "snapshot_digests",
                }
                or str(UUID(previous["job_id"])) != previous["job_id"]
                or previous["status"] not in {"completed", "partial", "unavailable"}
                or any(not isinstance(previous[key], list) for key in (
                    "ledger", "coverage", "failures", "snapshots",
                ))
                or not isinstance(previous["snapshot_digests"], dict)
            ):
                raise ValueError("Invalid fanout receipt")
            task_keys = [task.key for task in data.tasks]
            if len(set(task_keys)) != len(task_keys) or [
                row["task_key"] for row in previous["coverage"]
            ] != task_keys:
                raise ValueError("Fanout tasks differ")
            snapshots, urls, reads = {}, set(), set()
            for ref in previous["snapshots"]:
                identity = UUID(ref["id"])
                if str(identity) != ref["id"] or ref["id"] in snapshots:
                    raise ValueError("Duplicate or malformed snapshot identity")
                snapshot = self.artifacts.snapshot(scope, identity)
                expected = {
                    field.name: getattr(snapshot, field.name) for field in fields(SnapshotReference)
                }
                expected["id"] = str(expected["id"])
                expected["retrieved_at"] = expected["retrieved_at"].isoformat()
                if (
                    ref != expected or snapshot.status not in {"ok", "partial"}
                    or canonical_url(snapshot.url) != snapshot.url
                    or canonical_url(snapshot.final_url) != snapshot.final_url
                    or previous["snapshot_digests"].get(ref["id"]) != digest(asdict(snapshot))
                ):
                    raise ValueError("Full snapshot metadata differs")
                snapshots[ref["id"]] = snapshot
            if set(previous["snapshot_digests"]) != set(snapshots):
                raise ValueError("Snapshot digest manifest differs")
            for coverage in previous["coverage"]:
                for search in coverage["searches"]:
                    if not isinstance(search["provider"], str) or not search["provider"]:
                        raise ValueError("Missing search provider")
                    for url in search["urls"]:
                        if canonical_url(url) != url:
                            raise ValueError("Invalid observed URL")
                        urls.add(url)
                for read in coverage["reads"]:
                    if read["error"] is not None:
                        continue
                    snapshot = snapshots[read["snapshot_id"]]
                    if read["url"] != snapshot.url:
                        raise ValueError("Read URL differs from its snapshot")
                    self._page_bounds(snapshot, read["locator"])
                    reads.add((coverage["task_key"], read["snapshot_id"], read["locator"]))
                    urls.add(snapshot.url)
            if {identity for _, identity, _ in reads} != set(snapshots):
                raise ValueError("Snapshot lacks an actual successful read")
            for row in previous["ledger"]:
                snapshot = snapshots[row["snapshot_id"]]
                if (
                    (row["task_key"], row["snapshot_id"], row["locator"]) not in reads
                    or row["snapshot_url"] != snapshot.final_url
                    or not isinstance(row["quote"], str) or not row["quote"]
                ):
                    raise ValueError("Ledger citation lacks an actual read")
                start, end = self._page_bounds(snapshot, row["locator"])
                if row["quote"] not in snapshot.markdown[start:end]:
                    raise ValueError("Ledger quote is outside its actual page")
            return snapshots, urls
        except (OSError, ValueError, KeyError, TypeError, AttributeError, ResearchError) as exc:
            raise DomainError(
                "SOURCE_UNAVAILABLE", "原研究作业、快照或逐字读取位置无法核对。"
            ) from exc

    def _snapshot_read_refs(self, scope, result):
        """Only a server ledger callback can mint or revalidate references.

        Fresh results omit the field. On replay the callback receives the exact
        saved field and must recheck those call IDs, not substitute later reads.
        Its private copy prevents a callback from changing the research receipt.
        """
        self.artifacts.current(scope)
        if self.read_refs is None:
            raise DomainError("SOURCE_UNAVAILABLE", "原研究读取引用缺少服务器核对端口。")
        try:
            refs = self.read_refs(scope, deepcopy(result))
            if not isinstance(refs, list):
                raise ValueError("Read references must be a list")
            snapshots = {ref["id"]: ref for ref in result["snapshots"]}
            pages = {(read["snapshot_id"], read["locator"])
                     for coverage in result["coverage"] for read in coverage["reads"]
                     if read["error"] is None}
            calls, covered = set(), set()
            for ref in refs:
                if not isinstance(ref, dict) or set(ref) != {
                    "call_id", "snapshot_id", "content_hash", "locator",
                }:
                    raise ValueError("Invalid read reference fields")
                for field in ("call_id", "snapshot_id"):
                    if not isinstance(ref[field], str) or str(UUID(ref[field])) != ref[field]:
                        raise ValueError("Invalid read identity")
                if (
                    not isinstance(ref["content_hash"], str)
                    or re.fullmatch(r"[a-f0-9]{64}", ref["content_hash"]) is None
                    or ref["content_hash"] != snapshots[ref["snapshot_id"]]["content_hash"]
                    or not isinstance(ref["locator"], str)
                    or (ref["snapshot_id"], ref["locator"]) not in pages
                    or ref["call_id"] in calls
                ):
                    raise ValueError("Read reference differs from actual fanout coverage")
                calls.add(ref["call_id"])
                covered.add((ref["snapshot_id"], ref["locator"]))
            if covered != pages:
                raise ValueError("Actual read references do not cover all fanout pages")
            refs = sorted(deepcopy(refs), key=lambda ref: ref["call_id"])
            if ("snapshot_read_refs" in result
                    and digest(refs) != digest(result["snapshot_read_refs"])):
                raise ValueError("Saved read references cannot be replaced on replay")
            self.artifacts.current(scope)
            return refs
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise DomainError("SOURCE_UNAVAILABLE", "研究读取引用与实际作业账本不一致。") from exc

    @staticmethod
    def _page_bounds(snapshot, locator):
        match = re.fullmatch(r"chars:(0|[1-9][0-9]*):(0|[1-9][0-9]*)", locator)
        if match is None:
            raise ValueError("Invalid page locator")
        start, end = map(int, match.groups())
        if (
            not start <= end <= len(snapshot.markdown)
            or (start == end and end < len(snapshot.markdown))
        ):
            raise ValueError("Page locator is outside its snapshot")
        return start, end

    def restore_fanout(self, scope, arguments, previous):
        self.artifacts.current(scope)
        try:
            stored = self.artifacts.get(scope, UUID(previous["job_id"]))
            if (
                set(stored) != {"kind", "value"} or stored["kind"] != "research_ledger"
                or digest(stored["value"]) != digest(previous)
            ):
                raise ValueError("Completed fanout differs from its original job artifact")
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            raise DomainError("SOURCE_UNAVAILABLE", "原运行研究作业文件缺失或与回执不同。") from exc
        snapshots, urls = self._fanout_material(scope, arguments, previous)
        if "snapshot_read_refs" in previous:
            self._snapshot_read_refs(scope, previous)
        self.artifacts.current(scope)
        service = self.tool_host.service
        key = scope.tenant_id, scope.requester_id, scope.session_id, scope.run_id
        with service._lock:
            service._allowlists.setdefault(key, set()).update(urls)
            for snapshot in snapshots.values():
                service._snapshots[(key, snapshot.url)] = snapshot
        return previous

    def admit_history(self, parent, arguments, previous, consumer):
        """Reuse only revalidated snapshots in the same actual private conversation."""
        if any(getattr(parent, key) != getattr(consumer, key) for key in (
            "tenant_id", "requester_id", "session_id", "category_id", "product_id", "proposal_id",
        )):
            raise DomainError("FORBIDDEN_SCOPE", "历史研究来源不属于当前本人会话。", 403)
        result = self.restore_fanout(parent, arguments, previous)
        self.artifacts.current(consumer)
        source_ids = {str(row["id"]) for row in result["snapshots"]}
        old_key = parent.tenant_id, parent.requester_id, parent.session_id, parent.run_id
        new_key = consumer.tenant_id, consumer.requester_id, consumer.session_id, consumer.run_id
        service = self.tool_host.service
        with service._lock:
            admitted = [(url, snapshot) for (key, url), snapshot in service._snapshots.items()
                        if key == old_key and str(snapshot.id) in source_ids]
            if {str(snapshot.id) for _, snapshot in admitted} != source_ids:
                raise DomainError("SOURCE_UNAVAILABLE", "历史研究来源不完整，请重新核对原记录。")
            service._allowlists.setdefault(new_key, set()).update(url for url, _ in admitted)
            for url, snapshot in admitted:
                service._snapshots[(new_key, url)] = snapshot
        return result
