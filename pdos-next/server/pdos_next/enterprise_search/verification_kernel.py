"""Project a frozen verification action into a Human-owned candidate event.

This port opens a separate ordinary requester transaction before the generic AI
command path. It does not preview, execute, or grant the requester an AI identity.
"""

from uuid import UUID

from pydantic import ValidationError

from pdos_next.agent_kernel.bindings import WriteSource, execution_key
from pdos_next.agent_kernel.execution import check_run_binding
from pdos_next.agent_kernel.models import AgentRun
from pdos_next.database import tenant_session
from pdos_next.domain.verification_execution.schemas import PreparationRecordPayload
from pdos_next.errors import DomainError
from pdos_next.schemas.verification.contracts import BuildRef
from pdos_next.service import Context

from .verification_candidates import PREPARATION, record


def prepare(owner, scope, spec, arguments, intent_key, *, source=None):
    """Return an action candidate, or None for the existing non-action path.

    ``verification_action`` is frozen by run startup. Model arguments never
    supply its Build/configuration choice or discussion citation identities.
    The bridge repeats current permissions, source identity and model-ledger
    verification in this Human transaction before recording its AgentEvent.
    """
    if spec.name != PREPARATION or spec.tier != "T1" or scope.isolation != "main":
        raise DomainError("FORBIDDEN_SCOPE", "复验准备只接受当前主运行的 T1 候选。", 403)
    with tenant_session(
        owner.engine, scope.tenant_id, actor_id=scope.requester_id,
        requester_id=scope.requester_id, category_id=scope.category_id,
    ) as session:
        # Hold the run lock before reading action/state so the bridge cannot
        # reuse a pre-cancellation ORM identity after its own lock acquisition.
        run = session.get(AgentRun, scope.run_id, with_for_update=True)
        check_run_binding(run, scope)
        action = run.versions.get("verification_action")
        if action is None:
            return None
        if not isinstance(source, WriteSource) or intent_key != execution_key(
            run.id, source.model_call_id, source.response_index,
        ):
            raise DomainError("FORBIDDEN_SCOPE", "复验候选须绑定服务器实际模型账本。", 403)
        try:
            if not isinstance(action, dict) or not isinstance(action.get("citation_ids"), list):
                raise ValueError
            request_id = UUID(action["request_id"])
            selection = BuildRef.model_validate(action["selection"])
            citations = tuple(UUID(value) for value in action["citation_ids"])
        except (KeyError, TypeError, ValueError, ValidationError):
            raise DomainError("SOURCE_UNAVAILABLE", "本次复验行动缺少固定目标或来源。") from None
        try:
            payload = PreparationRecordPayload.model_validate(arguments)
        except ValidationError:
            raise DomainError("INVALID_PAYLOAD", "复验准备须使用登记的原生字段。", 422) from None
        if payload.request_id != request_id:
            raise DomainError("FORBIDDEN_SCOPE", "复验准备须沿用本次行动固定的新请求身份。", 403)
        if not citations:
            raise DomainError("MISSING_REQUIRED_EVIDENCE", "继续处理须保留已核对的讨论来源。")
        ctx = Context(scope.tenant_id, scope.requester_id, scope.requester_id,
                      category_id=scope.category_id)
        candidate = record(
            session, ctx, run.id, operation=PREPARATION, arguments=arguments,
            source=source, selection=selection, owner=owner, citation_ids=citations,
        )
        return {**candidate, "write_tier": "T1"}
