from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from app.auth.errors import ObjectPermissionDeniedError
from app.auth.project_access import ProjectAccessService
from app.auth.repository import AuthContext, TenantRecord, UserRecord
from app.auth.roles import Action, Role


class StubProjectAccessRepository:
    def __init__(self, *, project_exists: bool = True, is_member: bool = False) -> None:
        self.project_exists_result = project_exists
        self.is_member_result = is_member
        self.last_tenant_id: UUID | None = None
        self.last_user_id: UUID | None = None

    def project_exists(self, *, tenant_id: UUID, project_id: UUID) -> bool:
        self.last_tenant_id = tenant_id
        return self.project_exists_result

    def is_project_member(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        user_id: UUID,
    ) -> bool:
        self.last_tenant_id = tenant_id
        self.last_user_id = user_id
        return self.is_member_result


def auth_context(role: Role) -> AuthContext:
    tenant_id = uuid4()
    return AuthContext(
        tenant=TenantRecord(
            id=tenant_id,
            slug="beepump",
            name="Beehive Technology",
            status="active",
        ),
        user=UserRecord(
            id=uuid4(),
            tenant_id=tenant_id,
            username=role.value,
            display_name=role.value,
            role=role,
            email=None,
            password_hash=None,
            is_active=True,
        ),
    )


@pytest.mark.parametrize("role", [Role.OWNER, Role.ADMIN])
def test_owner_and_admin_can_authorize_tenant_projects_without_membership(role: Role) -> None:
    repository = StubProjectAccessRepository(is_member=False)
    context = auth_context(role)

    access = ProjectAccessService(repository).authorize(
        context=context,
        project_id=uuid4(),
        action=Action.PROJECT_VIEW,
    )

    assert access.role is role
    assert access.tenant_id == context.tenant.id
    assert repository.last_tenant_id == context.tenant.id
    assert repository.last_user_id is None


@pytest.mark.parametrize(
    "role",
    [
        Role.PROJECT_MANAGER,
        Role.ENGINEER,
        Role.QUALITY,
        Role.SUPPLIER,
        Role.CUSTOMER,
    ],
)
def test_non_admin_roles_require_project_membership(role: Role) -> None:
    context = auth_context(role)

    with pytest.raises(ObjectPermissionDeniedError):
        ProjectAccessService(StubProjectAccessRepository(is_member=False)).authorize(
            context=context,
            project_id=uuid4(),
            action=Action.PROJECT_VIEW,
        )

    access = ProjectAccessService(StubProjectAccessRepository(is_member=True)).authorize(
        context=context,
        project_id=uuid4(),
        action=Action.PROJECT_VIEW,
    )
    assert access.role is role


@pytest.mark.parametrize("role", [Role.SUPPLIER, Role.CUSTOMER])
def test_external_members_cannot_expand_their_surface_with_membership(role: Role) -> None:
    context = auth_context(role)
    service = ProjectAccessService(StubProjectAccessRepository(is_member=True))

    with pytest.raises(ObjectPermissionDeniedError):
        service.authorize(
            context=context,
            project_id=uuid4(),
            action=Action.WORK_ITEM_VIEW,
        )


def test_missing_or_cross_tenant_project_fails_with_the_same_denial() -> None:
    context = auth_context(Role.OWNER)

    with pytest.raises(ObjectPermissionDeniedError):
        ProjectAccessService(StubProjectAccessRepository(project_exists=False)).authorize(
            context=context,
            project_id=uuid4(),
            action=Action.PROJECT_VIEW,
        )
