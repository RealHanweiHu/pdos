"""Trusted domain composition: one command, one Call, one atomic business transaction."""

from dataclasses import replace
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import ValidationError
from sqlalchemy import select

from pdos_next.contracts import PAYLOADS, Command, SourceRead
from pdos_next.database import category_transaction, tenant_session
from pdos_next.domain.preproject.access import fail
from pdos_next.errors import DomainError
from pdos_next.models import Receipt
from pdos_next.service import (
    Context,
    command_digest,
    command_scope,
    execute,
    receipt_view,
    require_access,
)

from .bindings import DomainBinding, WriteSource, execution_key
from .execution import (
    check_run_binding,
    finish_domain_call,
    prepare_domain_call,
    recover_domain_call,
)
from .models import AgentRun, AgentToolCall, PublicWebSnapshot


class ExistingResult(Exception):
    """Rollback an unused new Call before returning a separately verified old Receipt."""

    def __init__(self, receipt_id):
        self.receipt_id = receipt_id


class DomainCommands:
    def __init__(self, engine, *, catalog, registry, route, artifacts=None):
        self.engine, self.catalog, self.registry, self.route = engine, catalog, registry, route
        self.artifacts = artifacts

    @staticmethod
    def context(scope, *, call_id=None):
        return Context(
            scope.tenant_id,
            scope.writer_id,
            scope.requester_id,
            category_id=scope.category_id,
            agent_run_id=scope.run_id,
            cancel_epoch=scope.cancel_epoch,
            agent_call_id=call_id,
        )

    def transaction(self, scope):
        return tenant_session(
            self.engine,
            scope.tenant_id,
            actor_id=scope.writer_id,
            requester_id=scope.requester_id,
            category_id=scope.category_id,
        )

    def read_receipt(self, session, scope, receipt):
        require_access(session, self.context(scope), scope.product_id, write=False)
        actual = session.get(Receipt, receipt.id)
        if (
            actual is None
            or actual.tenant_id != scope.tenant_id
            or actual.category_id != scope.category_id
            or actual.product_id != scope.product_id
        ):
            raise DomainError("FORBIDDEN_SCOPE", "原回执不在当前可读范围。", 403)
        return actual

    def recover(self, scope, spec, arguments, intent_key, *, source: WriteSource):
        if scope.category_id is None:
            raise DomainError("FORBIDDEN_SCOPE", "领域写入须绑定实际品类。", 403)
        if intent_key != execution_key(scope.run_id, source.model_call_id, source.response_index):
            raise DomainError("FORBIDDEN_SCOPE", "恢复引用须来自服务器实际模型账本。", 403)
        with self.transaction(scope) as session:
            # Hold current read authority before Run/Call, without checking write qualification.
            require_access(session, self.context(scope), scope.product_id, lock=True)
            call = session.scalar(
                select(AgentToolCall).where(
                    AgentToolCall.run_id == scope.run_id,
                    AgentToolCall.call_key == intent_key,
                )
            )
            if call is None or call.state != "completed":
                return None
            try:
                bound = DomainBinding.model_validate(call.execution_binding)
            except ValidationError:
                raise DomainError("SOURCE_UNAVAILABLE", "原执行没有可信绑定。") from None
            recovered = recover_domain_call(
                session,
                scope,
                spec,
                arguments,
                source,
                command_digest=bound.command_digest,
                read_receipt=self.read_receipt,
            )
            return recovered[1] if recovered else None

    def command(self, session, scope, operation, arguments, intent_key):
        if operation not in PAYLOADS or not isinstance(arguments, dict):
            raise DomainError("SOURCE_UNAVAILABLE", "此领域命令尚未接入。")
        run = session.get(AgentRun, scope.run_id)
        # Even candidate preparation is pinned to the stored Run; payload fields
        # and a caller-provided RunScope never establish scope by themselves.
        check_run_binding(run, scope)
        payload = dict(arguments)
        for key in ("product_id", "proposal_id"):
            if key in PAYLOADS[operation].model_fields:
                actual = getattr(run, key)
                if key in payload and str(payload[key]) != str(actual):
                    fail(
                        "FORBIDDEN_SCOPE",
                        "proposal_run_mismatch" if key == "proposal_id" else "product_run_mismatch",
                        "命令对象与实际运行不一致。",
                        403,
                    )
                payload[key] = actual
        normalized = PAYLOADS[operation].model_validate(payload)
        current = require_access(session, self.context(scope), run.product_id)
        reads = self._artifact_reads(run)
        pinned = {read.artifact_id: read.expected_revision for read in reads}
        from .m3_object_reads import _references
        from .proposal_context import KEY, reference_key, stored_references

        refs = list(_references(arguments))
        for ref in refs:
            if ref.type in {"artifact", "original"}:
                self._require_artifact_read(pinned, ref.id, ref.version)
        if KEY in getattr(run, "versions", {}):
            allowed = {reference_key(ref) for ref in stored_references(run)[1]} | {
                ("original", str(read.artifact_id), read.expected_revision) for read in reads
            }
            if any(reference_key(ref) not in allowed for ref in refs):
                fail(
                    "MISSING_REQUIRED_EVIDENCE",
                    "source_read_not_bound",
                    "草稿引用须属于本次运行已绑定的资料。",
                )
        source = getattr(normalized, "source", None)
        if operation == "evidence.claim.record" and source is not None:
            if source.kind == "artifact":
                self._require_artifact_read(pinned, source.id, source.version)
            else:
                self._require_snapshot_read(
                    session, run, source.id, source.version, line=source.line, quote=source.quote,
                )
        else:
            source_id = getattr(normalized, "artifact_id", None)
            if source_id is not None:
                self._require_artifact_read(pinned, source_id)
        if operation == "evidence.link.create":
            evidence = normalized.evidence
            if evidence.type == "artifact":
                self._require_artifact_read(pinned, evidence.id, evidence.version)
            elif evidence.type == "snapshot":
                self._require_snapshot_read(
                    session, run, evidence.id, evidence.version, locator=evidence.locator,
                )
        return Command(
            command_id=uuid5(NAMESPACE_URL, intent_key),
            idempotency_key=intent_key,
            category_id=scope.category_id,
            product_id=scope.product_id,
            operation=operation,
            expected_revision=current.revision,
            source_read_set=reads,
            payload=normalized.model_dump(
                mode="json", exclude_unset=operation == "product.definition.item.patch"
            ),
        )

    @staticmethod
    def _artifact_reads(run):
        reads, versions = [], {}
        for raw in run.read_sources:
            try:
                parsed = SourceRead.model_validate(
                    {
                        "artifact_id": raw["artifact_id"],
                        "expected_revision": raw["expected_revision"],
                    }
                )
                product_id = raw.get("product_id")
                if product_id is not None:
                    source_product = UUID(str(product_id))
                    if run.product_id is not None and source_product != run.product_id:
                        raise ValueError("Artifact belongs to another product")
                if (
                    parsed.artifact_id in versions
                    and versions[parsed.artifact_id] != parsed.expected_revision
                ):
                    raise ValueError("Conflicting source versions")
            except (KeyError, TypeError, ValueError, ValidationError):
                fail(
                    "SOURCE_UNAVAILABLE",
                    "run_source_binding_invalid",
                    "运行读取账本缺少可信来源版本或范围。",
                )
            if parsed.artifact_id not in versions:
                reads.append(parsed)
            versions[parsed.artifact_id] = parsed.expected_revision
        return reads

    @staticmethod
    def _require_artifact_read(pinned, identity, version=None):
        if identity not in pinned or (version is not None and pinned[identity] != version):
            fail(
                "MISSING_REQUIRED_EVIDENCE",
                "source_read_not_bound",
                "运行未绑定此来源的明确版本。",
            )

    @staticmethod
    def _require_snapshot_read(
        session, run, identity, version, *, line=None, quote=None, locator=None,
    ):
        snapshot = session.get(PublicWebSnapshot, identity)
        if (
            not snapshot
            or snapshot.tenant_id != run.tenant_id
            or snapshot.category_id != run.category_id
            or version != 1
            or snapshot.status not in {"ok", "partial"}
        ):
            fail("SOURCE_UNAVAILABLE", "snapshot_unavailable", "快照不在运行实际可用的品类范围。")
        if snapshot.registered_by_run_id != run.id:
            from .execution import scope_for_run
            from .snapshot_read_ledger import validate_snapshot_read

            candidates = session.scalars(select(AgentToolCall).where(
                AgentToolCall.run_id == run.id,
                AgentToolCall.tool == "research.read",
                AgentToolCall.state == "completed",
                AgentToolCall.execution_binding["read_kind"].astext == "registered_snapshot/v1",
                AgentToolCall.result["snapshot_id"].astext == str(identity),
            )).all()
            for call in candidates:
                try:
                    if line is not None and quote:
                        validate_snapshot_read(
                            session, scope_for_run(run), identity, version, line, quote,
                            call_id=call.id,
                        )
                    else:
                        from .snapshot_locator import validate_snapshot_locator

                        validate_snapshot_locator(
                            session, scope_for_run(run), identity, version, locator,
                            call_id=call.id,
                        )
                except DomainError:
                    continue
                return
            fail(
                "SOURCE_UNAVAILABLE",
                "snapshot_read_not_bound",
                "复用其他运行快照须先登记可信读取账本。",
            )
        receipt = session.get(Receipt, snapshot.receipt_id)
        if (
            not receipt
            or receipt.tenant_id != run.tenant_id
            or receipt.category_id != run.category_id
            or receipt.requester_id != run.requester_id
            or receipt.operation != "research.snapshot.register"
            or receipt.subject_type != "public_web_snapshot"
            or receipt.subject_id != snapshot.id
            or receipt.subject_revision != version
            or receipt.agent_run_id not in {None, run.id}
        ):
            fail(
                "SOURCE_UNAVAILABLE",
                "snapshot_registration_invalid",
                "快照没有属于实际运行的登记回执。",
            )

    def execute(self, scope, operation, arguments, intent_key, *, source: WriteSource):
        spec = self.registry.get(operation)
        if spec.operation_key != operation or spec.tier != "T0" or scope.isolation != "main":
            raise DomainError("NAMED_DECISION_REQUIRED", "此操作没有 AI 自动执行权。", 403)
        previous = self.recover(scope, spec, arguments, intent_key, source=source)
        if previous is not None:
            return previous
        ctx = self.context(scope)

        def write(session):
            # The actual command transaction owns its ports; another API/worker bootstrap
            # sharing this Engine cannot replace them between prepare and common execute.
            session.info["domain_command_owner"] = self
            command = self.command(session, scope, operation, arguments, intent_key)
            command_scope(session, ctx, command, lock=True)
            call, previous = prepare_domain_call(
                session,
                scope,
                spec,
                arguments,
                source,
                catalog=self.catalog,
                registry=self.registry,
                route=self.route,
                command_digest=command_digest(command),
                read_receipt=self.read_receipt,
            )
            if previous is not None:
                return previous
            result = execute(session, replace(ctx, agent_call_id=call.id), command)
            receipt = session.get(Receipt, UUID(result["id"]))
            if (
                receipt.agent_run_id != scope.run_id
                or receipt.command_id != command.command_id
                or receipt.request_digest != command_digest(command)
            ):
                raise ExistingResult(receipt.id)
            return finish_domain_call(session, scope, call.id, receipt.id)

        try:
            return category_transaction(self.engine, ctx, write)
        except ExistingResult as previous:
            with self.transaction(scope) as session:
                receipt = session.get(Receipt, previous.receipt_id)
                if receipt is None:
                    raise DomainError(
                        "FORBIDDEN_SCOPE", "已有结果不在当前可读范围。", 403
                    ) from None
                receipt = self.read_receipt(session, scope, receipt)
                if receipt.operation != operation:
                    raise DomainError("FORBIDDEN_SCOPE", "已有结果的操作不一致。", 403) from None
                return {**receipt_view(receipt), "existing_result": True}
