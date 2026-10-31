"""Actual guard SQL shape and ACL boundary without PostgreSQL, transport or credentials."""

from types import SimpleNamespace as NS
from uuid import uuid4

import pytest
from migrations.candidates.dingtalk_fence import DOWNGRADE_SQL, SCHEMA_SQL
from pdos_next.dingtalk.guards import message_binding
from pdos_next.dingtalk.models import Binding
from pdos_next.errors import DomainError
from pdos_next.models import Principal


class MetadataSession:
    """Represent the diagnosed RLS: service SELECT works, FOR UPDATE returns no row."""

    def __init__(self):
        self.message = NS(id=uuid4(), tenant_id=uuid4(), application_id=uuid4(),
                          binding_id=uuid4(), owner_id=uuid4(), binding_epoch=1)
        self.app = NS(id=self.message.application_id, active=True, service_principal_id=uuid4())
        self.binding = NS(id=self.message.binding_id, active=True, epoch=1,
                          owner_id=self.message.owner_id, application_id=self.app.id,
                          tenant_id=self.message.tenant_id)
        self.people = {
            self.message.owner_id: NS(active=True, kind="human"),
            self.app.service_principal_id: NS(active=True, kind="agent"),
        }
        self.calls, self.queries = [], []

    def execute(self, query, values):
        self.calls.append((str(query), values))

    def scalar(self, query):
        self.queries.append(query)
        if query._for_update_arg is not None:
            return None
        model = query.column_descriptions[0]["entity"]
        return self.binding if model is Binding else self.app

    def get(self, model, identity):
        assert model is Principal
        return self.people.get(identity)


def test_service_lock_uses_bounded_helper_then_refreshed_ordinary_rls_reads():
    session = MetadataSession()
    assert message_binding(session, session.message, lock=True) == (session.app, session.binding)
    assert session.calls == [
        ("SELECT dingtalk_lock_message_binding(:tenant,:message)",
         {"tenant": session.message.tenant_id, "message": session.message.id})
    ]
    assert len(session.queries) == 2
    assert all(query._for_update_arg is None for query in session.queries)
    assert all(query.get_execution_options()["populate_existing"] for query in session.queries)


def test_readonly_guard_does_not_lock_or_call_internal_fence():
    session = MetadataSession()
    assert message_binding(session, session.message) == (session.app, session.binding)
    assert not session.calls
    assert all(not query.get_execution_options() for query in session.queries)


@pytest.mark.parametrize("target", ["app", "binding"])
def test_after_waiting_actual_disable_or_revoke_still_cancels(target):
    session = MetadataSession()
    getattr(session, target).active = False
    with pytest.raises(DomainError) as error:
        message_binding(session, session.message, lock=True)
    assert error.value.reason == "CANCELLED_RUN"
    assert len(session.calls) == 1


def test_helper_only_locks_actual_message_metadata_with_exact_scope_and_acl():
    joined = "\n".join(SCHEMA_SQL)
    function = next(sql for sql in SCHEMA_SQL if sql.startswith("CREATE FUNCTION"))
    assert "RETURNS void" in function and "SET search_path=pg_catalog,public,pg_temp" in function
    assert "scope_actor() IS DISTINCT FROM public.scope_requester()" in function
    assert "m.tenant_id=t AND m.id=mid" in function
    assert function.index("dingtalk_applications a") < function.index("dingtalk_account_bindings b")
    assert function.count("public.dingtalk_service(t,app_id) IS NOT TRUE") == 2
    assert "FOR UPDATE" in function
    assert all(word not in function for word in ("INSERT ", "DELETE ", "UPDATE public.", "payload"))
    assert "GRANT UPDATE(id)" in joined and "CREATE POLICY" not in joined
    owner = joined.index("OWNER TO pdos_next_dingtalk_maintenance")
    assert owner < joined.index("TO pdos_next_owner")
    assert sum(sql.endswith("TO pdos_next_app;") for sql in SCHEMA_SQL) == 1
    assert SCHEMA_SQL[-1].startswith("REVOKE CREATE ON SCHEMA")
    assert "FROM PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch" in joined
    assert len(DOWNGRADE_SQL) == 3 and DOWNGRADE_SQL[0].startswith("DROP FUNCTION")
    assert all("UPDATE(id)" in sql for sql in DOWNGRADE_SQL[1:])
