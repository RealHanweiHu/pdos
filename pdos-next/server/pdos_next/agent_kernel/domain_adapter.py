"""Trusted domain composition: one command, one Call, one atomic business transaction."""

from dataclasses import replace
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import ValidationError
from sqlalchemy import select

from pdos_next.contracts import PAYLOADS, Command, SourceRead
from pdos_next.database import category_transaction, tenant_session
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
from .execution import finish_domain_call, prepare_domain_call, recover_domain_call
from .models import AgentRun, AgentToolCall


class ExistingResult(Exception):
    """Rollback an unused new Call before returning a separately verified old Receipt."""

    def __init__(self, receipt_id):
        self.receipt_id = receipt_id


class DomainCommands:
    def __init__(self, engine, *, catalog, registry, route):
        self.engine, self.catalog, self.registry, self.route = engine, catalog, registry, route

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
        payload = dict(arguments)
        # Scope fields omitted from model definitions are supplied only by the actual Run.
        for key in ("product_id", "proposal_id"):
            if key in PAYLOADS[operation].model_fields:
                actual = getattr(scope, key)
                if key in payload and str(payload[key]) != str(actual):
                    raise DomainError("FORBIDDEN_SCOPE", "命令对象与实际运行不一致。", 403)
                payload[key] = actual
        normalized = PAYLOADS[operation].model_validate(payload)
        current = require_access(session, self.context(scope), scope.product_id)
        run = session.get(AgentRun, scope.run_id)
        if not run:
            raise DomainError("FORBIDDEN_SCOPE", "运行不在当前范围。", 403)
        reads = [
            SourceRead(artifact_id=r["artifact_id"], expected_revision=r["expected_revision"])
            for r in run.read_sources
        ]
        if hasattr(normalized, "artifact_id"):
            source_id = normalized.artifact_id
            if source_id not in {r.artifact_id for r in reads}:
                raise DomainError("MISSING_REQUIRED_EVIDENCE", "运行未绑定此来源的明确版本。")
        return Command(
            command_id=uuid5(NAMESPACE_URL, intent_key),
            idempotency_key=intent_key,
            category_id=scope.category_id,
            product_id=scope.product_id,
            operation=operation,
            expected_revision=current.revision,
            source_read_set=reads,
            payload=normalized.model_dump(mode="json"),
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
