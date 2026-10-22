"""Real SELECT/active-UOW substitutes, no database or actual qualification.

The frozen atom reader is called, not replaced. All stored associations and the
candidate callback here are explicitly synthetic fixtures, never live evidence.
"""

from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import fact_atom_storage as atom
import fact_registry_storage as registry
import facts
import pytest
from fact_storage_codec import assemble_fact, body_payload_sha256, decode_fact_body
from pdos_next.errors import DomainError
from pdos_next.models import (
    Audit,
    Confirmation,
    Grant,
    Outbox,
    Principal,
    RequestKey,
)
from pdos_next.service import Context
from sqlalchemy.orm import Session
from test_fact_atom_storage import Memory, frame
from test_facts import material_fixture
from test_paired import AT, uid


class Store:
    def __init__(self, monkeypatch):
        self.patch = monkeypatch
        self.rows, self.entries = {}, {}
        self.memory = Memory(self.rows)
        self.s = Session(bind=SimpleNamespace())
        self.s.begin()
        monkeypatch.setattr(self.s, "scalars", self.memory.scalars)
        monkeypatch.setattr(self.s, "execute", self.memory.execute)
        self.anchor = material_fixture().anchor
        origin = self.anchor.origin
        self.ctx = Context(origin.scope.tenant_id, origin.owner_id, origin.owner_id)
        self.pid = origin.scope.product_id
        self.rows[registry.Project.__tablename__] = [
            dict(
                id=origin.scope.project_id,
                tenant_id=origin.scope.tenant_id,
                product_id=self.pid,
                owner_id=origin.owner_id,
                visibility="product",
                status="active",
            )
        ]
        self.rows[registry.QualityIssueVersion.__tablename__] = [
            dict(
                id=origin.ref.id,
                revision=origin.ref.revision,
                tenant_id=origin.scope.tenant_id,
                product_id=self.pid,
                project_id=origin.scope.project_id,
                issue_id=origin.issue_id,
                owner_id=origin.owner_id,
                writer_id=origin.writer_id,
                visibility=origin.visibility,
                purpose=origin.purpose,
                operation=origin.operation,
                created_at=origin.created_at,
                issue_snapshot=origin.issue.model_dump(mode="json"),
                snapshot_sha256=origin.ref.snapshot_sha256,
                previous_issue_version_id=origin.previous_ref.id if origin.previous_ref else None,
                previous_revision=origin.previous_ref.revision if origin.previous_ref else None,
                input_snapshot=deepcopy(origin.input_snapshot),
                authority_snapshot=deepcopy(origin.authority_snapshot),
                policy_snapshot=deepcopy(origin.policy_snapshot),
                source_basis=deepcopy(origin.persisted_source_basis),
                sources=[v.model_dump(mode="json") for v in origin.sources],
                required_source_read_set=[
                    v.model_dump(mode="json") for v in origin.required_source_read_set
                ],
            )
        ]

    def add(self, kind, *, previous=None, label=None, rule=None, observations=None):
        f = frame(self.patch, kind)
        raw = deepcopy(f.document.model_dump(mode="json"))
        body = raw["body"]
        label = label or kind
        body["ref"] = {
            "id": str(uid("registry-" + label)),
            "revision": previous.ref.revision + 1 if previous else 1,
        }
        body["previous"] = previous.ref.model_dump(mode="json") if previous else None
        if rule:
            body["rule"] = rule.ref.model_dump(mode="json")
        if observations:
            body["observations"] = [v.ref.model_dump(mode="json") for v in observations]
        document = decode_fact_body(raw)
        value = document.body
        row = f.row
        row.update(
            id=value.ref.id,
            revision=value.ref.revision,
            fact_body=raw,
            payload_sha256=body_payload_sha256(raw),
        )
        row.update(
            origin_issue_version_id=self.anchor.origin.ref.id,
            origin_issue_revision=self.anchor.origin.ref.revision,
            anchor_snapshot=self.anchor.model_dump(mode="json"),
            anchor_sha256=self.anchor.anchor_sha256,
            requirement_sha256=value.requirement_sha256,
            sources=[v.model_dump(mode="json") for v in value.sources],
            required_source_read_set=[
                v.model_dump(mode="json") for v in value.required_source_read_set
            ],
            source_basis=[v.model_dump(mode="json") for v in value.source_basis],
        )
        if kind != "review":
            row.update(
                series_id=self.entries[previous.ref.id].row["series_id"]
                if previous
                else value.ref.id,
                previous_fact_id=previous.ref.id if previous else None,
                previous_revision=previous.ref.revision if previous else None,
                issuer_key=value.issuer.key,
                issuer_version=value.issuer.version,
                issuer_epoch=value.issuer.epoch,
            )
        if kind == "rule":
            row.update(
                external_id="controlled-registry-series",
                valid_from=value.valid_from,
                valid_until=value.valid_until,
            )
        else:
            row.update(
                rule_fact_id=value.rule.id,
                rule_revision=value.rule.revision,
                rule_sha256=value.rule.sha256,
            )
            if kind == "observation":
                row.update(
                    executor_id=value.executor_id,
                    observed_from=value.observed_from,
                    observed_until=value.observed_until,
                )
            else:
                row.update(
                    candidate_id=value.candidate.id,
                    candidate_revision=value.candidate.revision,
                    candidate_sha256=value.candidate.sha256,
                    reviewer_id=value.reviewer_id,
                    valid_until=value.valid_until,
                    authority_snapshot=value.authority_snapshot,
                    policy_snapshot=value.policy_snapshot,
                )
        receipt = f.receipt
        receipt.id, receipt.command_id = uid(label + "-receipt"), uid(label + "-command")
        row["command_id"] = receipt.command_id
        row["intent_digest"] = receipt.intent_digest = facts.digest(label + "-common-intent")
        receipt.subject_id, receipt.subject_revision = value.ref.id, value.ref.revision
        receipt.result.update(
            id=str(value.ref.id), revision=value.ref.revision, payload_sha256=row["payload_sha256"]
        )
        for model in (Audit, Outbox, RequestKey):
            for item in f.rows[model]:
                item.id, item.receipt_id = uid(label + model.__name__), receipt.id
                if model is Outbox:
                    item.subject_id, item.subject_revision = value.ref.id, value.ref.revision
                    item.correlation_id = receipt.command_id
        for proof in f.rows[Confirmation]:
            proof.id = row["shared_proof_id"] = uid(label + "-proof")
        for key, values in f.rows.items():
            target = self.rows.setdefault(key, [])
            for item in values:
                identity = item["id"] if isinstance(item, dict) else item.id
                if not any((v["id"] if isinstance(v, dict) else v.id) == identity for v in target):
                    target.append(item)
        f.s.close()
        fact = self.assemble(kind, row)
        entry = SimpleNamespace(row=row, fact=fact, receipt=receipt)
        self.entries[fact.ref.id] = entry
        if kind != "review":
            pointer = {k: deepcopy(row[k]) for k in registry.models.BINDING}
            pointer.update(
                id=uid(kind + "-pointer-" + str(row["series_id"])),
                created_at=AT,
                series_id=row["series_id"],
                fact_id=fact.ref.id,
                fact_revision=fact.ref.revision,
                epoch=fact.ref.revision + 4,
                anchor_snapshot=deepcopy(row["anchor_snapshot"]),
            )
            if kind == "rule":
                pointer.update(
                    issuer_key=row["issuer_key"],
                    issuer_version=row["issuer_version"],
                    external_id=row["external_id"],
                )
            table = registry.CURRENTS[kind].name
            existing = self.rows.setdefault(table, [])
            old = next((p for p in existing if p["series_id"] == row["series_id"]), None)
            if old:
                old.update(pointer)
            else:
                existing.append(pointer)
        return fact

    def assemble(self, kind, row):
        group = atom.read_fact_atom(
            self.s, self.ctx, self.pid, kind=kind, fact_id=row["id"], revision=row["revision"]
        )
        return assemble_fact(
            row["fact_body"], group.atom, expected_payload_sha256=row["payload_sha256"]
        )

    def reseal(self, kind, fact, change):
        entry = self.entries[fact.ref.id]
        change(entry.row)
        entry.row["payload_sha256"] = body_payload_sha256(entry.row["fact_body"])
        entry.receipt.result["payload_sha256"] = entry.row["payload_sha256"]
        value = self.assemble(kind, entry.row)
        entry.fact = value
        return value

    def read(self, kind, value, **kwargs):
        return registry.read_stored_fact(self.s, self.ctx, self.pid, kind, value.ref, **kwargs)

    def candidate(self, review):
        row = self.entries[review.ref.id].row
        self.rows[registry.CapaVerificationEvidence.__tablename__] = [
            dict(
                id=review.candidate.id,
                revision=1,
                **{k: row[k] for k in registry.models.SCOPE},
                owner_id=row["owner_id"],
                visibility=row["visibility"],
                purpose=row["purpose"],
                nature=row["nature"],
                status="candidate",
                result="indeterminate",
                applicable=None,
                independently_verified=None,
                observation_complete=None,
            )
        ]

        def owner(s, ctx, pid, ref):
            # Synthetic callback: only raw correspondence, never a HostFactProof.
            return registry.CandidateRegistryRead(
                s,
                ctx,
                pid,
                ref,
                review.scope,
                review.issue_id,
                review.capa_id,
                review.purpose,
                review.owner_id,
                review.visibility,
                review.nature,
                review.anchor_sha256,
                review.requirement_sha256,
            )

        return owner


@pytest.fixture
def work(monkeypatch):
    w = Store(monkeypatch)
    yield w
    w.s.close()


def test_current_rule_is_only_registry_material_never_live_evidence(work):
    rule = work.add("rule")
    read = work.read("rule", rule)
    assert read.fact == rule
    assert read.registry.state == "current_registered"
    assert read.registry.current_ref == rule.ref
    assert read.registry.current_epoch == 5  # Not guessed from revision.
    assert read.dependencies == ()
    assert read.needs_lineage_owner is True
    assert read.current_evidence_authorized is read.same_uow_consumption_attested is False
    assert len(read.missing) == 9
    assert not hasattr(read, "host_proofs")
    assert all(q.get_execution_options().get("autoflush") is False for q in work.memory.queries)


def test_shared_product_fact_cannot_bypass_private_project_owner(work):
    rule = work.add("rule")
    project = work.rows[registry.Project.__tablename__][0]
    project.update(visibility="private", owner_id=uid("other project owner"))
    with pytest.raises(DomainError) as error:
        work.read("rule", rule)
    assert error.value.code == "FORBIDDEN_SCOPE"
    assert error.value.status == 403
    project["owner_id"] = work.ctx.requester_id
    assert work.read("rule", rule).current_evidence_authorized is False


def test_missing_or_wrong_scope_project_is_not_a_product_grant(work):
    rule = work.add("rule")
    project = work.rows[registry.Project.__tablename__][0]
    project["product_id"] = uid("other product project")
    with pytest.raises(DomainError) as error:
        work.read("rule", rule)
    assert error.value.code == "FACT_EXACT_REGISTRY_ROW_MISSING"


def test_after_all_owner_io_project_audience_must_still_match(work):
    rule = work.add("rule")
    observation = work.add("observation", rule=rule)
    review = work.add("review", rule=rule, observations=[observation])
    owner = work.candidate(review)

    def callback(s, ctx, pid, ref):
        value = owner(s, ctx, pid, ref)
        # It is still readable by this owner, but the captured audience changed.
        work.rows[registry.Project.__tablename__][0]["visibility"] = "private"
        return value

    with pytest.raises(DomainError) as error:
        work.read("review", review, candidate_owner=callback)
    assert error.value.code == "FACT_PROJECT_CHANGED_DURING_READ"


def test_rule_history_keeps_exact_ref_and_fixed_complete_origin_without_issue_latest(work):
    old = work.add("rule")
    current = work.add("rule", previous=old, label="rule-v2")
    read = work.read("rule", old)
    assert read.registry.state == "historical_registered"
    assert read.registry.current_ref == current.ref
    assert read.fact.ref == old.ref
    assert read.fact.sources == old.sources
    assert not any(
        q.get_final_froms()[0].name == "quality_current_issues" for q in work.memory.queries
    )


def test_observation_uses_fixed_historical_rule_not_the_latest_rule(work):
    old = work.add("rule")
    newer = work.add("rule", previous=old, label="new-rule")
    observation = work.add("observation", rule=old)
    read = work.read("observation", observation)
    assert read.dependencies[0].fact.ref == old.ref
    assert read.dependencies[0].registry.current_ref == newer.ref
    assert read.dependencies[0].registry.state == "historical_registered"
    assert read.fact.at == observation.at


def test_review_fixed_ordered_observations_and_history_are_not_replaced(work):
    rule = work.add("rule")
    first = work.add("observation", rule=rule, label="obs-first")
    second = work.add("observation", rule=rule, label="obs-second")
    newer = work.add("observation", rule=rule, previous=first, label="obs-first-v2")
    review = work.add("review", rule=rule, observations=[second, first])
    read = work.read("review", review, candidate_owner=work.candidate(review))
    assert read.registry.state == "fixed_review" and read.registry.current_ref is None
    assert [d.fact.ref for d in read.dependencies] == [rule.ref, second.ref, first.ref]
    assert read.dependencies[2].registry.current_ref == newer.ref
    assert read.candidate.ref == review.candidate
    assert read.current_evidence_authorized is False


def test_review_without_true_candidate_full_sha_owner_is_explicitly_blocked(work):
    rule = work.add("rule")
    observation = work.add("observation", rule=rule)
    review = work.add("review", rule=rule, observations=[observation])
    with pytest.raises(DomainError) as error:
        work.read("review", review)
    assert error.value.code == "FACT_CANDIDATE_OWNER_REQUIRED"
    assert error.value.status == 503


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "wrong_scope",
        "wrong_series",
        "wrong_epoch",
        "wrong_owner",
        "wrong_purpose",
        "wrong_issuer",
        "duplicate",
    ],
)
def test_rule_current_cannot_be_missing_rebound_or_ambiguous(work, mutation):
    rule = work.add("rule")
    pointers = work.rows[registry.CURRENTS["rule"].name]
    if mutation == "missing":
        pointers.clear()
    elif mutation == "duplicate":
        pointers.append(deepcopy(pointers[0]))
    else:
        field, value = {
            "wrong_scope": ("project_id", uid("foreign project")),
            "wrong_series": ("series_id", uid("foreign series")),
            "wrong_epoch": ("epoch", True),
            "wrong_owner": ("owner_id", uid("foreign owner")),
            "wrong_purpose": ("purpose", "different purpose"),
            "wrong_issuer": ("issuer_version", "v-other"),
        }[mutation]
        pointers[0][field] = value
    with pytest.raises(DomainError):
        work.read("rule", rule)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_previous",
        "wrong_previous_sha",
        "rebound_series",
        "disconnected_selected",
        "source_mirror",
        "origin_snapshot",
        "anchor_digest",
    ],
)
def test_broken_continuous_chain_or_complete_saved_context_is_rejected(work, mutation):
    old = work.add("rule")
    current = work.add("rule", previous=old, label="v2")
    row = work.entries[old.ref.id].row
    if mutation == "missing_previous":
        work.rows[registry.TABLES["rule"].name].remove(row)
    elif mutation == "wrong_previous_sha":

        def change(v):
            v["fact_body"]["body"]["previous"]["sha256"] = "f" * 64

        current = work.reseal("rule", current, change)
    elif mutation == "rebound_series":
        row["series_id"] = uid("unrelated root")
    elif mutation == "disconnected_selected":
        current = work.add("rule", label="other-independent")
        pointer = work.rows[registry.CURRENTS["rule"].name][0]
        pointer.update(fact_id=current.ref.id, fact_revision=current.ref.revision)
        current = old
    elif mutation == "source_mirror":
        row["source_basis"][0]["hash"] = "f" * 64
    elif mutation == "origin_snapshot":
        work.rows[registry.QualityIssueVersion.__tablename__][0]["issue_snapshot"]["title"] = (
            "forged origin"
        )
    else:
        row["anchor_snapshot"]["full_failure_proofs_sha256"] = "f" * 64
    with pytest.raises((DomainError, ValueError)):
        work.read("rule", current)


def test_wrong_selected_full_digest_is_not_accepted_as_payload_digest(work):
    rule = work.add("rule")
    row = work.entries[rule.ref.id].row
    for sha in ("f" * 64, row["payload_sha256"]):
        ref = facts.FactRef(id=rule.ref.id, revision=rule.ref.revision, sha256=sha)
        with pytest.raises(ValueError, match="FACT_FULL_REF_MISMATCH"):
            registry.read_stored_fact(work.s, work.ctx, work.pid, "rule", ref)


def test_actual_saved_group_change_cannot_reuse_old_full_ref(work):
    rule = work.add("rule")
    audit = next(v for v in work.rows[Audit] if v.receipt_id == rule.provenance.receipt_id)
    audit.id = uid("different actual audit row")
    with pytest.raises(ValueError, match="FACT_FULL_REF_MISMATCH"):
        work.read("rule", rule)


def test_observation_wrong_fixed_child_full_sha_is_not_silently_refreshed(work):
    rule = work.add("rule")
    observation = work.add("observation", rule=rule)

    def change(row):
        row["fact_body"]["body"]["rule"]["sha256"] = "f" * 64
        row["rule_sha256"] = "f" * 64

    observation = work.reseal("observation", observation, change)
    with pytest.raises(ValueError, match="FACT_FULL_REF_MISMATCH"):
        work.read("observation", observation)


def test_review_duplicate_or_different_rule_children_cannot_form_fixed_evidence(work):
    rule = work.add("rule")
    newer = work.add("rule", previous=rule, label="rule-child-v2")
    old = work.add("observation", rule=rule, label="old-child")
    different = work.add("observation", rule=newer, label="new-child")
    duplicate = work.add("review", rule=rule, observations=[old, old], label="duplicate-review")
    with pytest.raises(DomainError) as error:
        work.read("review", duplicate)
    assert error.value.code == "FACT_DUPLICATE_OBSERVATION_REF"
    mismatched = work.add("review", rule=rule, observations=[different], label="wrong-review")
    with pytest.raises(DomainError) as error:
        work.read("review", mismatched)
    assert error.value.code == "FACT_REVIEW_OBSERVATION_RULE_MISMATCH"


def test_reader_does_not_create_flush_commit_or_reserve_anything(work, monkeypatch):
    rule = work.add("rule")
    original_rows = {key: len(values) for key, values in work.rows.items()}

    def forbidden(*args, **kwargs):
        pytest.fail("Raw registry reading attempted a write or new UOW")

    for name in ("add", "add_all", "flush", "commit", "begin", "begin_nested"):
        monkeypatch.setattr(work.s, name, forbidden)
    assert work.read("rule", rule).current_evidence_authorized is False
    assert original_rows == {key: len(values) for key, values in work.rows.items()}


@pytest.mark.parametrize("kind,ref", [("candidate", None), ([], None), ("rule", True)])
def test_typed_kind_and_full_ref_are_required_before_sql(work, kind, ref):
    with pytest.raises(DomainError):
        registry.read_stored_fact(work.s, work.ctx, work.pid, kind, ref)
    assert work.memory.queries == []


@pytest.mark.parametrize(
    "which",
    [
        "rule_parent",
        "candidate_parent",
        "owner_session",
        "owner_caller",
        "owner_ref",
        "owner_scope",
        "owner_purpose",
    ],
)
def test_review_missing_or_wrong_exact_parents_and_candidate_callback_bindings(work, which):
    rule = work.add("rule")
    obs = work.add("observation", rule=rule)
    review = work.add("review", rule=rule, observations=[obs])
    callback = work.candidate(review)
    if which == "rule_parent":
        work.rows[registry.TABLES["rule"].name].clear()
    elif which == "candidate_parent":
        work.rows[registry.CapaVerificationEvidence.__tablename__].clear()
    else:
        old_callback = callback

        def callback(s, ctx, pid, ref):
            value = old_callback(s, ctx, pid, ref)
            changes = {
                "owner_session": {"session": object()},
                "owner_caller": {"caller": Context(ctx.tenant_id, ctx.actor_id, ctx.requester_id)},
                "owner_ref": {"ref": ref.model_copy(update={"sha256": "f" * 64})},
                "owner_scope": {
                    "scope": value.scope.model_copy(update={"project_id": uid("other")})
                },
                "owner_purpose": {"purpose": "different purpose"},
            }
            return replace(value, **changes[which])

    with pytest.raises(DomainError):
        work.read("review", review, candidate_owner=callback)


def test_final_current_reread_after_all_candidate_io_detects_late_pointer_change(work):
    rule = work.add("rule")
    obs = work.add("observation", rule=rule)
    review = work.add("review", rule=rule, observations=[obs])
    owner = work.candidate(review)

    def callback(s, ctx, pid, ref):
        value = owner(s, ctx, pid, ref)
        work.rows[registry.CURRENTS["rule"].name][0]["epoch"] += 1
        return value

    with pytest.raises(DomainError) as error:
        work.read("review", review, candidate_owner=callback)
    assert error.value.code == "FACT_CURRENT_CHANGED_DURING_READ"


@pytest.mark.parametrize("change", ["caller", "transaction", "principal", "grant_expiry"])
def test_final_caller_uow_and_post_io_acl_are_not_synthetic_positive(work, change):
    rule = work.add("rule")
    count = 0

    def hook(key):
        nonlocal count
        if key == registry.CURRENTS["rule"].name:
            count += 1
            if count == 2:
                if change == "caller":
                    # Deliberately corrupt a normally frozen context: the read
                    # must detect a changed actual caller rather than reuse it.
                    object.__setattr__(work.ctx, "actor_id", uid("different caller"))
                elif change == "transaction":
                    work.s.commit()
                    work.s.begin()
                elif change == "principal":
                    work.rows[Principal][0].active = False
                else:
                    work.rows[Grant][0].expires_at = AT

    work.memory.hook = hook
    with pytest.raises(DomainError):
        work.read("rule", rule)


def test_post_io_grant_query_clock_cannot_precede_expiry(work, monkeypatch):
    rule = work.add("rule")
    clock = [AT + timedelta(days=1)]

    class Clock(atom.datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0]

    monkeypatch.setattr(atom, "datetime", Clock)
    original = work.rows[Grant][0].expires_at
    count = 0

    def hook(key):
        nonlocal count
        if key is Grant:
            count += 1
            # Initial top ACL + atom initial/final ACL, then final outer ACL.
            if count == 4:
                clock[0] = original

    work.memory.hook = hook
    with pytest.raises(DomainError) as error:
        work.read("rule", rule)
    assert error.value.code == "FORBIDDEN_SCOPE"


def test_aggregate_bound_rejects_before_a_truncated_current_result(work, monkeypatch):
    rule = work.add("rule")
    monkeypatch.setattr(registry, "MAX_NODES", 2)
    with pytest.raises(DomainError) as error:
        work.read("rule", rule)
    assert error.value.code == "FACT_REGISTRY_LIMIT_EXCEEDED"


def test_active_real_savepoint_is_supported_and_ending_it_during_owner_io_is_rejected(work):
    rule = work.add("rule")
    nested = work.s.begin_nested()
    assert work.read("rule", rule).registry.state == "current_registered"
    obs = work.add("observation", rule=rule)
    review = work.add("review", rule=rule, observations=[obs])
    owner = work.candidate(review)

    def callback(s, ctx, pid, ref):
        value = owner(s, ctx, pid, ref)
        nested.rollback()
        return value

    with pytest.raises(DomainError) as error:
        work.read("review", review, candidate_owner=callback)
    assert error.value.code == "FACT_CALLER_UOW_CHANGED"


@pytest.mark.parametrize(
    "scope", ["foreign_product", "foreign_tenant", "private_other", "agent", "no_active_uow"]
)
def test_foreign_scope_private_human_and_actual_uow_are_required(work, scope):
    rule = work.add("rule")
    if scope == "foreign_product":
        work.pid = uid("foreign product")
    elif scope == "foreign_tenant":
        work.ctx = replace(work.ctx, tenant_id=uid("foreign tenant"))
    elif scope == "private_other":
        row = work.entries[rule.ref.id].row
        row["visibility"] = "private"
        row["owner_id"] = uid("someone else")
    elif scope == "agent":
        work.rows[Principal][0].kind = "agent"
    else:
        work.s.rollback()
    with pytest.raises(DomainError):
        work.read("rule", rule)
