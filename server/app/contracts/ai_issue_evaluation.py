"""Issue-specific evaluation target identity; independent from meeting draft contracts."""

from typing import Literal

from app.contracts.ai_write_qualification import BundleVersion
from app.contracts.common_objects import Contract, Digest, Key, Positive, Text


class IssueEvaluationBinding(Contract):
    operation_key: Literal["event.issue.create"] = "event.issue.create"
    provider: Key
    model: Text
    model_version: Text | None
    release_bundle_version: BundleVersion
    suite_version: Key
    suite_digest: Digest
    adapter_version: Key
    policy_version: Key
    policy_revision: Positive
