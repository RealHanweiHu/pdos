"""Change disciplines that a professional role can currently sign off (D26)."""

from typing import get_args

from pdos_next.domain.builds.professional_authority.schemas import FactInput
from pdos_next.errors import DomainError

SIGNING_ROLES = frozenset(get_args(FactInput.model_fields["role"].annotation))


def require_signing_roles(disciplines):
    """Refuse a change policy whose disciplines no professional role can sign off.

    No role covers customer or regulatory sign-off yet, so such a change could never
    close. This refusal lifts by itself once the role list covers them (D21-B2).
    """
    unsupported = sorted(set(disciplines) - SIGNING_ROLES)
    if unsupported:
        raise DomainError(
            "CHANGE_DISCIPLINE_UNSUPPORTED",
            "暂不支持需要认证或客户专业签核的变更：目前没有可签核这些专业的角色。",
            422,
            detail={"disciplines": unsupported},
        )
