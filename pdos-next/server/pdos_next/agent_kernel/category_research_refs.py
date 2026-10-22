"""Actual completed child-read references, without raw external pages."""

from dataclasses import asdict
from uuid import UUID

from sqlalchemy import select

from pdos_next.errors import DomainError
from pdos_next.research.tools import ReadInput

from .deterministic_proofs import _historical_read
from .models import AgentToolCall, PublicWebSnapshot
from .snapshot_command import verify_snapshot_page


def _deny(*_args, **_kwargs):
    raise DomainError("SOURCE_UNAVAILABLE", "研究台账缺少当前运行的实际子页读取证明。")


class CategoryResearchRefs:
    def __init__(self, store, artifacts):
        self.store, self.artifacts = store, artifacts

    def __call__(self, scope, result):
        self.store.current(scope)
        try:
            snapshots = {item["id"]: item for item in result["snapshots"]}
            pages = {
                (item["snapshot_id"], item["locator"])
                for coverage in result["coverage"]
                for item in coverage["reads"]
                if item["error"] is None
            }
            if {identity for identity, _ in pages} != set(snapshots):
                _deny()
            with self.store.transaction(scope) as (session, _):
                self.store.authority(session, scope)
                if "snapshot_read_refs" in result:
                    identities = [item["call_id"] for item in result["snapshot_read_refs"]]
                    if len(set(identities)) != len(identities):
                        _deny()
                    rows = [
                        session.get(AgentToolCall, UUID(item["call_id"]))
                        for item in result["snapshot_read_refs"]
                    ]
                else:
                    rows = session.scalars(
                        select(AgentToolCall)
                        .where(
                            AgentToolCall.tenant_id == scope.tenant_id,
                            AgentToolCall.run_id == scope.run_id,
                            AgentToolCall.tool == "research.read",
                            AgentToolCall.state == "completed",
                        )
                        .order_by(AgentToolCall.created_at, AgentToolCall.id)
                    ).all()
                refs, covered = [], set()
                for row in rows:
                    if not row:
                        _deny()
                    page = (row.result.get("snapshot_id"), row.result.get("locator"))
                    if page not in pages:
                        if "snapshot_read_refs" in result:
                            _deny()
                        continue
                    if "snapshot_read_refs" not in result and page in covered:
                        continue
                    read_kind = row.execution_binding.get("read_kind")
                    if read_kind not in {"ordinary/v1", "registered_snapshot/v1"}:
                        _deny()
                    run, call, binding, arguments = _historical_read(
                        session,
                        scope,
                        row.id,
                        read_kind,
                        deny=_deny,
                    )
                    if call.tool != "research.read" or binding.isolation != "research":
                        _deny()
                    from .snapshot_read_ledger import SnapshotPage, SnapshotReadInput

                    snapshot = self.artifacts.snapshot(scope, UUID(page[0]))
                    if read_kind == "ordinary/v1":
                        ReadInput.model_validate(arguments)
                        verify_snapshot_page(snapshot, call.result, arguments)
                    else:
                        from .snapshot_read_ledger import _registration, page_result

                        payload = SnapshotReadInput.model_validate(arguments)
                        typed_page = SnapshotPage.model_validate(call.result)
                        registered = session.get(PublicWebSnapshot, snapshot.id)
                        if (
                            not registered or registered.visibility != "category"
                            or registered.tenant_id != run.tenant_id
                            or registered.category_id != run.category_id
                            or registered.status not in {"ok", "partial"}
                            or payload.url not in {registered.url, registered.final_url}
                        ):
                            _deny()
                        _registration(session, registered)
                        if any(
                            getattr(registered, key) != value
                            for key, value in asdict(snapshot).items()
                        ):
                            _deny()
                        if (
                            page_result(
                                registered,
                                cursor=payload.cursor,
                                page_chars=binding.page_chars,
                            )
                            != typed_page.model_dump(mode="json")
                        ):
                            _deny()
                    if snapshot.content_hash != snapshots[page[0]]["content_hash"]:
                        _deny()
                    refs.append(
                        {
                            "call_id": str(call.id),
                            "snapshot_id": str(snapshot.id),
                            "content_hash": snapshot.content_hash,
                            "locator": page[1],
                        }
                    )
                    covered.add(page)
                if covered != pages:
                    _deny()
                refs.sort(key=lambda item: item["call_id"])
                if "snapshot_read_refs" in result and refs != result["snapshot_read_refs"]:
                    _deny()
                return refs
        except (AttributeError, KeyError, TypeError, ValueError, OSError):
            _deny()
