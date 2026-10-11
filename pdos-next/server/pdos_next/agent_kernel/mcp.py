"""Server-admitted MCP tools. Credentials and raw replies stay in the isolated host."""

from dataclasses import dataclass

from pdos_next.errors import DomainError
from pdos_next.service import digest

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
            decision = egress(session, scope, connector.key, text=str(arguments))
            # Captured only for the bounded network call, never sent to model/event/result.
            endpoint, secret_ref, revision = (
                connector.endpoint,
                connector.secret_ref,
                connector.revision,
            )
            grant_ids = [str(g.id) for g in grants]
            connector_key = connector.key
        call_id, prior = self.store.claim(
            scope,
            intent_key,
            f"mcp.{tool}",
            {
                "connector_id": str(connector_id),
                "revision": revision,
                "arguments": arguments,
                "grant_ids": grant_ids,
                "egress_agreement": decision.agreement_id,
            },
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
                if (latest.revision, latest.endpoint, latest.secret_ref) != (
                    revision,
                    endpoint,
                    secret_ref,
                ):
                    raise DomainError("VERSION_CONFLICT", "连接器配置已变化。")
                if set(grant_ids) != {str(g.id) for g in current_grants}:
                    raise DomainError("FORBIDDEN_SCOPE", "连接器授权已变化。")
                egress(session, scope, connector_key, text=str(arguments))
            sent = True
            raw = self.ports.transport(endpoint, credential, tool, arguments)
            # Main never sees raw connector instructions or claims of authorization.
            rows = self.ports.extract(scope.child("mcp"), raw, spec)
            result = {
                "connector_id": str(connector_id),
                "tool": tool,
                "rows": rows,
                "raw_digest": digest(raw),
                "grant_ids": grant_ids,
                "call_id": str(call_id),
            }
            self.store.settle(scope, call_id, result=result)
            return result
        except DomainError as error:
            self.store.release_call(
                scope, call_id, error=error.code, unknown=sent and spec.get("kind") != "read"
            )
            raise
        except Exception:
            self.store.release_call(scope, call_id, unknown=sent, error="EXTERNAL_OUTCOME_UNKNOWN")
            raise DomainError(
                "EXTERNAL_OUTCOME_UNKNOWN",
                "MCP 原调用待对账，不盲目重发。",
                detail={"call_id": str(call_id)},
            ) from None
