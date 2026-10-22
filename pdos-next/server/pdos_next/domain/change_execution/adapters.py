"""Only the host stages versions/receipts; pure ChangeControl owns transition rules."""

from pdos_next.domain.change_control.handlers import ChangeControlHandler
from pdos_next.domain.change_control.ports import Authority, Currentness, Ports
from pdos_next.domain.change_control.rules import digest
from pdos_next.errors import DomainError


def unavailable(*args, **kwargs):
    raise DomainError("INTEGRATION_REQUIRED", "正式批准、实施、生效及关闭端口尚未接入。", 503)


class Commands:
    def __init__(self, authority, request, save=None):
        self.authority, self.request_value, self.save = authority, request, save

    def context(self, uow, operation, subject_id):
        return self.authority

    def begin(self, uow, invocation):
        return self.authority

    def replay(self, uow, invocation, authority):
        # Common execute already performs exact key/intent dedup after current ACL.
        return None

    def request(self, uow, scope, request_id):
        if self.request_value is None or self.request_value.id != request_id:
            raise DomainError("FORBIDDEN_SCOPE", "固定变更请求不可读取。", 403)
        return self.request_value

    confirm = unavailable

    def record(self, uow, invocation, mutation):
        if self.save is None:
            raise DomainError("INTEGRATION_REQUIRED", "共同变更保存端口未配置。", 503)
        return self.save(mutation)


class Facts:
    def __init__(self, reader, sources, graph=None):
        self.reader, self.sources, self.graph_value = reader, sources, graph

    def audience(self, uow, authority, audience, refs, sources):
        if tuple(audience) != self.reader.target:
            raise DomainError("AUDIENCE_USE_FORBIDDEN", "图/请求受众不一致。", 403)
        for ref in refs:
            if ref.kind != "graph_snapshot":
                self.reader.resolve(ref)
        for source in sources:
            self.source(uow, authority, source)

    def ref(self, uow, authority, ref):
        if ref.kind == "graph_snapshot":
            if self.graph_value is None or (self.graph_value.id, self.graph_value.revision) != (
                ref.id,
                ref.revision,
            ):
                raise DomainError("FIXED_REFERENCE_MISMATCH", "图引用并非本次固定捕获。")
        else:
            self.reader.resolve(ref)
        return ref

    def source(self, uow, authority, source):
        if source.kind == "artifact":
            if digest(source) not in self.sources:
                raise DomainError("MISSING_REQUIRED_EVIDENCE", "来源未通过固定行及原件核对。", 422)
        elif source.kind == "domain":
            if not any(obj.source == source for obj in self.reader.objects.values()):
                raise DomainError("SOURCE_UNAVAILABLE", "领域来源不属于已核验固定图。")
        else:
            raise DomainError("SOURCE_UNAVAILABLE", "不能用任意Command UUID作为变更证据。")
        return Currentness(current=True)

    def currentness(self, uow, authority, ref):
        self.ref(uow, authority, ref)
        return Currentness(current=ref.kind == "graph_snapshot" or self.reader.resolve(ref).current)

    def graph(self, uow, authority, ref):
        self.ref(uow, authority, ref)
        return self.graph_value

    selection = implementation = effectivity = verification = unavailable


class Policies:
    assess = unavailable


def authority_dto(value, ctx, scope, audience, at):
    return Authority(
        scope=scope,
        actor_id=ctx.actor_id,
        requester_id=ctx.requester_id,
        actor_kind="human",
        audience=audience,
        roles=tuple(value["roles"]),
        authorized=value["authorized"],
        qualified=value["qualified"] is True,
        cancelled=False,
        now=at,
    )


def kernel(authority, request, reader, sources, graph=None, save=None):
    return ChangeControlHandler(
        Ports(Commands(authority, request, save), Facts(reader, sources, graph), Policies())
    )
