"""No-DB query, fixed-source and rendering tests; native PG cases are separate."""

from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest
from quality_issues.helpers import NOW, Harness, source, uid
from sqlalchemy import Engine
from sqlalchemy.dialects.postgresql import dialect

from pdos_next import personal_summary
from pdos_next import personal_summary_quality as quality
from pdos_next import personal_summary_runtime as runtime
from pdos_next import personal_summary_templates as templates
from pdos_next.errors import DomainError
from pdos_next.personal_summary_schemas import Selection
from pdos_next.schemas.quality_issues.contracts import CapaDraft, IssueTriage
from pdos_next.service import Context, digest


@pytest.fixture(autouse=True)
def no_database(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("pure summary checks cannot connect to PostgreSQL")

    monkeypatch.setattr(Engine, "connect", forbidden)
    monkeypatch.setattr(Engine, "raw_connection", forbidden)


def case(*, executor=None, due=True):
    h = Harness()
    identity = h.create().subject_id
    h.call("quality.issue.triage", identity, 1, IssueTriage(reason="Synthetic named triage"))
    issue = h.issue(identity)
    h.call(
        "quality.capa.draft",
        identity,
        2,
        CapaDraft(
            capa_id=uid("capa"),
            hypotheses=[{"text": "Tentative", "sources": [source("hypothesis")]}],
            actions=[
                {
                    "id": uid("corrective"),
                    "kind": "corrective",
                    "text": "Actual named work",
                    "executor_id": executor or uid("executor"),
                }
            ],
            requirement={
                "method": "Separate evidence",
                "acceptance": "Fixed pairs pass",
                "observation_until": NOW + timedelta(hours=-1 if due else 1),
                "required_failure_ids": [f.identity for f in issue.failures],
            },
        ),
    )
    issue = h.issue(identity)
    ctx = Context(issue.scope.tenant_id, uid("executor"), uid("executor"))
    body = issue.model_dump(mode="json")
    row = NS(
        id=uuid4(),
        tenant_id=ctx.tenant_id,
        category_id=uuid4(),
        product_id=issue.scope.product_id,
        project_id=issue.scope.project_id,
        issue_id=issue.id,
        revision=issue.revision,
        status=issue.status,
        issue_snapshot=body,
        snapshot_sha256=digest(body),
        created_at=NOW,
        owner_id=uuid4(),
        writer_id=uuid4(),
    )
    return ctx, row, issue


def sql(query):
    return str(query.compile(dialect=dialect(), compile_kwargs={"literal_binds": True}))


def test_current_issue_query_binds_full_identity_native_duty_and_explicit_scope():
    ctx, row, _ = case()
    selection = Selection(category_ids=(row.category_id,), followed_project_ids=(row.project_id,))
    query = sql(
        quality.query(ctx, selection, NOW, "quality_issue_opened", product_id=row.product_id)
    )
    for key in ("tenant_id", "category_id", "product_id", "project_id", "issue_id"):
        assert f"quality_issue_versions.{key} = quality_current_issues.{key}" in query
    assert "quality_issue_versions.id = quality_current_issues.issue_version_id" in query
    assert "quality_issue_versions.revision = quality_current_issues.issue_revision" in query
    assert str(ctx.requester_id) in query and str(row.category_id) in query
    assert str(row.product_id) in query and str(row.project_id) in query
    assert "professional_authority_current" in query and "kind = 'duty'" in query
    assert "state = 'active'" in query and "valid_until >" in query
    assert "fact_revision" in query and "jsonb_path_exists" in query
    assert "SECURITY DEFINER" not in query
    assert "visibility != 'private'" in query
    assert f"quality_issue_versions.owner_id = '{ctx.requester_id}'" in query


def test_capa_due_query_has_only_registered_observation_clock_and_actual_executor():
    ctx, row, _ = case()
    query = sql(quality.query(ctx, Selection(groups=("action",)), NOW, "capa_observation_due"))
    assert "observation_until" in query and "TIMESTAMP WITH TIME ZONE" in query
    assert "executor_id" in query and "completion == null" in query
    assert "effectiveness" in query and "effective" in query
    assert "recorded_by" not in query and "shared" not in query


def test_new_issue_uses_same_fixed_snapshot_history_and_does_not_make_recorder_responsible():
    ctx, row, issue = case()
    (first,) = quality.items(row, True, ctx, NOW, "quality_issue_opened", Selection())
    value = personal_summary.compose(ctx, Selection(), NOW, [first], [])
    item = value.groups[2].items[0]
    assert item.object.id == issue.id and item.object.version_id == row.id
    assert item.object.revision == row.revision
    assert item.next_step.responsible is None and item.next_step.recorded_by is None
    assert item.facts["opened_at_as_recorded"] == issue.history[0].at.isoformat()
    assert item.health is None and "首次列入" in item.change.text
    again = personal_summary.compose(
        ctx, Selection(), NOW + timedelta(days=1), [first], [], previous=value.baseline
    )
    assert again.groups[2].unchanged_items[0].change.kind == "unchanged"


def test_due_capa_names_only_actual_pending_executor_not_the_issue_owner_or_reviewer():
    ctx, row, issue = case()
    (item,) = quality.items(row, True, ctx, NOW, "capa_observation_due", Selection())
    assert item["group"] == "action" and item["next_step"].responsible.id == ctx.requester_id
    assert item["next_step"].responsible.id != row.owner_id
    assert (
        item["facts"]["observation_until_as_recorded"]
        == issue.capa.requirement.observation_until.isoformat()
    )
    assert item["facts"]["action_due_at_as_recorded"] is None
    assert "观察截止不是措施完成期限" in item["next_step"].text
    assert item["facts"]["effectiveness_as_recorded"] is None


def test_subscriber_or_quality_duty_does_not_become_next_verification_responsible():
    ctx, row, _ = case(executor=uuid4())
    (item,) = quality.items(row, True, ctx, NOW, "capa_observation_due", Selection())
    assert item["group"] == "following" and item["next_step"].responsible is None
    assert item["relationship"].kind == "current_quality_duty"
    assert "复核责任人未单独登记" in item["next_step"].text
    (subscribed,) = quality.items(row, False, ctx, NOW, "capa_observation_due", Selection())
    assert subscribed["relationship"].kind == "subscriber"


def test_future_observation_clock_is_not_due_and_missing_open_date_is_not_filled():
    ctx, row, issue = case(due=False)
    assert quality.items(row, True, ctx, NOW, "capa_observation_due", Selection()) == []
    row.issue_snapshot = {**row.issue_snapshot, "history": []}
    row.snapshot_sha256 = digest(row.issue_snapshot)
    (item,) = quality.items(row, True, ctx, NOW, "quality_issue_opened", Selection())
    assert item["facts"]["opened_at_as_recorded"] is None
    assert item["next_step"].responsible is None


def test_corrupt_fixed_snapshot_is_rejected_and_unsubscribed_sources_are_not_read():
    ctx, row, _ = case()
    row.issue_snapshot = deepcopy(row.issue_snapshot)
    row.issue_snapshot["title"] = "Forged changed body"
    with pytest.raises(DomainError) as error:
        quality.items(row, True, ctx, NOW, "quality_issue_opened", Selection())
    assert error.value.reason == "INTEGRITY_MISMATCH"

    class NoRead:
        def execute(self, *_args):
            raise AssertionError("unsubscribed source must not be read")

    assert quality.read(
        NoRead(),
        ctx,
        Selection(
            excluded_kinds=(
                "quality_issue_opened",
                "capa_observation_due",
            )
        ),
        NOW,
    ) == ([], [])


@pytest.mark.parametrize(
    ("role", "duties", "manager", "expected"),
    [
        ("management", ("quality",), True, "management"),
        ("supply", (), False, "supply"),
        ("quality", (), False, "quality"),
        ("engineering", (), False, "general"),
        (None, ("quality",), False, "quality"),
        (None, ("engineering",), False, None),
        (None, (), True, "product"),
        (None, ("quality",), True, None),
        (None, (), False, None),
    ],
)
def test_server_role_defaults_are_explicit_or_current_native_duties_never_guessed(
    role,
    duties,
    manager,
    expected,
):
    assert templates.choose(role, duties, project_manager=manager)[0] == expected


def test_templates_only_use_existing_selection_filters_without_new_authority_fields():
    before = Selection().model_dump(mode="json")
    for template in templates.TEMPLATES:
        choice = Selection(
            groups=template["groups"],
            excluded_kinds=[k for k in templates.KINDS if k not in template["kinds"]],
        )
        assert set(choice.model_dump(mode="json")) == set(before)
    assert "quality_issue" in runtime._source_models()
    (model,) = runtime._source_models()["quality_issue"]
    assert runtime._source_key(model).key == "issue_id"


def test_template_options_query_rejects_identity_and_role_fields():
    from pydantic import ValidationError

    from pdos_next.personal_summary_delivery import OptionsQuery

    category = uuid4()
    assert OptionsQuery(category_id=category).product_id is None
    for key in ("owner_id", "principal_id", "role", "grant_id"):
        with pytest.raises(ValidationError):
            OptionsQuery.model_validate({"category_id": category, key: "quality"})


def test_quality_history_readback_keeps_exact_version_and_never_substitutes_latest():
    ctx, row, _ = case()
    (item,) = quality.items(row, True, ctx, NOW, "capa_observation_due", Selection())
    source = item["object"]
    binding = NS(tenant_id=ctx.tenant_id, requester_id=ctx.requester_id,
                 category_id=row.category_id, product_id=row.product_id)
    metadata = {
        "id": row.id,
        "source_id": row.issue_id,
        "category_id": row.category_id,
        "product_id": row.product_id,
        "project_id": row.project_id,
        "revision": row.revision,
    }

    class Metadata:
        def __init__(self):
            self.rows, self.queries = [metadata], []

        def execute(self, query):
            self.queries.append(query)
            return NS(mappings=lambda: NS(all=lambda: self.rows))

    session = Metadata()
    assert runtime._readable_sources(session, binding, {source}) == {source}
    query = sql(session.queries[-1])
    assert "quality_issue_versions" in query and str(row.id) in query
    assert "issue_snapshot" not in query and "snapshot_sha256" not in query
    session.rows = [{**metadata, "id": uuid4(), "revision": row.revision + 1}]
    assert runtime._readable_sources(session, binding, {source}) == set()
    session.rows = []
    assert runtime._readable_sources(session, binding, {source}) == set()


def test_template_read_uses_ordinary_human_saved_role_and_current_scope_only():
    from pdos_next.models import Category, Principal, Product

    tenant, owner, category, product = (uuid4() for _ in range(4))
    ctx = Context(tenant, owner, owner)

    class OwnRead:
        info = {"scope": (tenant, owner, owner, None), "read_snapshot": True}

        def __init__(self):
            self.results = iter((NOW, NS(body={"role": "management"}), None, None))
            self.queries = []

        def get(self, model, identity):
            if model is Principal:
                assert identity == owner
                return NS(id=owner, tenant_id=tenant, active=True, kind="human")
            assert model in {Category, Product}
            return NS(id=identity, tenant_id=tenant, category_id=category)

        def scalar(self, query):
            self.queries.append(query)
            return next(self.results)

        def scalars(self, query):
            self.queries.append(query)
            return ["quality"]

    session = OwnRead()
    value = templates.read(session, ctx, category, product)
    assert value["principal_id"] == str(owner) and value["category_id"] == str(category)
    assert value["product_id"] == str(product) and value["default_template"] == "management"
    assert value["basis"]["saved_role"] == "management"
    assert value["basis"]["current_duty_roles"] == ["quality"]
    query = "\n".join(sql(q) for q in session.queries)
    assert "kind = 'duty'" in query and "state = 'active'" in query
    assert str(owner) in query and str(category) in query and str(product) in query
