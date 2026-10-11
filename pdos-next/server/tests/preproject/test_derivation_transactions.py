"""HTTP derivation/G0 transactions with explicitly synthetic published baselines.

Only the parent publication fixture uses the administrative owner. No publication
API or model is invoked; all child creation, approval and attacks use app roles.
"""
# ruff: noqa: F811 -- pytest injects the explicitly re-exported shared fixture

from contextlib import contextmanager
from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pdos_next.database import tenant_session
from pdos_next.domain.preproject.baseline import (
    publication_digest,
    published_baseline,
    read_baseline,
)
from pdos_next.domain.preproject.models import Proposal, ProposalDecision, ProposalSubmission
from pdos_next.domain.products.definitions import definition_view
from pdos_next.domain.products.models import DefinitionRevision, DefinitionSource, DefinitionSpecRow
from pdos_next.domain.products.variant_models import Variant, VariantRevision
from pdos_next.domain.projects.models import Project, ProjectProductLink
from pdos_next.errors import DomainError
from pdos_next.models import (
    Artifact,
    Category,
    Claim,
    Confirmation,
    Consumption,
    Grant,
    ObjectAudience,
    Product,
    Receipt,
)
from pdos_next.service import Context, digest
from tests.preproject.test_evidence_commands_pg import (
    artifact,
    record_claim,
    share_request,
    withdraw_request,
)
from tests.preproject.test_g0 import (
    create,
    decide_request,
    payload,
    post,
    read,
    request,
    save,
    submit,
)
from tests.preproject.test_g0 import work as work
from tests.preproject.test_material_proofs_pg import assert_check_violation, human_session

PARENT_QUOTE = "仅父来源保留的合成逐字原文"


@contextmanager
def synthetic_owner(work):
    with tenant_session(
        work.admin,
        work.tenant,
        actor_id=work.human,
        requester_id=work.human,
        category_id=work.category,
    ) as session:
        session.execute(text("SET LOCAL ROLE pdos_next_owner"))
        yield session


def base_specs():
    return [
        {
            "key": "parent_number",
            "value_type": "number",
            "value": Decimal("12.345678901234"),
            "unit": "V",
        },
        {
            "key": "parent_range",
            "value_type": "range",
            "lower": Decimal("0.100000000001"),
            "upper": Decimal("9.999999999999"),
            "unit": "A",
        },
        {"key": "parent_text", "value_type": "text", "text": "合成外壳"},
        {"key": "parent_boolean", "value_type": "boolean", "text": "false"},
        {"key": "parent_enum", "value_type": "enum", "text": "低功耗"},
        {
            "key": "parent_unknown",
            "value_type": "number",
            "availability": "unknown",
            "item_status": "unknown",
        },
    ]


def synthetic_parent(
    work,
    *,
    revision=1,
    status="published",
    private=False,
    product_id=None,
    artifact_source=None,
    spec_source_refs=None,
    spec_values=None,
):
    """Assemble an unsealed draft, compute actual content, then attach synthetic publication."""
    product_id = product_id or work.product
    identity = uuid4()
    with synthetic_owner(work) as session:
        # Represent a pre-0753 stored publication, including the deliberately
        # inconsistent historic source cases below. The migration backfills
        # these rows without treating them as newly authorized draft commands.
        # Only this owner-only fixture skips the new creation-receipt trigger;
        # existing scope, immutability, lifecycle and Current guards still run.
        legacy_atom = session.scalar(
            text(
                "SELECT EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid='definition_specs'::regclass "
                "AND tgname='definition_item_atom' AND NOT tgisinternal)"
            )
        )
        if legacy_atom:
            assert session.scalar(text("SELECT current_user")) == "pdos_next_owner"
            session.execute(
                text("ALTER TABLE definition_specs DISABLE TRIGGER definition_item_atom")
            )
        product = session.get(Product, product_id)
        if private and product.visibility != "private":
            product.visibility = "private"
            session.add(
                ObjectAudience(
                    tenant_id=work.tenant,
                    category_id=work.category,
                    object_type="products",
                    subject_id=product_id,
                    owner_id=work.human,
                    principal_id=work.peer,
                )
            )
        row = DefinitionRevision(
            id=identity,
            tenant_id=work.tenant,
            category_id=work.category,
            product_id=product_id,
            owner_id=work.human,
            revision=revision,
            title=f"合成发布父版 {revision}",
            purpose="合成派生基线",
            status="draft",
            sealed=status == "sealed_draft",
            visibility="private" if private else "category",
            use_cases=["合成使用场景"],
            requirements=[],
            constraints=[],
            unknowns=[],
            exclusions=[],
            change_reason="Synthetic published-baseline fixture; no real publication qualification",
        )
        session.add(row)
        session.flush()
        # A legacy sealed draft is inserted complete and empty. Its child
        # rows cannot be appended after sealing, even by the fixture owner.
        specs = (
            []
            if status == "sealed_draft"
            else (base_specs() if spec_values is None else spec_values)
        )
        for spec in specs:
            values = {
                "parameter": spec["key"],
                "availability": "known",
                "unit": None,
                "test_conditions": ["25 °C", "静态工况"],
                "method": "合成检查方法",
                "acceptance_criterion": "合成验收口径",
                "nature": "extracted",
                "state": "proposed",
                "owner_id": work.human,
                "reason": "合成父规格",
                "item_status": "confirmed",
                "condition_note": "父定义的结构化工况",
                "modality": "should",
                "exceptions": [{"condition": "合成例外"}],
                "applicable_variants": [],
                "origin": "human",
                "writer_id": work.human,
                "confirmed_by": (
                    work.human if spec.get("availability", "known") == "known" else None
                ),
                "source_refs": deepcopy(spec_source_refs)
                if spec_source_refs is not None
                else [
                    {
                        "type": "human",
                        "id": str(work.human),
                        "version": 1,
                        "statement": PARENT_QUOTE,
                    }
                ],
                **spec,
            }
            session.add(
                DefinitionSpecRow(
                    tenant_id=work.tenant,
                    category_id=work.category,
                    product_id=product_id,
                    definition_id=row.id,
                    **values,
                )
            )
        if legacy_atom:
            session.flush()
            # Execute the old deferred guard before changing trigger metadata.
            # A failed flush rolls back this whole transaction, including DDL,
            # without masking its error with an ALTER in an aborted transaction.
            session.execute(text("SET CONSTRAINTS m3_variant_lifecycle IMMEDIATE"))
            session.execute(
                text("ALTER TABLE definition_specs ENABLE TRIGGER definition_item_atom")
            )
            session.execute(text("SET CONSTRAINTS m3_variant_lifecycle DEFERRED"))
        if artifact_source is not None:
            source = session.get(Artifact, artifact_source)
            assert source.status == "active" and source.revision == 1
            session.add(
                DefinitionSource(
                    tenant_id=work.tenant,
                    category_id=work.category,
                    product_id=product_id,
                    definition_id=row.id,
                    artifact_id=source.id,
                    source_revision=source.revision,
                    line=1,
                    quote=source.content.splitlines()[0],
                    spec_keys=["parent_number"],
                )
            )
        if private:
            session.add(
                ObjectAudience(
                    tenant_id=work.tenant,
                    category_id=work.category,
                    object_type="definition_revisions",
                    subject_id=row.id,
                    owner_id=work.human,
                    principal_id=work.peer,
                )
            )
        session.flush()
        ctx = Context(work.tenant, work.human, work.human, category_id=work.category)
        content_digest = publication_digest(definition_view(session, ctx, row))
        receipt_id = None
        if status == "published":
            receipt_id = uuid4()
            session.add(
                Receipt(
                    id=receipt_id,
                    tenant_id=work.tenant,
                    category_id=work.category,
                    product_id=product_id,
                    command_id=uuid4(),
                    actor_id=work.human,
                    requester_id=work.human,
                    operation="product.definition.publish",
                    subject_type="definition_revision",
                    subject_id=row.id,
                    subject_revision=revision,
                    visibility=row.visibility,
                    request_digest=digest(str(uuid4())),
                    intent_digest=digest(str(uuid4())),
                    result={"definition_digest": content_digest, "synthetic": True},
                )
            )
            session.flush()
            if private:
                session.add(
                    ObjectAudience(
                        tenant_id=work.tenant,
                        category_id=work.category,
                        object_type="action_receipts",
                        subject_id=receipt_id,
                        owner_id=work.human,
                        principal_id=work.peer,
                    )
                )
            row.status, row.publication_receipt_id, row.sealed = "published", receipt_id, True
    return SimpleNamespace(
        id=identity,
        product_id=product_id,
        revision=revision,
        receipt_id=receipt_id,
        digest=content_digest,
    )


def derivative_payload(work, parent, target_kind="new_product", *, explicit_id=True):
    data = payload(work)
    data.update(
        title="合成派生方案",
        entry_kind="derivative",
        target_kind=target_kind,
        baseline_product_id=str(parent.product_id),
        baseline_definition_revision=parent.revision,
    )
    if explicit_id:
        data["baseline_definition_id"] = str(parent.id)
    return data


def baseline(work, product_id=None):
    with human_session(work) as session:
        return read_baseline(
            session,
            Context(work.tenant, work.human, work.human, category_id=work.category),
            product_id or work.product,
        )


@contextmanager
def reviewer_session(work):
    with tenant_session(
        work.engine, work.tenant, actor_id=work.peer, category_id=work.category
    ) as session:
        yield session


def proof_id(work, command):
    with reviewer_session(work) as session:
        identity = session.scalar(
            select(Confirmation.id).where(
                Confirmation.token_hash == digest(command["payload"]["approval_token"])
            )
        )
        assert identity is not None
        return identity


def proof_consumed(work, identity):
    with reviewer_session(work) as session:
        row = session.get(Confirmation, identity)
        assert row is not None
        return row.consumed


def inherited_specs(document):
    return {
        i["content"]["key"]: i
        for i in document["items"]
        if i["kind"] == "spec" and i["content"]["key"].startswith("parent_")
    }


def assert_inherited(document, parent, work):
    specs = inherited_specs(document)
    assert set(specs) == {s["key"] for s in base_specs()}
    for original in base_specs():
        item, content = specs[original["key"]], specs[original["key"]]["content"]
        assert content["value_type"] == original["value_type"]
        assert content["availability"] == original.get("availability", "known")
        assert content["item_status"] == "unknown"
        assert content["test_conditions"] == ["25 °C", "静态工况"]
        assert item["origin"] == "human" and item["writer_id"] == str(work.human)
        assert item["confirmed_by"] is None and item["run_id"] is None
        assert len(item["source_refs"]) == 1
        ref = item["source_refs"][0]
        assert (ref["type"], ref["id"], ref["version"]) == (
            "definition",
            str(parent.id),
            parent.revision,
        )
        assert ref.get("quote") is None and ref["statement"] == f"specs/{original['key']}"
        for field in ("value", "lower", "upper"):
            if field in original:
                assert Decimal(str(content[field])) == original[field]
        if "text" in original:
            assert content["text_value"] == original["text"]
    assert PARENT_QUOTE not in str(specs)
    return specs


@pytest.mark.parametrize("explicit_id", [False, True])
def test_derivative_create_inherits_fixed_full_specs_without_parent_confirmation(work, explicit_id):
    parent = synthetic_parent(work)
    view = baseline(work)
    assert view["derivation_eligible"] is True and view["baseline_kind"] == "published"
    assert view["definition"]["publication"]["synthetic"] is True
    proposal_id, command = create(work, derivative_payload(work, parent, explicit_id=explicit_id))
    assert post(work, command).json()["subject_id"] == proposal_id
    assert_inherited(read(work, proposal_id).json(), parent, work)
    with human_session(work) as session:
        row = session.get(Proposal, UUID(proposal_id))
        assert row.baseline_definition_id == parent.id and row.baseline_definition_revision == 1


def test_explicit_child_spec_overrides_only_its_fixed_parent_key(work):
    parent = synthetic_parent(work)
    data = derivative_payload(work, parent)
    override = {
        "kind": "spec",
        "content": {
            "key": "parent_number",
            "parameter": "派生电压",
            "value_type": "number",
            "value": "99.000000000001",
            "unit": "V",
            "availability": "known",
            "item_status": "confirmed",
        },
        "source_refs": [
            {
                "type": "human",
                "id": str(work.human),
                "version": 1,
                "statement": "本次派生的具名规格决定",
            }
        ],
    }
    data["groups"]["items"].append(override)
    proposal_id, _ = create(work, data)
    document = read(work, proposal_id).json()
    specs = inherited_specs(document)
    assert len([i for i in document["items"] if i["kind"] == "spec"]) == 8
    assert set(specs) == {s["key"] for s in base_specs()}
    explicit = specs.pop("parent_number")
    assert Decimal(explicit["content"]["value"]) == Decimal("99.000000000001")
    assert explicit["content"]["item_status"] == "confirmed"
    assert explicit["source_refs"][0]["type"] == "human"
    assert explicit["source_refs"][0]["statement"] == "本次派生的具名规格决定"
    for item in specs.values():
        assert item["content"]["item_status"] == "unknown"
        assert item["source_refs"][0]["id"] == str(parent.id)
        assert item["source_refs"][0]["version"] == 1


@pytest.mark.parametrize("state", ["draft", "sealed_draft"])
def test_unpublished_draft_or_sealed_definition_is_not_a_published_parent(work, state):
    parent = synthetic_parent(work, status=state)
    view = baseline(work)
    assert view["derivation_eligible"] is False and view["baseline_kind"] == "draft"
    denied = post(
        work, request(work, "proposal.create", derivative_payload(work, parent)), preview=True
    )
    assert denied.status_code == 409, denied.text
    assert denied.json()["detail"]["reason"] == "baseline_not_published"


def test_real_sealed_g0_first_definition_does_not_become_published_baseline(work):
    proposal_id, _ = create(work)
    submit(work, proposal_id)
    approved, _ = save(work, decide_request(work, proposal_id), actor=work.peer)
    product_id = UUID(approved["result"]["product_id"])
    view = baseline(work, product_id)
    assert view["baseline_kind"] == "g0" and view["derivation_eligible"] is False
    parent = SimpleNamespace(
        product_id=product_id, id=UUID(approved["result"]["definition_id"]), revision=1
    )
    denied = post(
        work, request(work, "proposal.create", derivative_payload(work, parent)), preview=True
    )
    assert (
        denied.status_code == 409 and denied.json()["detail"]["reason"] == "baseline_not_published"
    )


def test_explicit_parent_version_mismatch_and_cross_category_parent_are_rejected(work):
    parent = synthetic_parent(work)
    changed = derivative_payload(work, parent)
    changed["baseline_definition_revision"] = 2
    denied = post(work, request(work, "proposal.create", changed), preview=True)
    assert denied.status_code == 409, denied.text
    assert denied.json()["detail"]["reason"] == "baseline_version_changed"
    other_category, other_product = uuid4(), uuid4()
    with synthetic_owner(work) as session:
        session.add(
            Category(
                id=other_category,
                tenant_id=work.tenant,
                name="其他合成品类",
                purpose="隔离",
                owner_id=work.human,
            )
        )
        session.flush()
        session.add(
            Product(
                id=other_product,
                tenant_id=work.tenant,
                category_id=other_category,
                name="其他品类型号",
                purpose="隔离",
                owner_id=work.human,
            )
        )
    changed = derivative_payload(work, parent)
    changed["baseline_product_id"] = str(other_product)
    denied = post(work, request(work, "proposal.create", changed), preview=True)
    assert denied.status_code == 403 and denied.json()["code"] == "FORBIDDEN_SCOPE"


@pytest.mark.parametrize("target_kind", ["new_product", "new_variant"])
def test_derivative_g0_creates_one_atomic_identity_and_fixed_canonical_definition(
    work, target_kind
):
    parent = synthetic_parent(work)
    proposal_id, _ = create(work, derivative_payload(work, parent, target_kind))
    submit(work, proposal_id)
    frozen = deepcopy(read(work, proposal_id, work.peer).json()["submission"]["frozen_document"])
    assert_inherited(frozen, parent, work)
    # A later published baseline cannot silently change an already-fixed proposal.
    latest = synthetic_parent(work, revision=2)
    assert baseline(work)["definition"]["id"] == str(latest.id)
    assert read(work, proposal_id, work.peer).json()["submission"]["frozen_document"] == frozen
    approved, command = save(work, decide_request(work, proposal_id), actor=work.peer)
    assert post(work, command, actor=work.peer).json()["id"] == approved["id"]
    result = approved["result"]
    with human_session(work) as session:
        grant = session.scalar(
            select(Grant).where(Grant.principal_id == work.peer, Grant.category_id == work.category)
        )
        assert grant.can_write is False and grant.product_manager is True
        decision = session.get(ProposalDecision, UUID(result["decision_id"]))
        definition = session.get(DefinitionRevision, UUID(result["definition_id"]))
        product = session.get(Product, UUID(result["product_id"]))
        project = session.get(Project, UUID(result["project_id"]))
        link = session.scalar(
            select(ProjectProductLink).where(ProjectProductLink.project_id == project.id)
        )
        assert decision.decided_by == work.peer and str(decision.receipt_id) == approved["id"]
        assert definition.status == "draft" and definition.sealed is True
        assert definition.publication_receipt_id is None and definition.revision == 1
        assert (
            definition.derived_from_definition_id == parent.id
            and definition.derived_from_definition_revision == 1
        )
        assert definition.g0_decision_id == decision.id and project.g0_decision_id == decision.id
        assert link.definition_id == definition.id and link.definition_revision == 1
        assert (
            decision.created_definition_id == definition.id
            and decision.created_project_id == project.id
        )
        specs = {
            s.key: s
            for s in session.scalars(
                select(DefinitionSpecRow).where(DefinitionSpecRow.definition_id == definition.id)
            )
        }
        assert specs["parent_number"].value == Decimal("12.345678901234")
        assert specs["parent_range"].lower == Decimal("0.100000000001")
        assert specs["parent_boolean"].text == "false" and specs["parent_enum"].text == "低功耗"
        assert (
            specs["parent_unknown"].availability == "unknown"
            and specs["parent_unknown"].value is None
        )
        assert all(specs[key].confirmed_by is None for key in inherited_specs(frozen))
        if target_kind == "new_product":
            assert (
                product.id != parent.product_id and product.parent_product_id == parent.product_id
            )
            assert (
                definition.variant_id is None
                and decision.created_variant_id is None
                and link.variant_id is None
            )
        else:
            assert product.id == parent.product_id
            variant = session.get(Variant, decision.created_variant_id)
            version = session.scalar(
                select(VariantRevision).where(VariantRevision.variant_id == variant.id)
            )
            assert str(variant.id) == result["variant_id"] and variant.g0_decision_id == decision.id
            assert variant.product_id == product.id and variant.kind == "configuration"
            assert definition.variant_id == variant.id and link.variant_id == variant.id
            assert version.definition_id == definition.id and version.revision == 1
            assert version.parent_definition_id == parent.id and version.parent_revision == 1
            assert version.effective_definition == {
                "definition_id": str(definition.id),
                "definition_revision": 1,
            }
        assert (
            session.scalar(
                select(func.count())
                .select_from(ProposalDecision)
                .where(ProposalDecision.proposal_id == UUID(proposal_id))
            )
            == 1
        )


def publication_receipt(work, parent):
    return Receipt(
        id=uuid4(),
        tenant_id=work.tenant,
        category_id=work.category,
        product_id=parent.product_id,
        command_id=uuid4(),
        actor_id=work.human,
        requester_id=work.human,
        operation="product.definition.publish",
        subject_type="definition_revision",
        subject_id=parent.id,
        subject_revision=parent.revision,
        visibility="category",
        request_digest=digest(str(uuid4())),
        intent_digest=digest(str(uuid4())),
        result={"definition_digest": parent.digest, "synthetic": True},
    )


def test_application_role_cannot_mint_publication_receipt(work):
    parent = synthetic_parent(work, status="draft")
    forged = publication_receipt(work, parent)
    with pytest.raises(DBAPIError) as error:
        with human_session(work) as session:
            assert session.scalar(text("SELECT current_user")) == "pdos_next_app"
            session.add(forged)
    assert_check_violation(
        error, "definition publication receipt requires unavailable named publication authority"
    )
    assert baseline(work)["derivation_eligible"] is False


def test_application_role_cannot_attach_a_synthetic_receipt_and_publish_draft(work):
    parent = synthetic_parent(work, status="draft")
    receipt = publication_receipt(work, parent)
    receipt_id = receipt.id
    with synthetic_owner(work) as session:
        session.add(receipt)
    with pytest.raises(DBAPIError) as error:
        with human_session(work) as session:
            assert session.scalar(text("SELECT current_user")) == "pdos_next_app"
            session.execute(
                text(
                    "UPDATE definition_revisions SET status='published',sealed=true,"
                    "publication_receipt_id=:receipt WHERE id=:definition"
                ),
                {"receipt": receipt_id, "definition": parent.id},
            )
    if error.value.orig.sqlstate == "42501":
        assert "permission denied for table definition_revisions" in str(error.value.orig)
    else:
        assert_check_violation(
            error, "definition publication requires unavailable named publication authority"
        )
    with human_session(work) as session:
        row = session.get(DefinitionRevision, parent.id)
        assert row.status == "draft" and not row.sealed and row.publication_receipt_id is None


def test_readonly_pm_has_no_general_product_creation_right(work):
    identity = uuid4()
    with pytest.raises(DBAPIError) as error:
        with tenant_session(
            work.engine, work.tenant, actor_id=work.peer, category_id=work.category
        ) as session:
            assert session.scalar(text("SELECT current_user")) == "pdos_next_app"
            session.add(
                Product(
                    id=identity,
                    tenant_id=work.tenant,
                    category_id=work.category,
                    owner_id=work.peer,
                    name="未经G0的型号",
                    purpose="合成越权负例",
                    visibility="private",
                )
            )
    assert error.value.orig.sqlstate == "42501"
    assert 'row-level security policy for table "products"' in str(error.value.orig)


def test_revoked_pm_capability_after_preview_blocks_derivative_approval(work):
    from pdos_next.category_scope import MemberGrant, grant_member

    parent = synthetic_parent(work)
    proposal_id, _ = create(work, derivative_payload(work, parent))
    submit(work, proposal_id)
    checked = post(work, decide_request(work, proposal_id), actor=work.peer, preview=True)
    assert checked.status_code == 200, checked.text
    command = checked.json()["command"]
    confirmation_id = proof_id(work, command)
    with human_session(work) as session:
        category = session.get(Category, work.category)
        grant_member(
            session,
            Context(work.tenant, work.human, work.human, category_id=work.category),
            MemberGrant(
                principal_id=work.peer,
                can_write=False,
                product_manager=False,
                expected_revision=category.revision,
                idempotency_key=str(uuid4()),
                decision="批准",
            ),
        )
    denied = post(work, command, actor=work.peer)
    assert (
        denied.status_code,
        denied.json()["code"],
        denied.json()["detail"]["reason"],
    ) in {
        (403, "FORBIDDEN_SCOPE", "reviewer_not_eligible"),
        (404, "NOT_FOUND", "proposal_not_found"),
    }, denied.text
    assert proof_consumed(work, confirmation_id) is False
    with human_session(work) as session:
        assert (
            session.scalar(
                select(ProposalDecision.id).where(ProposalDecision.proposal_id == UUID(proposal_id))
            )
            is None
        )
        assert session.get(Proposal, UUID(proposal_id)).status == "in_review"


def parent_state(work, parent):
    with human_session(work) as session:
        product = session.get(Product, parent.product_id)
        values = {
            field: getattr(product, field)
            for field in (
                "visibility",
                "owner_id",
                "revision",
                "target_price",
                "target_price_currency",
                "target_price_basis",
                "target_price_includes_tax",
                "target_price_as_of",
            )
        }
        audiences = set(
            session.scalars(
                select(ObjectAudience.principal_id).where(
                    ObjectAudience.object_type == "products",
                    ObjectAudience.subject_id == parent.product_id,
                )
            )
        )
        return values, audiences


def test_private_new_variant_preserves_parent_product_audience_and_commercial_values(work):
    parent = synthetic_parent(work, private=True)
    with synthetic_owner(work) as session:
        product = session.get(Product, parent.product_id)
        product.target_price = Decimal("123.450000000001")
        product.target_price_currency, product.target_price_basis = "CNY", "retail"
        product.target_price_includes_tax = True
    before = parent_state(work, parent)
    proposal_id, _ = create(work, derivative_payload(work, parent, "new_variant"))
    submit(work, proposal_id)
    command = decide_request(work, proposal_id)
    command["payload"]["new_identity"] = {"name": "合成私有区域变体", "variant_kind": "region"}
    approved, _ = save(work, command, actor=work.peer)
    assert parent_state(work, parent) == before
    with human_session(work) as session:
        variant = session.get(Variant, UUID(approved["result"]["variant_id"]))
        assert variant.kind == "region" and variant.name == "合成私有区域变体"
        assert variant.visibility == "private" and variant.product_id == parent.product_id
        definition = session.get(DefinitionRevision, UUID(approved["result"]["definition_id"]))
        assert definition.visibility == "private" and definition.publication_receipt_id is None
    # The project/open-item assignee did not gain the existing parent Product.
    with tenant_session(
        work.engine, work.tenant, actor_id=work.expert, category_id=work.category
    ) as session:
        assert session.get(Product, parent.product_id) is None


@pytest.mark.parametrize("fault", ["missing_variant_revision", "wrong_project_variant"])
def test_variant_g0_output_failure_rolls_back_every_identity_and_preserves_approval(work, fault):
    parent = synthetic_parent(work)
    proposal_id, _ = create(work, derivative_payload(work, parent, "new_variant"))
    submit(work, proposal_id)
    checked = post(work, decide_request(work, proposal_id), actor=work.peer, preview=True)
    assert checked.status_code == 200, checked.text
    command = checked.json()["command"]
    confirmation_id = proof_id(work, command)
    touched = []

    def omit_revision(session, _context, _instances):
        for row in list(session.new):
            if isinstance(row, VariantRevision) and row.tenant_id == work.tenant:
                touched.append(row.id)
                session.expunge(row)

    def wrong_variant(_mapper, _connection, row):
        if row.tenant_id == work.tenant:
            assert row.variant_id is not None
            touched.append(row.id)
            row.variant_id = None  # Valid nullable FK shape, wrong canonical scope.

    target, name, hook = (
        (Session, "before_flush", omit_revision)
        if fault == "missing_variant_revision"
        else (ProjectProductLink, "before_insert", wrong_variant)
    )
    database_errors = []

    def record_constraint(error_context):
        original = error_context.original_exception
        database_errors.append(
            (
                getattr(original, "sqlstate", None),
                getattr(getattr(original, "diag", None), "message_primary", ""),
            )
        )

    event.listen(target, name, hook)
    event.listen(Engine, "handle_error", record_constraint)
    try:
        failed = post(work, command, actor=work.peer)
    finally:
        event.remove(target, name, hook)
        event.remove(Engine, "handle_error", record_constraint)
    assert touched
    assert failed.status_code == 422, failed.text
    assert failed.json()["code"] == "VALIDATION_FAILED"
    assert failed.json()["detail"]["reason"] == "CONSTRAINT_VALIDATION_FAILED"
    if fault == "missing_variant_revision":
        # The audience guard can reject the missing revision before the final
        # canonical-output guard runs. Both fail the same injected omission.
        assert any(
            state == "23514"
            and message
            in {"G0 variant canonical definition mismatch", "audience target unavailable"}
            for state, message in database_errors
        )
    else:
        assert any(
            state == "23514"
            and message
            in {
                "G0 derivation outputs require exact same transaction named receipt",
                "project definition variant scope mismatch",
            }
            for state, message in database_errors
        )
    assert proof_consumed(work, confirmation_id) is False
    with human_session(work) as session:
        assert session.get(Proposal, UUID(proposal_id)).status == "in_review"
        for model in (ProposalDecision, Variant, VariantRevision, Project, ProjectProductLink):
            assert (
                session.scalar(
                    select(func.count()).select_from(model).where(model.tenant_id == work.tenant)
                )
                == 0
            )
        assert (
            session.scalar(
                select(func.count())
                .select_from(DefinitionRevision)
                .where(DefinitionRevision.tenant_id == work.tenant)
            )
            == 1
        )
    retried = post(work, command, actor=work.peer)
    assert retried.status_code == 200, retried.text
    assert post(work, command, actor=work.peer).json()["id"] == retried.json()["id"]
    assert proof_consumed(work, confirmation_id) is True
    with human_session(work) as session:
        assert (
            session.scalar(
                select(func.count()).select_from(Variant).where(Variant.tenant_id == work.tenant)
            )
            == 1
        )


def assert_no_g0_outputs(work, proposal_id):
    with human_session(work) as session:
        assert session.get(Proposal, UUID(proposal_id)).status == "in_review"
        for model in (ProposalDecision, Variant, VariantRevision, Project, ProjectProductLink):
            assert (
                session.scalar(
                    select(func.count()).select_from(model).where(model.tenant_id == work.tenant)
                )
                == 0
            )
        assert (
            session.scalar(
                select(func.count())
                .select_from(DefinitionRevision)
                .where(DefinitionRevision.tenant_id == work.tenant)
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count()).select_from(Product).where(Product.tenant_id == work.tenant)
            )
            == 1
        )


@pytest.mark.parametrize(
    ("change", "code"), [("version", "SOURCE_STALE"), ("withdrawn", "SOURCE_UNAVAILABLE")]
)
def test_published_parent_revalidates_native_artifact_before_derivative_create(work, change, code):
    source_id = artifact(work)
    parent = synthetic_parent(work, artifact_source=source_id)
    assert baseline(work)["derivation_eligible"] is True
    command = request(work, "proposal.create", derivative_payload(work, parent))
    assert post(work, command, preview=True).status_code == 200
    # Artifact has no M3 withdraw command. This explicitly synthetic legacy
    # source transition matches the existing G0 source-withdrawal fixture.
    with synthetic_owner(work) as session:
        source = session.get(Artifact, source_id)
        if change == "version":
            source.revision += 1
        else:
            source.status = "withdrawn"
    denied = post(work, command, preview=True)
    assert denied.status_code == 409, denied.text
    assert denied.json()["code"] == code
    assert denied.json()["detail"]["reason"] == code
    assert baseline(work)["derivation_eligible"] is False
    with human_session(work) as session:
        assert (
            session.scalar(
                select(func.count()).select_from(Proposal).where(Proposal.tenant_id == work.tenant)
            )
            == 0
        )
        row = session.get(DefinitionRevision, parent.id)
        assert row.status == "published" and row.publication_receipt_id == parent.receipt_id


def published_claim_parent(work):
    source_id = artifact(work)
    recorded = record_claim(work, source_id)
    claim_id = UUID(recorded["subject_id"])
    parent = synthetic_parent(
        work,
        spec_source_refs=[{"type": "claim", "id": str(claim_id), "version": 1}],
    )
    assert baseline(work)["derivation_eligible"] is True
    return parent, claim_id


def test_published_parent_revalidates_spec_claim_after_real_withdrawal(work):
    parent, claim_id = published_claim_parent(work)
    command = request(work, "proposal.create", derivative_payload(work, parent))
    assert post(work, command, preview=True).status_code == 200
    withdrawn, _ = save(work, withdraw_request(work, claim_id))
    assert withdrawn["operation"] == "evidence.claim.withdraw"
    denied = post(work, command, preview=True)
    assert denied.status_code == 409, denied.text
    assert denied.json()["code"] == "SOURCE_STALE"
    assert denied.json()["detail"]["reason"] == "claim_withdrawn"
    assert baseline(work)["derivation_eligible"] is False
    with human_session(work) as session:
        assert session.get(Claim, claim_id).status == "withdrawn"
        assert (
            session.scalar(
                select(func.count()).select_from(Proposal).where(Proposal.tenant_id == work.tenant)
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(Consumption)
                .where(Consumption.claim_id == claim_id)
            )
            == 0
        )


def stored_frozen_document(work, proposal_id):
    with human_session(work) as session:
        document = session.scalar(
            select(ProposalSubmission.frozen_document)
            .where(ProposalSubmission.proposal_id == UUID(proposal_id))
            .order_by(ProposalSubmission.revision.desc())
            .limit(1)
        )
        assert document is not None
        return deepcopy(document)


def test_parent_claim_withdrawn_after_g0_preview_blocks_old_approval_without_side_effects(work):
    parent, claim_id = published_claim_parent(work)
    proposal_id, _ = create(work, derivative_payload(work, parent, "new_variant"))
    submit(work, proposal_id)
    checked = post(work, decide_request(work, proposal_id), actor=work.peer, preview=True)
    assert checked.status_code == 200, checked.text
    command = checked.json()["command"]
    confirmation_id = proof_id(work, command)
    frozen = stored_frozen_document(work, proposal_id)
    # The parent is only a synthetic publication: there is no fabricated signed
    # Consumption. The actual withdrawal command remains the authority here.
    save(work, withdraw_request(work, claim_id))
    denied = post(work, command, actor=work.peer)
    assert (
        denied.status_code,
        denied.json()["code"],
        denied.json()["detail"]["reason"],
    ) in {
        (409, "SOURCE_STALE", "claim_withdrawn"),
        (403, "SOURCE_UNAVAILABLE", "baseline_not_published"),
        (409, "SOURCE_UNAVAILABLE", "baseline_not_published"),
    }, denied.text
    assert proof_consumed(work, confirmation_id) is False
    assert_no_g0_outputs(work, proposal_id)
    with human_session(work) as session:
        assert (
            session.scalar(
                select(Receipt.id).where(Receipt.command_id == UUID(command["command_id"]))
            )
            is None
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(Consumption)
                .where(Consumption.claim_id == claim_id)
            )
            == 0
        )
        row = session.get(DefinitionRevision, parent.id)
        assert row.status == "published" and row.publication_receipt_id == parent.receipt_id
    # HTTP projections redact withdrawn evidence dynamically; compare the
    # original stored submission under its owner's normal application scope.
    assert stored_frozen_document(work, proposal_id) == frozen


def baseline_get(work, *, actor=None, product_id=None, revision=None):
    return work.client.get(
        f"/v1/categories/{work.category}/products/{product_id or work.product}/baseline",
        params={"definition_revision": revision} if revision is not None else {},
        headers={"Authorization": f"Bearer {work.tokens[actor or work.human]}"},
    )


@pytest.mark.parametrize("target_kind", ["new_product", "new_variant"])
def test_derivative_g0_consumes_parent_claim_closure_once_and_blocks_prepared_withdrawal(
    work, target_kind
):
    parent, claim_id = published_claim_parent(work)
    proposal_id, _ = create(work, derivative_payload(work, parent, target_kind))
    submit(work, proposal_id)
    frozen = read(work, proposal_id, work.peer).json()["submission"]["frozen_document"]
    refs = frozen["baseline_claim_refs"]
    assert [(ref["type"], ref["id"], ref["version"]) for ref in refs] == [
        ("claim", str(claim_id), 1)
    ]
    # This is an actual usable T1 withdrawal confirmation while still unsigned.
    # Approval must invalidate its action, without consuming that old token.
    withdrawal = post(work, withdraw_request(work, claim_id), preview=True)
    assert withdrawal.status_code == 200, withdrawal.text
    withdrawal_command = withdrawal.json()["command"]
    with human_session(work) as session:
        withdrawal_proof = session.scalar(
            select(Confirmation.id).where(
                Confirmation.token_hash
                == digest(withdrawal_command["payload"]["confirmation_token"])
            )
        )
        assert withdrawal_proof is not None
    approved, approval_command = save(work, decide_request(work, proposal_id), actor=work.peer)
    assert post(work, approval_command, actor=work.peer).json()["id"] == approved["id"]
    with human_session(work) as session:
        consumptions = list(
            session.scalars(select(Consumption).where(Consumption.claim_id == claim_id))
        )
        # Six parent specs cite the same Claim: one signed decision consumes it once.
        assert len(consumptions) == 1
        consumed = consumptions[0]
        assert consumed.claim_version == 1 and consumed.tenant_id == work.tenant
        assert consumed.category_id == work.category
        assert str(consumed.product_id) == approved["result"]["product_id"]
        assert str(consumed.decision_id) == approved["result"]["decision_id"]
        assert str(consumed.definition_id) == approved["result"]["definition_id"]
        assert str(consumed.receipt_id) == approved["id"]
        assert consumed.consumer_type == "proposal_decision"
        assert consumed.consumer_id == consumed.decision_id
    denied = post(work, withdrawal_command)
    assert denied.status_code == 409, denied.text
    assert denied.json()["code"] == "UNDO_BLOCKED_BY_DEPENDENCY"
    assert denied.json()["detail"]["reason"] == "consumed_by_decision"
    with human_session(work) as session:
        assert session.get(Confirmation, withdrawal_proof).consumed is False
        assert session.get(Claim, claim_id).status == "active"
        assert (
            session.scalar(
                select(Receipt.id).where(
                    Receipt.command_id == UUID(withdrawal_command["command_id"])
                )
            )
            is None
        )


def test_readonly_pm_get_baseline_checks_claim_sources_and_selects_exact_version(work):
    first, claim_id = published_claim_parent(work)
    second = synthetic_parent(work, revision=2)
    with reviewer_session(work) as session:
        grant = session.scalar(
            select(Grant).where(Grant.principal_id == work.peer, Grant.category_id == work.category)
        )
        assert grant.can_write is False and grant.product_manager is True
        receipts_before = session.scalar(
            select(func.count()).select_from(Receipt).where(Receipt.tenant_id == work.tenant)
        )
    latest = baseline_get(work, actor=work.peer)
    assert latest.status_code == 200, latest.text
    assert latest.json()["definition"]["id"] == str(second.id)
    exact = baseline_get(work, actor=work.peer, revision=1)
    assert exact.status_code == 200, exact.text
    assert exact.json()["definition"]["id"] == str(first.id)
    assert exact.json()["definition"]["revision"] == 1
    assert exact.json()["derivation_eligible"] is True
    assert exact.json()["source_issues"] == []
    missing = baseline_get(work, actor=work.peer, revision=999)
    assert missing.status_code == 200, missing.text
    assert missing.json()["definition"] is None
    assert missing.json()["baseline_kind"] == "unavailable"
    assert missing.json()["derivation_eligible"] is False
    with reviewer_session(work) as session:
        assert (
            session.scalar(
                select(func.count()).select_from(Receipt).where(Receipt.tenant_id == work.tenant)
            )
            == receipts_before
        )
    save(work, withdraw_request(work, claim_id))
    # A withdrawn Claim's historical body is for its owner/explicit historical
    # audience. A formerly category-visible reader must not inherit that access.
    hidden = baseline_get(work, actor=work.peer, revision=1)
    assert hidden.status_code == 200, hidden.text
    assert hidden.json()["definition"] is None
    assert hidden.json()["derivation_eligible"] is False
    assert first.digest not in hidden.text
    stale = baseline_get(work, revision=1)
    assert stale.status_code == 200, stale.text
    assert stale.json()["definition"]["id"] == str(first.id)
    assert stale.json()["baseline_kind"] == "published"
    assert stale.json()["derivation_eligible"] is False
    assert stale.json()["source_issues"] == [{"code": "SOURCE_STALE", "reason": "claim_withdrawn"}]
    assert baseline_get(work, actor=work.peer).json()["definition"]["id"] == str(second.id)


def test_source_audience_revoke_hides_baseline_and_blocks_already_prepared_g0(work):
    private_quote = "仅原件具名受众可读的合成客户细节"
    source_id = artifact(work, body=private_quote, visibility="private")
    parent = synthetic_parent(work, private=True, artifact_source=source_id)
    with human_session(work) as session:
        audience = ObjectAudience(
            id=uuid4(),
            tenant_id=work.tenant,
            category_id=work.category,
            object_type="artifact_versions",
            subject_id=source_id,
            owner_id=work.human,
            principal_id=work.peer,
        )
        audience_id = audience.id
        session.add(audience)
    visible = baseline_get(work, actor=work.peer, revision=1)
    assert visible.status_code == 200, visible.text
    assert visible.json()["derivation_eligible"] is True
    assert visible.json()["definition"]["sources"][0]["quote"] == private_quote
    proposal_id, _ = create(work, derivative_payload(work, parent, "new_variant"))
    submit(work, proposal_id)
    checked = post(work, decide_request(work, proposal_id), actor=work.peer, preview=True)
    assert checked.status_code == 200, checked.text
    command = checked.json()["command"]
    confirmation_id = proof_id(work, command)
    # Simulate an externally authorized revocation in this synthetic fixture.
    # Ordinary app DELETE without the required command/receipt is RLS-filtered
    # to zero rows; it cannot stand in for a successful audience revocation.
    with synthetic_owner(work) as session:
        audience = session.get(ObjectAudience, audience_id)
        assert audience is not None
        session.delete(audience)
    with reviewer_session(work) as session:
        assert session.get(Product, parent.product_id) is not None
        assert session.get(Artifact, source_id) is None
    hidden = baseline_get(work, actor=work.peer, revision=1)
    assert hidden.status_code == 200, hidden.text
    assert hidden.json()["definition"] is None
    assert hidden.json()["derivation_eligible"] is False
    assert private_quote not in hidden.text
    denied = post(work, command, actor=work.peer)
    assert denied.status_code == 409, denied.text
    assert denied.json()["code"] == "SOURCE_UNAVAILABLE"
    assert denied.json()["detail"]["reason"] == "baseline_not_published"
    assert proof_consumed(work, confirmation_id) is False
    assert_no_g0_outputs(work, proposal_id)
    assert baseline_get(work, revision=1).json()["derivation_eligible"] is True


def test_private_publication_requires_readable_receipt_without_leaking_its_digest(work):
    parent = synthetic_parent(work, private=True)
    visible = baseline_get(work, actor=work.peer, revision=1)
    assert visible.status_code == 200, visible.text
    assert visible.json()["derivation_eligible"] is True
    assert visible.json()["definition"]["publication"]["definition_digest"] == parent.digest
    # Remove only this synthetic publication's explicit receipt reader. Product
    # and Definition audiences remain intact, isolating the actual missing fact.
    with synthetic_owner(work) as session:
        audience = session.scalar(
            select(ObjectAudience).where(
                ObjectAudience.object_type == "action_receipts",
                ObjectAudience.subject_id == parent.receipt_id,
                ObjectAudience.principal_id == work.peer,
            )
        )
        assert audience is not None
        session.delete(audience)
    with reviewer_session(work) as session:
        assert session.get(Product, parent.product_id) is not None
        assert session.get(DefinitionRevision, parent.id) is not None
        assert session.get(Receipt, parent.receipt_id) is None
        with pytest.raises(DomainError) as denied:
            published_baseline(
                session,
                Context(work.tenant, work.peer, work.peer, category_id=work.category),
                parent.product_id,
                parent.revision,
                definition_id=parent.id,
            )
        assert denied.value.code == "SOURCE_UNAVAILABLE"
        assert denied.value.detail["reason"] == "baseline_not_published"
    hidden = baseline_get(work, actor=work.peer, revision=1)
    assert hidden.status_code == 200, hidden.text
    assert hidden.json()["definition"] is None
    assert hidden.json()["derivation_eligible"] is False
    assert parent.digest not in hidden.text and str(parent.receipt_id) not in hidden.text
    assert baseline_get(work, revision=1).json()["derivation_eligible"] is True


def typed_private_parent(work, *, source_kind="artifact"):
    quote = "仅底层私有来源受众可见的合成逐字内容"
    copied_value = "从私有祖先继承的唯一合成规格值"
    source_id = artifact(work, body=quote, visibility="private")
    ref = {"type": "artifact", "id": str(source_id), "version": 1, "line": 1, "quote": quote}
    if source_kind == "claim":
        context = payload(work)
        context.update(entry_kind="customer_request", source_refs=[ref])
        private_proposal, _ = create(work, context)
        assert read(work, private_proposal).json()["private_source_count"] > 0
        claim = record_claim(
            work, source_id, quote=quote, text="合成来源事实", proposal_id=private_proposal
        )
        ref = {"type": "claim", "id": claim["subject_id"], "version": 1}
    specs = base_specs()
    next(spec for spec in specs if spec["key"] == "parent_text")["text"] = copied_value
    # Synthetic historical inconsistency: the definition's top-level visibility
    # is category, but typed spec provenance reaches a genuinely private source.
    parent = synthetic_parent(work, spec_source_refs=[ref], spec_values=specs)
    return parent, source_id, quote, copied_value


def definition_reads(work, parent, *, actor):
    headers = {"Authorization": f"Bearer {work.tokens[actor]}"}
    return (
        baseline_get(work, actor=actor, product_id=parent.product_id, revision=parent.revision),
        work.client.get(
            f"/v1/categories/{work.category}/products/{parent.product_id}/definitions",
            headers=headers,
        ),
        work.client.get(
            f"/v1/categories/{work.category}/g0-definitions/{parent.id}", headers=headers
        ),
    )


def assert_private_parent_hidden(work, parent, quote, copied_value):
    baseline_response, listed, fixed = definition_reads(work, parent, actor=work.peer)
    assert baseline_response.status_code == 200, baseline_response.text
    assert baseline_response.json()["definition"] is None
    assert baseline_response.json()["derivation_eligible"] is False
    assert listed.status_code == 200, listed.text
    assert str(parent.id) not in {row["id"] for row in listed.json()["items"]}
    assert fixed.status_code == 404, fixed.text
    assert fixed.json()["detail"]["reason"] == "definition_not_found"
    for response in (baseline_response, listed, fixed):
        assert quote not in response.text and copied_value not in response.text


@pytest.mark.parametrize("source_kind", ["artifact", "claim"])
def test_public_definition_typed_private_root_cannot_launder_derivation_or_read_body(
    work, source_kind
):
    parent, source_id, quote, copied_value = typed_private_parent(work, source_kind=source_kind)
    assert baseline_get(work).json()["derivation_eligible"] is True
    with reviewer_session(work) as session:
        assert session.get(Product, parent.product_id) is not None
        assert session.get(Artifact, source_id) is None
    assert_private_parent_hidden(work, parent, quote, copied_value)
    if source_kind == "claim":
        # A private Claim is additionally bound to its actual source proposal.
        # A readable parent definition cannot silently authorize another one.
        denied = post(
            work, request(work, "proposal.create", derivative_payload(work, parent)), preview=True
        )
        assert denied.status_code == 403, denied.text
        assert denied.json()["code"] == "FORBIDDEN_SCOPE"
        assert denied.json()["detail"]["reason"] == "claim_proposal_mismatch"
        assert_private_parent_hidden(work, parent, quote, copied_value)
        return
    proposal_id, _ = create(work, derivative_payload(work, parent))
    document = read(work, proposal_id).json()
    assert document["private_source_count"] > 0
    with human_session(work) as session:
        assert session.get(Proposal, UUID(proposal_id)).effective_visibility == "private"
    assert inherited_specs(document)["parent_text"]["content"]["text_value"] == copied_value
    sharing = share_request(work, proposal_id)
    for preview in (True, False):
        denied = post(work, sharing, preview=preview)
        assert denied.status_code == 409, denied.text
        assert denied.json()["code"] == "VALIDATION_FAILED"
        assert denied.json()["detail"]["reason"] == "private_sources_present"
    assert read(work, proposal_id, work.peer).status_code == 404
    assert_private_parent_hidden(work, parent, quote, copied_value)


def test_typed_private_source_revocation_hides_all_definition_reads_and_blocks_old_g0(work):
    parent, source_id, quote, copied_value = typed_private_parent(work)
    with synthetic_owner(work) as session:
        audience = ObjectAudience(
            id=uuid4(),
            tenant_id=work.tenant,
            category_id=work.category,
            object_type="artifact_versions",
            subject_id=source_id,
            owner_id=work.human,
            principal_id=work.peer,
        )
        audience_id = audience.id
        session.add(audience)
    baseline_response, listed, fixed = definition_reads(work, parent, actor=work.peer)
    assert baseline_response.status_code == 200, baseline_response.text
    assert baseline_response.json()["derivation_eligible"] is True
    assert listed.status_code == 200 and copied_value in listed.text
    assert fixed.status_code == 200 and copied_value in fixed.text
    proposal_id, _ = create(work, derivative_payload(work, parent, "new_variant"))
    submit(work, proposal_id)
    checked = post(work, decide_request(work, proposal_id), actor=work.peer, preview=True)
    assert checked.status_code == 200, checked.text
    command = checked.json()["command"]
    confirmation_id = proof_id(work, command)
    # External authorized revocation is owner-only fixture data. Do not pretend
    # an app DELETE lacking its required command/receipt removed any audience.
    with synthetic_owner(work) as session:
        session.delete(session.get(ObjectAudience, audience_id))
    with reviewer_session(work) as session:
        assert session.get(Artifact, source_id) is None
        assert session.get(Product, parent.product_id) is not None
    assert_private_parent_hidden(work, parent, quote, copied_value)
    denied = post(work, command, actor=work.peer)
    assert denied.status_code == 409, denied.text
    assert denied.json()["code"] == "SOURCE_UNAVAILABLE"
    assert denied.json()["detail"]["reason"] == "baseline_not_published"
    assert proof_consumed(work, confirmation_id) is False
    assert_no_g0_outputs(work, proposal_id)
    assert baseline_get(work).json()["derivation_eligible"] is True
