"""Lease-scoped persistence of completed model results, never a model tool."""

from typing import Any, cast
from uuid import UUID

from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from app.ai.run_store import AgentRunStore, ClaimedAgentRun


class AgentCheckpointError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class AgentResultCheckpoints:
    def __init__(self, engine: Engine, run_store: AgentRunStore):
        if not run_store.projection_only:
            raise ValueError("checkpoint port requires a restricted run lease")
        self._engine, self._store = engine, run_store

    def _call(self, claim: ClaimedAgentRun, sql: str, body: str | None = None) -> Any:
        try:
            with self._engine.begin() as connection:
                self._store.bind(connection)
                return connection.execute(
                    text(sql), dict(run=claim.id, token=claim.lease_token, body=body)
                ).scalar_one()
        except DBAPIError as error:
            code = getattr(getattr(error.orig, "diag", None), "message_primary", "")
            if getattr(error.orig, "sqlstate", None) == "22023" and code.startswith(
                ("AGENT_", "BUDGET_")
            ):
                raise AgentCheckpointError(code) from error
            raise

    def save(self, claim: ClaimedAgentRun, body: str) -> UUID:
        return cast(
            UUID,
            self._call(
                claim, "SELECT cehub_ai.save_agent_result_checkpoint(:run,:token,:body)", body
            ),
        )

    def load(self, claim: ClaimedAgentRun) -> dict[str, Any] | None:
        return cast(
            dict[str, Any] | None,
            self._call(claim, "SELECT cehub_ai.load_agent_result_checkpoint(:run,:token)"),
        )
