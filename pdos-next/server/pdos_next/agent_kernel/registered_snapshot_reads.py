"""Actual category snapshot pages in the isolated research graph, under ordinary RLS."""

from dataclasses import fields
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import or_, select

from pdos_next.errors import DomainError
from pdos_next.research.types import ReadPage, ReadTrace, Snapshot
from pdos_next.research.web import canonical_url
from pdos_next.service import digest

from .bindings import execution_key
from .deterministic_proofs import _historical_read
from .models import AgentToolCall, PublicWebSnapshot
from .read_execution import ReadBinding, ReadSource, build_read_binding, verify_read_source
from .snapshot_read_ledger import SnapshotPage, _registration, page_result


class RegisteredSnapshotReads:
    def __init__(self, store):
        self.store = store

    def read(self, host, child, spec, arguments, intent_key, *, source):
        scope, service = child._scope, child._service
        url = canonical_url(arguments["url"])
        if not isinstance(source, ReadSource) or intent_key != execution_key(
            scope.run_id, source.model_call_id, source.response_index
        ):
            raise DomainError("FORBIDDEN_SCOPE", "读取须绑定实际模型回复。")
        with self.store.transaction(scope) as (session, run):
            prior = session.scalar(
                select(AgentToolCall).where(
                    AgentToolCall.tenant_id == scope.tenant_id,
                    AgentToolCall.run_id == scope.run_id,
                    AgentToolCall.call_key == intent_key,
                )
            )
            binding = None
            completed = prior is not None and prior.state == "completed"
            if prior is not None:

                def deny(reason):
                    error = DomainError("SOURCE_UNAVAILABLE", "原快照读取绑定不可用。")
                    error.detail["reason"] = reason
                    raise error

                try:
                    binding = ReadBinding.model_validate(prior.execution_binding)
                    if binding.read_kind not in {"ordinary/v1", "registered_snapshot/v1"}:
                        deny("snapshot_read_kind_invalid")
                    if completed:
                        _, actual, binding, original = _historical_read(
                            session,
                            scope,
                            prior.id,
                            binding.read_kind,
                            deny=deny,
                        )
                        if (
                            actual.tool != spec.name
                            or actual.call_key != intent_key
                            or binding.model_call_id != source.model_call_id
                            or binding.response_index != source.response_index
                            or digest(original) != digest(arguments)
                        ):
                            deny("snapshot_read_source_mismatch")
                        if binding.read_kind == "ordinary/v1":
                            # Keep the original raw restore route even if this URL
                            # has gained a registered snapshot since the read.
                            return None
                        proof = SnapshotPage.model_validate(actual.result)
                        identity, page_chars = proof.snapshot_id, binding.page_chars
                    else:
                        # An unfinished call pins its type, not a completed source
                        # proof. Revalidate the producer before its unknown-outcome exit.
                        from .tools import default_registry

                        model = verify_read_source(
                            session,
                            scope,
                            run,
                            spec,
                            arguments,
                            source,
                            host.adapters.tool_registry or default_registry(),
                            host.adapters.route_for(scope),
                            catalog=host.catalog,
                            intent_key=intent_key,
                        )
                        expected = build_read_binding(
                            scope,
                            run,
                            spec,
                            source,
                            model,
                            read_kind=binding.read_kind,
                            server_metadata={"page_chars": binding.page_chars}
                            if binding.read_kind == "registered_snapshot/v1"
                            else None,
                        ).model_dump(mode="json")
                        if (
                            prior.tenant_id != scope.tenant_id
                            or prior.run_id != scope.run_id
                            or prior.tool != spec.name
                            or prior.call_key != intent_key
                            or prior.receipt_id is not None
                            or prior.state not in {"started", "failed", "unknown"}
                            or prior.input_digest != digest([spec.name, arguments])
                            or prior.execution_binding != expected
                        ):
                            deny("snapshot_read_source_mismatch")
                        raise DomainError(
                            "EXTERNAL_OUTCOME_UNKNOWN",
                            "原调用须按回执对账，不能盲目重发。",
                            detail={"call_id": str(prior.id)},
                        )
                except (ValidationError, AttributeError, KeyError, TypeError, ValueError):
                    deny("snapshot_read_binding_invalid")
            if not completed:
                # New reads need an observed URL; a verified historical read already
                # binds its original URL grant and does not perform a new web request.
                key = scope.tenant_id, scope.requester_id, scope.session_id, scope.run_id
                with service._lock:
                    observed = url in service._allowlists.get(key, set())
                if not observed:
                    raise DomainError("FORBIDDEN_SCOPE", "网址须来自本轮搜索或用户消息。")
                rows = list(
                    session.scalars(
                        select(PublicWebSnapshot).where(
                            PublicWebSnapshot.tenant_id == scope.tenant_id,
                            PublicWebSnapshot.category_id == scope.category_id,
                            or_(PublicWebSnapshot.url == url, PublicWebSnapshot.final_url == url),
                        )
                    )
                )
                if not rows:
                    return None
                if len(rows) != 1:
                    raise DomainError(
                        "VERSION_CONFLICT",
                        "此网址有多个快照版本，须先明确固定来源。",
                        detail={"reason": "snapshot_selection_required"},
                    )
                identity = rows[0].id
                page_chars = (
                    binding.page_chars if binding is not None else service.limits.page_chars
                )

        def load(*_, previous=None):
            with self.store.transaction(scope) as (session, _):
                row = session.get(PublicWebSnapshot, identity)
                if (
                    not row
                    or row.tenant_id != scope.tenant_id
                    or row.category_id != scope.category_id
                    or scope.category_id is None
                    or row.visibility != "category"
                    or row.status not in {"ok", "partial"}
                    or url not in {row.url, row.final_url}
                ):
                    raise DomainError(
                        "SOURCE_UNAVAILABLE",
                        "原品类快照不可读或缺少出站上下文绑定。",
                        detail={"reason": "snapshot_unavailable"},
                    )
                _registration(session, row)
                from hashlib import sha256

                if sha256(row.markdown.encode()).hexdigest() != row.content_hash:
                    raise DomainError("SOURCE_UNAVAILABLE", "快照正文与固定摘要不同。")
                result = page_result(row, cursor=arguments.get("cursor", 0), page_chars=page_chars)
                if previous is not None and result != previous:
                    raise DomainError("SOURCE_STALE", "固定快照读取结果已变化。")
                snapshot = Snapshot(
                    **{field.name: getattr(row, field.name) for field in fields(Snapshot)}
                )
            page = ReadPage(snapshot, result["locator"], result["markdown"], result["next_cursor"])
            host.current(scope)
            child.pages[(snapshot.id, page.locator)] = page
            trace = ReadTrace(snapshot.url, snapshot.id, page.locator)
            if trace not in child.reads:
                child.reads.append(trace)
            return result

        def restore(previous):
            proof = SnapshotPage.model_validate(previous)
            if proof.snapshot_id != UUID(str(identity)):
                raise DomainError("SOURCE_UNAVAILABLE", "读取回执引用了其他快照。")
            return load(previous=previous)

        return host.read_callback(
            scope,
            spec,
            arguments,
            intent_key,
            source=source,
            callback=load,
            restore=restore,
            read_kind="registered_snapshot/v1",
            metadata={"page_chars": page_chars},
        )
