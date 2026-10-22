"""Ordinary platform reads; private links require an exact Run-bound target."""

from pdos_next.database import tenant_session
from pdos_next.domain.products import platforms
from pdos_next.domain.products.platform_schemas import PlatformReadInput
from pdos_next.errors import DomainError
from pdos_next.service import digest, require_access

from .execution import check_run_binding
from .models import AgentRun

SCHEMAS = {"platform.read": PlatformReadInput}


class PlatformReads:
    def __init__(self, store, commands):
        self.store, self.commands = store, commands

    def handlers(self):
        return {"platform.read": self.call}

    def restores(self):
        return {"platform.read": self.restore}

    def call(self, scope, arguments):
        payload = PlatformReadInput.model_validate(arguments)
        if scope.category_id is None or (
            scope.product_id is not None
            and payload.product_id is not None
            and scope.product_id != payload.product_id
        ):
            raise DomainError("FORBIDDEN_SCOPE", "平台读取不属于当前品类或型号运行。", 403)
        with tenant_session(
            self.store.engine,
            scope.tenant_id,
            actor_id=scope.writer_id,
            requester_id=scope.requester_id,
            category_id=scope.category_id,
            read_snapshot=True,
        ) as session:
            run = session.get(AgentRun, scope.run_id)
            check_run_binding(run, scope, for_write=False)
            self.store.authority(session, scope)
            ctx = self.commands.context(scope)
            require_access(session, ctx, scope.product_id)
            from .proposal_context import KEY

            shared_only = True
            if KEY in getattr(run, "versions", {}):
                from .m3_spec_compare import _objects

                objects = _objects(session, ctx, scope, run)
                if payload.product_id is not None:
                    shared_only = not objects.target(payload.product_id, payload.variant_id)
            result = platforms.read(session, ctx, payload, shared_only=shared_only)
            self.store.authority(session, scope)
            check_run_binding(session.get(AgentRun, scope.run_id), scope, for_write=False)
            return result

    def restore(self, scope, arguments, previous):
        result = self.call(scope, arguments)
        if digest(result) != digest(previous):
            raise DomainError("SOURCE_STALE", "平台关联已有变化，请重新读取。")
        return result
