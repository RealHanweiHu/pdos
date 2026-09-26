from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from app.auth.errors import ObjectPermissionDeniedError
from app.auth.project_access import ProjectAccessService
from app.auth.repository import AuthContext, TenantRecord, UserRecord
from app.auth.roles import Action, Role


class StubProjectAccessRepository:
    def __init__(
        self,
        *,
        project_exists: bool = True,
        is_member: bool = False,
        member_ids: frozenset[UUID] = frozenset(),
        principals: tuple[UUID, ...] = (),
    ) -> None:
        self.project_exists_result = project_exists
        self.is_member_result = is_member
        self.member_ids = member_ids
        self.principals = principals
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
        if self.member_ids:
            return user_id in self.member_ids
        return self.is_member_result

    def delegated_principals(
        self,
        *,
        tenant_id: UUID,
        delegate_user_id: UUID,
    ) -> tuple[UUID, ...]:
        return self.principals


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
            auth_version=1,
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


def test_active_delegate_borrows_project_reach_without_borrowing_role() -> None:
    """V1-A11: delegation lends membership, never permissions."""
    context = auth_context(Role.ENGINEER)
    principal_id = uuid4()
    repository = StubProjectAccessRepository(
        member_ids=frozenset({principal_id}),
        principals=(principal_id,),
    )
    service = ProjectAccessService(repository)
    project_id = uuid4()

    access = service.authorize(context=context, project_id=project_id, action=Action.WORK_ITEM_VIEW)
    assert access.acting_for_user_id == principal_id
    assert access.user_id == context.user.id
    assert access.role is Role.ENGINEER

    # The delegate's own role still gates the action: an engineer borrowing a
    # project manager's membership does not gain project-manager actions.
    with pytest.raises(ObjectPermissionDeniedError):
        service.authorize(
            context=context, project_id=project_id, action=Action.PROJECT_MEMBERS_MANAGE
        )


def test_delegation_to_a_non_member_principal_grants_nothing() -> None:
    context = auth_context(Role.ENGINEER)
    repository = StubProjectAccessRepository(
        member_ids=frozenset({uuid4()}),
        principals=(uuid4(),),
    )
    service = ProjectAccessService(repository)
    with pytest.raises(ObjectPermissionDeniedError):
        service.authorize(context=context, project_id=uuid4(), action=Action.WORK_ITEM_VIEW)


def test_direct_members_never_pay_the_delegation_lookup() -> None:
    context = auth_context(Role.ENGINEER)
    repository = StubProjectAccessRepository(is_member=True)
    repository.principals = ()
    service = ProjectAccessService(repository)
    access = service.authorize(context=context, project_id=uuid4(), action=Action.WORK_ITEM_VIEW)
    assert access.acting_for_user_id is None
