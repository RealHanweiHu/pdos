import json
from dataclasses import asdict, dataclass
from datetime import datetime
from uuid import UUID

from pdos_next.object_storage.types import ObjectRef
from pdos_next.original_lifecycle.types import EffectPermit, LifecycleAction, LifecycleScope


@dataclass(frozen=True, slots=True)
class LegacyReadReference:
    reference: ObjectRef
    scope: LifecycleScope


def encode(value):
    return json.loads(
        json.dumps(
            asdict(value),
            default=lambda item: item.isoformat() if isinstance(item, datetime) else str(item),
        )
    )


def reference(value):
    return ObjectRef(**{**value, "id": UUID(value["id"])})


def permit(value):
    data = dict(value)
    data["reference"] = reference(data["reference"])
    data["scope"] = LifecycleScope(
        **{key: UUID(item) if item else None for key, item in data["scope"].items()}
    )
    for key in ("operation_id", "lease_token", "named_decider_id"):
        data[key] = UUID(data[key])
    for key in ("issued_at", "expires_at"):
        data[key] = datetime.fromisoformat(data[key])
    data["action"] = LifecycleAction(data["action"])
    return EffectPermit(**data)
