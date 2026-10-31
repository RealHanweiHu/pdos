"""Source carry proofs are re-derived; fixed history is not execution applicability."""

from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from pdos_next.agent_kernel.models import AgentRun
from pdos_next.enterprise_search import action_sources as carry
from pdos_next.errors import DomainError
from pdos_next.service import Context, digest

ROOT_READ = carry._root_read


@pytest.fixture
def case(monkeypatch):
    tenant, human, category, product, project, build, run_id = [uuid4() for _ in range(7)]
    ctx = Context(tenant, human, human, category_id=category)
    run = SimpleNamespace(
        id=run_id,
        tenant_id=tenant,
        requester_id=human,
        category_id=category,
        product_id=product,
        project_id=project,
        reverted_at=None,
        state="completed",
        read_sources=[],
        session_id=uuid4(),
    )
    product_row = SimpleNamespace(id=product, category_id=category)
    build_row = SimpleNamespace(
        id=build, product_id=product, project_id=project, revision=2, visibility="category"
    )
    state = SimpleNamespace(
        carried={},
        historical=set(),
        actual={},
        reads=[],
        private=False,
        source_calls=[],
        current_calls=[],
        preparations={},
    )
    session = SimpleNamespace(get=lambda model, identity: run if model is AgentRun else None)
    monkeypatch.setattr(carry, "_human", lambda *_args: None)
    monkeypatch.setattr(carry, "scope_for_run", lambda row: row.id)
    monkeypatch.setattr(carry, "require_access", lambda *_args, **_kwargs: product_row)
    monkeypatch.setattr(carry, "_build", lambda *_args: build_row)
    monkeypatch.setattr(carry, "_linked", lambda *_args, **_kwargs: (None, None, None, state.reads))
    monkeypatch.setattr(
        carry,
        "preparation_row",
        lambda _s, _c, _p, identity: (state.preparations[identity], build_row),
    )
    monkeypatch.setattr(carry, "preparation_snapshot", lambda _row: None)
    monkeypatch.setattr(
        carry.ledger, "carried", lambda *_args: (deepcopy(state.carried), state.historical)
    )

    def sources(_s, _c, _p, reads, refs):
        state.source_calls.append((deepcopy(reads), deepcopy(refs)))
        return {}, state.private

    def current(_s, selected, **kwargs):
        state.current_calls.append((deepcopy(selected), kwargs))
        values = {cid: deepcopy(state.actual[cid]) for cid in selected if cid in state.actual}
        return values, {cid: "source_unavailable" for cid in set(selected) - set(values)}

    monkeypatch.setattr(carry, "_sources", sources)
    monkeypatch.setattr(carry, "current", current)
    monkeypatch.setattr(
        carry,
        "_root_read",
        lambda _s, _r, cid, _item: {
            "origin_run_id": str(run.id),
            "origin_citation_id": cid,
            "read_proof": {
                "call_id": str(run.id),
                "tool": "assistant.search",
                "result_digest": "a" * 64,
                "citation_digest": digest(state.carried[cid]),
            },
        },
    )

    def source(kind="issue", *, private=False, customer=False, current_=True):
        cid, identity = str(uuid4()), str(uuid4())
        body = "方法依据\n压力保持十分钟"
        item = {
            "citation_id": cid,
            "source_type": kind,
            "source_id": identity,
            "source_revision": 3,
            "content_hash": digest(body),
            "category_id": str(category),
            "product_id": str(product),
            "private": private,
            "customer_original": customer,
            "is_current": current_,
            "locator": {"char_start": 0, "char_end": len(body)},
        }
        state.carried[cid] = item
        state.actual[cid] = {
            **deepcopy(item),
            "body": body,
            "updated": False,
            "read_basis_status": "current",
        }
        return cid

    def capture(ids, refs=(), preparation_id=None):
        return carry.capture(
            session,
            ctx,
            run,
            ids,
            product_id=product,
            build_id=build,
            execution_references=refs,
            preparation_id=preparation_id,
        )

    return SimpleNamespace(
        ctx=ctx,
        run=run,
        session=session,
        state=state,
        build=build_row,
        source=source,
        capture=capture,
    )


def test_history_is_a_fixed_discussion_identity_and_never_an_artifact_read(case):
    cid = case.source(current_=False)
    case.state.historical.add(cid)
    case.state.actual[cid].update(updated=True, read_basis_status="needs_recheck")
    proof = case.capture([cid, cid])
    assert len(proof["discussion_sources"]) == 1
    row = proof["discussion_sources"][0]
    assert row["source_type"] == "issue" and row["purpose"] == "historical_discussion"
    assert row["source_revision"] == 3 and row["origin_citation_id"] == cid
    assert row["locator"] == case.state.carried[cid]["locator"]
    assert proof["read_set"] == [] and proof["execution_references"] == []
    assert proof["applicability_status"] == "not_assessed"
    assert "is_current" not in row and "applicable" not in row
    assert case.state.current_calls[0][1] == {"allow_updated": {cid}}
    assert carry.recheck(case.session, case.ctx, case.run, proof) == proof


@pytest.mark.parametrize("kind", ["issue", "artifact", "knowledge"])
def test_displayed_sources_without_actual_carried_citation_are_rejected(case, kind):
    cid = case.source(kind)
    case.state.carried.pop(cid)
    with pytest.raises(DomainError, match="所选来源") as error:
        case.capture([cid])
    assert error.value.detail["reason_key"] == "assistant_action_citation_not_carried"


def test_current_read_revocation_prevents_reopening_and_confirmation(case):
    cid = case.source()
    proof = case.capture([cid])
    case.state.actual.clear()
    with pytest.raises(DomainError) as error:
        carry.recheck(case.session, case.ctx, case.run, proof)
    assert error.value.reason == "SOURCE_UNAVAILABLE"


@pytest.mark.parametrize(
    "patch",
    [
        {"tenant_id": uuid4()},
        {"requester_id": uuid4()},
        {"category_id": uuid4()},
        {"reverted_at": "recorded"},
        {"state": "cancelled"},
    ],
)
def test_actual_run_scope_and_state_are_rechecked_before_sources(case, patch):
    cid = case.source()
    for key, value in patch.items():
        setattr(case.run, key, value)
    with pytest.raises(DomainError) as error:
        case.capture([cid])
    assert error.value.detail["reason_key"] == "assistant_action_run_invalid"
    assert not case.state.current_calls


def test_model_or_agent_context_cannot_borrow_the_requesters_session(case):
    cid = case.source()
    ctx = Context(
        case.ctx.tenant_id, uuid4(), case.ctx.requester_id, category_id=case.ctx.category_id
    )
    with pytest.raises(DomainError):
        carry.capture(
            case.session,
            ctx,
            case.run,
            [cid],
            product_id=case.run.product_id,
            build_id=case.build.id,
        )


def test_customer_derived_and_private_sources_may_stay_in_a_real_private_target(case):
    cid = case.source(private=True, customer=True)
    case.build.visibility = "private"
    proof = case.capture([cid])
    assert proof["target"]["visibility"] == "private"
    assert proof["target"]["owner_id"] == str(case.ctx.requester_id)


def test_customer_original_derivation_cannot_enter_a_shared_category_target(case):
    cid = case.source(customer=True)
    with pytest.raises(DomainError) as error:
        case.capture([cid])
    assert error.value.detail["reason_key"] == "assistant_action_customer_original_shared"


def test_category_audience_uses_actual_same_restricted_roots_not_private_flag(case, monkeypatch):
    cid = case.source(private=True)
    same_root = {("products", str(case.run.product_id), str(uuid4()))}
    monkeypatch.setattr(carry, "_audience_roots", lambda *_args, **_kwargs: same_root)
    monkeypatch.setattr(carry, "_source_roots", lambda *_args: same_root)
    assert case.capture([cid])["target"]["visibility"] == "category"
    monkeypatch.setattr(
        carry,
        "_source_roots",
        lambda *_args: (
            same_root | {("artifact_versions", str(uuid4()), str(case.ctx.requester_id))}
        ),
    )
    with pytest.raises(DomainError) as error:
        case.capture([cid])
    assert error.value.detail["reason_key"] == "assistant_action_audience_widened"


def test_actual_owner_acl_allows_bounded_equal_or_narrower_targets_without_guessing_rosters(case):
    human, peer, other = case.ctx.requester_id, uuid4(), uuid4()
    target = ("products", str(uuid4()), str(human))
    source = ("artifact_versions", str(uuid4()), str(human))
    rosters = {target[1]: [peer], source[1]: [peer, other]}

    def scalars(statement):
        params = statement.compile().params
        assert params["owner_id_1"] == human
        return SimpleNamespace(all=lambda: rosters[str(params["subject_id_1"])])

    session = SimpleNamespace(scalars=scalars)
    assert carry._covers(session, case.ctx, {target}, {source})
    rosters[target[1]] = [other]
    rosters[source[1]] = [peer]
    assert not carry._covers(session, case.ctx, {target}, {source})
    # A recipient's one visible ACL row must never masquerade as the whole ACL.
    foreign_source = ("artifact_versions", str(uuid4()), str(peer))
    assert not carry._covers(session, case.ctx, {target}, {foreign_source})
    rosters[target[1]] = []
    assert carry._covers(session, case.ctx, {target}, {foreign_source})


def test_execution_reference_requires_pinned_actual_artifact_read_and_exact_line(case):
    history = case.source()
    cid = case.source("artifact")
    item = case.state.carried[cid]
    reference = {
        "artifact_id": item["source_id"],
        "expected_revision": 3,
        "line": 2,
        "quote": "压力保持十分钟",
    }
    with pytest.raises(DomainError) as error:
        case.capture([history], [reference])
    assert error.value.detail["reason_key"] == "assistant_action_execution_read_missing"
    case.run.read_sources = [{"artifact_id": item["source_id"], "expected_revision": 3}]
    proof = case.capture([history], [reference])
    assert proof["execution_references"] == [reference]
    assert proof["execution_sources"][0]["citation_id"] == cid
    assert proof["read_set"] == case.run.read_sources
    assert proof["discussion_sources"][0]["source_type"] == "issue"
    assert any(kwargs == {"with_body": True} for _selected, kwargs in case.state.current_calls)
    with pytest.raises(DomainError) as error:
        case.capture([history], [{**reference, "line": 1}])
    assert error.value.reason == "MISSING_REQUIRED_EVIDENCE"


def test_a_current_source_flag_does_not_replace_current_fixed_body_check(case):
    cid = case.source("artifact", current_=True)
    item = case.state.carried[cid]
    case.run.read_sources = [{"artifact_id": item["source_id"], "expected_revision": 3}]
    case.state.actual[cid]["body"] = "新版本不同原文"
    with pytest.raises(DomainError) as error:
        case.capture([], [{**case.run.read_sources[0], "line": 1, "quote": "压力保持十分钟"}])
    assert error.value.reason == "MISSING_REQUIRED_EVIDENCE"


def test_recomputed_digest_cannot_replace_a_fixed_identity_or_grant_applicability(case):
    proof = case.capture([case.source()])
    for key, value in (("applicability_status", "applicable"), ("run_id", str(uuid4()))):
        changed = deepcopy(proof)
        changed[key] = value
        changed["digest"] = digest({k: v for k, v in changed.items() if k != "digest"})
        with pytest.raises(DomainError) as error:
            carry.recheck(case.session, case.ctx, case.run, changed)
        assert error.value.detail["reason_key"] == "assistant_action_proof_changed"
    changed = deepcopy(proof)
    changed["discussion_sources"][0]["content_hash"] = "f" * 64
    changed["digest"] = digest({k: v for k, v in changed.items() if k != "digest"})
    with pytest.raises(DomainError):
        carry.recheck(case.session, case.ctx, case.run, changed)


def test_real_preparation_transition_binds_owner_revision_hash_and_is_repeatable(case):
    cid = case.source()
    proof = case.capture([cid])
    prep = SimpleNamespace(
        id=uuid4(),
        build_id=case.build.id,
        owner_id=case.ctx.requester_id,
        required_source_read_set=[],
        build_revision=case.build.revision,
        sources=[],
        visibility="category",
        revision=1,
        snapshot_sha256="e" * 64,
    )
    case.state.preparations[prep.id] = prep
    checked = carry.recheck(case.session, case.ctx, case.run, proof, preparation_id=prep.id)
    assert checked["target"]["preparation_id"] == str(prep.id)
    assert checked["target"]["preparation_revision"] == 1
    assert checked["target"]["preparation_sha256"] == prep.snapshot_sha256
    assert carry.recheck(case.session, case.ctx, case.run, checked) == checked
    prep.snapshot_sha256 = "f" * 64
    with pytest.raises(DomainError):
        carry.recheck(case.session, case.ctx, case.run, checked)


def test_existing_preparation_cannot_borrow_another_owners_audience(case):
    prep = SimpleNamespace(
        id=uuid4(), build_id=case.build.id, owner_id=uuid4(), visibility="private"
    )
    case.state.preparations[prep.id] = prep
    with pytest.raises(DomainError) as error:
        case.capture([case.source()], preparation_id=prep.id)
    assert error.value.detail["reason_key"] == "assistant_action_target_owner_invalid"


def test_shared_preparation_keeps_its_actual_owner_and_does_not_require_private_ownership(case):
    prep = SimpleNamespace(
        id=uuid4(),
        build_id=case.build.id,
        build_revision=case.build.revision,
        owner_id=uuid4(),
        required_source_read_set=[],
        sources=[],
        visibility="category",
        revision=1,
        snapshot_sha256="e" * 64,
    )
    case.state.preparations[prep.id] = prep
    proof = case.capture([case.source()], preparation_id=prep.id)
    assert proof["target"]["owner_id"] == str(prep.owner_id)


def test_frozen_target_changes_and_definition_reference_changes_require_a_new_candidate(case):
    cid = case.source()
    proof = case.capture([cid])
    case.build.revision += 1
    with pytest.raises(DomainError) as error:
        carry.recheck(case.session, case.ctx, case.run, proof)
    assert error.value.detail["reason_key"] == "assistant_action_proof_changed"
    prep = SimpleNamespace(
        id=uuid4(),
        build_id=case.build.id,
        build_revision=case.build.revision - 1,
        owner_id=case.ctx.requester_id,
        sources=[],
        visibility="category",
    )
    case.state.preparations[prep.id] = prep
    with pytest.raises(DomainError) as error:
        case.capture([cid], preparation_id=prep.id)
    assert error.value.reason == "SOURCE_CHANGED"
    prep.build_revision = case.build.revision
    prep.sources = [
        {"artifact_id": str(uuid4()), "expected_revision": 1, "line": 1, "quote": "另一份执行定义"}
    ]
    with pytest.raises(DomainError) as error:
        case.capture([cid], preparation_id=prep.id)
    assert error.value.reason == "SOURCE_CHANGED"


def test_proof_shape_and_version_are_closed_even_with_a_recomputed_digest(case):
    proof = case.capture([case.source()])
    for patch in ({"version": True}, {"model_audience": "category"}):
        changed = {**deepcopy(proof), **patch}
        changed["digest"] = digest({k: v for k, v in changed.items() if k != "digest"})
        with pytest.raises(DomainError) as error:
            carry.recheck(case.session, case.ctx, case.run, changed)
        assert error.value.detail["reason_key"] == "assistant_action_proof_changed"


class Rows:
    def __init__(self, value):
        self.value = value

    def mappings(self):
        return self

    def one_or_none(self):
        return self.value


def test_audience_dependency_graph_uses_actual_rows_including_original_and_fixed_parents(case):
    ctx = case.ctx
    ids = {key: uuid4() for key in ("issue", "build", "artifact", "original", "configuration")}
    product = str(case.run.product_id)
    rows = {
        ("quality_issue_versions", ids["issue"]): {
            "id": ids["issue"],
            "tenant_id": ctx.tenant_id,
            "category_id": ctx.category_id,
            "owner_id": ctx.requester_id,
            "visibility": "category",
            "product_id": product,
            "audience_dependencies": [{"type": "builds", "id": str(ids["build"])}],
            "required_source_read_set": [{"artifact_id": str(ids["artifact"])}],
        },
        ("builds", ids["build"]): {
            "id": ids["build"],
            "category_id": ctx.category_id,
            "owner_id": ctx.requester_id,
            "visibility": "audience",
            "audience_dependencies": [
                {"type": "engineering_configurations", "id": str(ids["configuration"])}
            ],
        },
        ("engineering_configurations", ids["configuration"]): {
            "id": ids["configuration"],
            "category_id": ctx.category_id,
            "visibility": "category",
            "owner_id": ctx.requester_id,
        },
        ("artifact_versions", ids["artifact"]): {
            "id": ids["artifact"],
            "category_id": ctx.category_id,
            "visibility": "category",
            "original_id": ids["original"],
        },
        ("uploaded_originals", ids["original"]): {
            "id": ids["original"],
            "category_id": ctx.category_id,
            "owner_id": ctx.requester_id,
            "visibility": "private",
        },
        ("products", UUID(product)): {
            "id": UUID(product),
            "category_id": ctx.category_id,
            "owner_id": ctx.requester_id,
            "visibility": "category",
        },
    }
    touched = []

    def execute(statement):
        compiled = statement.compile()
        key = (statement.get_final_froms()[0].name, compiled.params["id_1"])
        touched.append(key)
        assert compiled.params["tenant_id_1"] == ctx.tenant_id
        return Rows(rows.get(key))

    actual = carry._audience_roots(
        SimpleNamespace(execute=execute), ctx, "quality_issue_versions", ids["issue"]
    )
    assert actual == {
        ("builds", str(ids["build"]), str(ctx.requester_id)),
        ("uploaded_originals", str(ids["original"]), str(ctx.requester_id)),
    }
    assert ("engineering_configurations", ids["configuration"]) in touched
    rows.pop(("uploaded_originals", ids["original"]))
    with pytest.raises(DomainError):
        carry._audience_roots(
            SimpleNamespace(execute=execute), ctx, "quality_issue_versions", ids["issue"]
        )


def test_root_proof_is_the_completed_signed_search_result_not_display_metadata(case, monkeypatch):
    item = deepcopy(case.state.carried[case.source()])
    call = SimpleNamespace(id=uuid4(), tool="assistant.search", result={"items": []})
    item["citation_id"] = carry.ledger.citation_id(case.run.id, call.id, item)
    call.result["items"] = [item]
    inherited = {
        **deepcopy(item),
        "origin_run_id": str(case.run.id),
        "origin_citation_id": item["citation_id"],
        "citation_id": str(uuid4()),
    }
    monkeypatch.setattr(carry.ledger, "completed", lambda *_args, **_kwargs: [(call, {})])
    result = ROOT_READ(case.session, case.run, inherited["citation_id"], inherited)
    assert result["origin_run_id"] == str(case.run.id)
    assert result["read_proof"]["result_digest"] == digest(call.result)
    assert result["read_proof"]["call_id"] == str(call.id)
    inherited["content_hash"] = "f" * 64
    with pytest.raises(DomainError):
        ROOT_READ(case.session, case.run, inherited["citation_id"], inherited)
