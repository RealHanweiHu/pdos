"""Server-admitted MCP tools. Credentials and raw replies stay in the isolated host."""

from dataclasses import dataclass

from pdos_next.errors import DomainError
from pdos_next.service import digest

from .mcp_binding import connector_binding, redact_credential, validate_arguments
from .models import AgentToolCall
from .policy import egress, mcp_admission


@dataclass(frozen=True)
class McpPorts:
    resolve_secret: object
    transport: object
    extract: object


class McpService:
    def __init__(self, store, ports: McpPorts):
        self.store, self.ports = store, ports

    def call(
        self,
        scope,
        *,
        connector_id,
        tool,
        arguments,
        loaded_skills,
        automation_rule_id=None,
        explicit_external_write=False,
        intent_key,
        resume_read=False,
        parent_read_call_id=None,
    ):
        with self.store.transaction(scope) as (session, _):
            connector, spec, grants = mcp_admission(
                session,
                scope,
                connector_id,
                tool,
                loaded_skills=loaded_skills,
                automation_rule_id=automation_rule_id,
                external_write=explicit_external_write,
            )
            validate_arguments(spec, arguments)
            decision = egress(session, scope, connector.key)
            # Captured only for the bounded network call, never sent to model/event/result.
            endpoint, secret_ref, revision = (
                connector.endpoint,
                connector.secret_ref,
                connector.revision,
            )
            binding = connector_binding(connector, tool)
            grant_ids = sorted(str(g.id) for g in grants)
            grant_versions = {str(g.id): g.revision for g in grants}
            connector_key = connector.key
            dispatch = None
            if resume_read:
                from .read_execution import ReadBinding

                parent = session.get(AgentToolCall, parent_read_call_id)
                if (
                    not parent
                    or parent.run_id != scope.run_id
                    or parent.tool != "mcp.read"
                    or parent.tenant_id != scope.tenant_id
                    or parent.state not in {"started", "completed"}
                    or parent.execution_binding.get("kind") != "read"
                    or ReadBinding.model_validate(parent.execution_binding).isolation != "main"
                    or spec.get("kind") != "read"
                    or scope.isolation != "mcp"
                ):
                    raise DomainError("FORBIDDEN_SCOPE", "MCP 接续须绑定主图实际只读调用。")
                dispatch = {
                    "kind": "unbound",
                    "dispatch": "mcp-read/v1",
                    "isolation": "mcp",
                    "parent_read_call_id": str(parent.id),
                }
        # Registered remote names may already use all 160 characters. Keep their
        # full identity in the payload/result without overflowing the ledger label.
        label = f"mcp.{tool}"
        long_name = len(label) > 160
        call_id, prior = self.store.claim(
            scope,
            intent_key,
            "mcp.bound:" + digest(tool) if long_name else label,
            {
                "connector_id": str(connector_id),
                "connector_binding": binding,
                "arguments": arguments,
                "grant_ids": grant_ids,
                "grant_versions": grant_versions,
                "egress_agreement": decision.agreement_id,
                **({"tool": tool} if long_name else {}),
            },
            **({"resume_started": True, "execution_binding": dispatch} if resume_read else {}),
        )
        if prior is not None:
            return prior
        sent = False
        try:
            self.store.current(scope)
            credential = self.ports.resolve_secret(scope.tenant_id, secret_ref)
            if credential is None:
                raise DomainError("SOURCE_UNAVAILABLE", "连接器凭据未配置。")
            with self.store.transaction(scope) as (session, _):
                latest, _, current_grants = mcp_admission(
                    session,
                    scope,
                    connector_id,
                    tool,
                    loaded_skills=loaded_skills,
                    automation_rule_id=automation_rule_id,
                    external_write=explicit_external_write,
                )
                if connector_binding(latest, tool) != binding:
                    raise DomainError("VERSION_CONFLICT", "连接器配置已变化。")
                if grant_versions != {str(g.id): g.revision for g in current_grants}:
                    raise DomainError("FORBIDDEN_SCOPE", "连接器授权已变化。")
                egress(session, scope, connector_key)
            sent = True
            raw = redact_credential(
                self.ports.transport(endpoint, credential, tool, arguments), credential
            )
            # Main never sees raw connector instructions or claims of authorization.
            rows = self.ports.extract(scope.child("mcp"), raw, spec)
            result = {
                "connector_id": str(connector_id),
                "connector_revision": revision,
                "tool": tool,
                "rows": rows,
                "raw_digest": digest(raw),
                "grant_ids": grant_ids,
                "call_id": str(call_id),
                "grant_versions": grant_versions,
            }
            self.store.settle(scope, call_id, result=result)
            return result
        except DomainError as error:
            self.store.release_call(
                scope,
                call_id,
                error=error.code,
                unknown=error.code == "EXTERNAL_OUTCOME_UNKNOWN"
                or (sent and spec.get("kind") != "read"),
            )
            raise
        except Exception:
            self.store.release_call(scope, call_id, unknown=sent, error="EXTERNAL_OUTCOME_UNKNOWN")
            raise DomainError(
                "EXTERNAL_OUTCOME_UNKNOWN",
                "MCP 原调用待对账，不盲目重发。",
                detail={"call_id": str(call_id)},
            ) from None
