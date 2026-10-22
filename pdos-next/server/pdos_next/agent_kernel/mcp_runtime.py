"""Server-only MCP storage and KMS metadata; no credential material in configuration."""

from pathlib import Path
from uuid import UUID

from pydantic import Field, model_validator

from pdos_next.schemas.model_configuration.dto import ClosedDTO


class McpSecretSlot(ClosedDTO):
    tenant_id: UUID
    reference: str = Field(min_length=1, max_length=2000)
    secret_arn: str = Field(pattern=r"^acs:kms:[a-z0-9-]+:[0-9]+:secret/[^\s]+$")


class McpConfiguration(ClosedDTO):
    artifact_root: str
    secrets: list[McpSecretSlot] = Field(default_factory=list)

    @model_validator(mode="after")
    def locations(self):
        if not Path(self.artifact_root).is_absolute():
            raise ValueError("An absolute private MCP artifact root is required")
        identities = [(row.tenant_id, row.reference) for row in self.secrets]
        if len(identities) != len(set(identities)):
            raise ValueError("MCP server secret bindings must be unique")
        return self


def configured_ports(engine, config, host):
    from pdos_next.research.runtime import checkpoints

    from .mcp_transport import StreamableMcpTransport
    from .persistence import KernelStore
    from .research_adapter import ResearchArtifacts

    store = KernelStore(engine)
    return {
        "mcp_resolve_secret": host.mcp_secret,
        "mcp_transport": StreamableMcpTransport(),
        "mcp_artifacts": ResearchArtifacts(config.artifact_root, current=store.current),
        "mcp_checkpointer_factory": checkpoints,
    }
