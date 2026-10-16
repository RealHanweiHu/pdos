"""Default server research ports; authority remains in the current Run and domain policy."""

import os
import re
from dataclasses import asdict
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, model_validator

from pdos_next.errors import DomainError
from pdos_next.schemas.model_configuration.dto import ClosedDTO


class ResearchConfiguration(ClosedDTO):
    search_endpoint: str
    search_provider: str = Field(min_length=1, max_length=160)
    artifact_root: str

    @model_validator(mode="after")
    def server_locations(self):
        endpoint = urlsplit(self.search_endpoint)
        if (
            endpoint.scheme not in {"http", "https"}
            or not endpoint.hostname
            or endpoint.username is not None
            or endpoint.password is not None
            or endpoint.query
            or endpoint.fragment
            or not Path(self.artifact_root).is_absolute()
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:_.@/-]{0,159}", self.search_provider)
        ):
            raise ValueError(
                "Trusted credential-free search endpoint and absolute artifact root required"
            )
        return self


def checkpoints():
    from langgraph.checkpoint.postgres import PostgresSaver

    from pdos_next.workflows.checkpoints import verified_checkpoint_url

    url = os.environ.get("PDOS_CHECKPOINT_DATABASE_URL")
    if not url:
        raise DomainError("SOURCE_UNAVAILABLE", "研究子任务检查点尚未配置。")
    return PostgresSaver.from_conn_string(verified_checkpoint_url(url))


def configured_ports(engine, config):
    from pdos_next.agent_kernel.persistence import KernelStore
    from pdos_next.agent_kernel.proposal_context import check
    from pdos_next.agent_kernel.research_adapter import ResearchArtifacts

    from .egress import decide
    from .search import SearxSearchAdapter
    from .service import ResearchService

    store = KernelStore(engine)
    artifacts = ResearchArtifacts(config.artifact_root, current=store.current)

    def egress(scope, provider, _categories, text):
        # The service's arguments cannot replace current persisted authority or categories.
        check(store, scope)
        with store.transaction(scope) as (session, run):
            decision = decide(session, scope, run, provider, text)
        store.emit(
            scope,
            {
                "type": "egress_checked",
                "channel": "research",
                **{
                    key: value.isoformat() if hasattr(value, "isoformat") else value
                    for key, value in asdict(decision).items()
                },
            },
        )
        return decision

    service = ResearchService(
        SearxSearchAdapter(config.search_endpoint, provider=config.search_provider),
        egress=egress,
        snapshot_sink=artifacts.save_snapshot,
    )
    return {
        "research_service": service,
        "research_artifacts": artifacts,
        "research_checkpointer_factory": checkpoints,
    }
