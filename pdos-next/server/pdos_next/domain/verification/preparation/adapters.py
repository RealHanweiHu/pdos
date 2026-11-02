"""Narrow adapters to the delivered kernel; no commits, authority grants or sample ports."""

from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256

from pdos_next.domain.verification.handlers import VerificationHandler
from pdos_next.domain.verification.ports import Authority, BuildContext, Outcome, Ports
from pdos_next.errors import DomainError
from pdos_next.schemas.verification.contracts import DocumentRequirement, Scope

PROFESSIONAL_PREFIX = "professional-method:"
METHOD_POSITION = "professional-method-applicability"
WINDOW_POSITION = "request-tentative-window"


def professional_key(item_id):
    return PROFESSIONAL_PREFIX + sha256(item_id.encode()).hexdigest()


def professional_documents(items, ordinary_documents, refs=None):
    """Required per-item proof keeps populated method references from completing documents."""
    refs = refs or {}
    if any(doc.id.startswith(PROFESSIONAL_PREFIX) for doc in ordinary_documents):
        raise DomainError("INVALID_PAYLOAD", "原资料ID不能占用专业适用证明命名空间。", 422)
    return tuple(ordinary_documents) + tuple(
        DocumentRequirement(
            id=professional_key(item.id),
            title=f"专业方法适用核对：{item.feature[:1900]}",
            item_ids=(item.id,),
            source=refs.get(item.id),
            required=True,
        )
        for item in items
    )


def authority_dto(assessment, actor_id, at):
    """Only a trusted server assessment may reach this adapter."""
    return Authority(
        scope=Scope.model_validate(assessment["scope"]),
        actor_id=actor_id,
        actor_kind="human",
        roles=tuple(assessment["roles"]),
        authorized=assessment["authorized"] is True,
        qualified=assessment["qualified"] is True,
        cancelled=False,
        now=at,
    )


@dataclass
class TransactionCommands:
    authority: Authority
    fixed_request: object
    record_mutation: Callable
    accepted_confirmation: bool = False

    def context(self, operation, subject_id):
        return self.authority

    def begin(self, invocation):
        return self.authority

    def request(self, scope, request_id):
        if self.fixed_request is None or self.fixed_request.id != request_id:
            raise DomainError("FORBIDDEN_SCOPE", "请求不在固定事务上下文。", 403)
        return self.fixed_request

    def confirm(self, invocation, preview, authority):
        if not self.accepted_confirmation or invocation.operation != "verification.method.prepare":
            raise DomainError("CONFIRMATION_REQUIRED", "必须先消费共同实质确认。", 403)

    def record(self, invocation, mutation):
        row = self.record_mutation(mutation)
        return Outcome(subject_id=row.id, revision=row.revision, status=row.status)

    def run(self, *args):
        raise DomainError("INTEGRATION_REQUIRED", "本闭环不包含真实TestRun。", 503)

    def runs(self, *args):
        raise DomainError("INTEGRATION_REQUIRED", "本闭环不包含真实TestRun。", 503)


@dataclass
class FixedBuilds:
    ref: object
    status: str

    def get(self, scope, build_id):
        if (
            build_id != self.ref.id
            or scope.product_id != self.ref.product_id
            or (scope.project_id != self.ref.project_id)
        ):
            raise DomainError("FORBIDDEN_SCOPE", "Build不在固定服务器范围。", 403)
        return BuildContext(ref=self.ref, status=self.status)


@dataclass
class BoundEvidence:
    check_source: Callable

    def check(self, scope, source, purpose):
        self.check_source(scope, source, purpose)

    def verify_measurement(self, *args):
        raise DomainError("INTEGRATION_REQUIRED", "真实测量原值核对尚未接通。", 503)


def handler(commands, build_ref, build_status, check_source):
    return VerificationHandler(
        Ports(
            commands=commands,
            builds=FixedBuilds(build_ref, build_status),
            evidence=BoundEvidence(check_source),
        )
    )
