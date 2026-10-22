"""One actual CAPA candidate/rule/observation chain, with original source material."""

# ruff: noqa: F401, F811 -- explicit fixture imports register the upstream tree

import json
from copy import deepcopy
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from build_start.test_transactions import import_authority
from sqlalchemy import func, select
from test_project_first_plan import accepted, cmd, post
from verification_handoff.fixtures import artifact

from pdos_next.capa_rule_import import publish_rule
from pdos_next.capa_rule_publisher import configure_local_profile
from pdos_next.contracts import Command
from pdos_next.database import tenant_session
from pdos_next.domain.capa_effectiveness import candidate_commands, fact_commands, fact_service
from pdos_next.domain.capa_effectiveness import service as candidates
from pdos_next.domain.capa_effectiveness.fact_atom_storage import read_fact_atom
from pdos_next.domain.capa_effectiveness.fact_storage_codec import assemble_fact
from pdos_next.domain.capa_effectiveness.fact_storage_models import (
    ObservationFact,
    RuleCurrent,
    RuleFact,
)
from pdos_next.domain.capa_effectiveness.fact_write import prepare_fact
from pdos_next.domain.quality_execution import policy
from pdos_next.models import Audit, Outbox, Receipt, now
from quality_followup_transactions.fixtures import (
    accepted_work,
    complete_command,
    current_rows,
    exact_source,
    fixed_issue,
    followup_integration_contract,
    followup_work,
    known_configuration,
    launch_work,
    operational_work,
    quality_work,
    ready_work,
    results_work,
    root_command,
)


def session(work):
    return tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.human,
        requester_id=work.quality.human,
        category_id=work.setup.category,
    )


def actual_counts(work):
    with session(work) as s:
        return {
            cls.__tablename__: s.scalar(select(func.count()).select_from(cls))
            for cls in (ObservationFact, RuleFact, RuleCurrent, Receipt, Audit, Outbox)
        }


def test_candidate_snapshot_reads_once_preserves_deadlines_and_rechecks_next_request(
    followup_work, monkeypatch
):
    from sqlalchemy import event, text

    from pdos_next import capa_candidate_api
    from pdos_next.domain.capa_effectiveness import anchor_owner, candidate_prepare
    from pdos_next.domain.capa_verification import service as verification
    from pdos_next.domain.capa_verification.models import CapaVerificationEvidence
    from pdos_next.domain.quality_execution.models import QualityIssueCurrent, QualityIssueVersion
    from pdos_next.models import (
        Artifact,
        Confirmation,
        OriginalSecurity,
        RequestKey,
        UploadedOriginal,
    )
    from pdos_next.originals import object_reference

    work = followup_work
    accepted(work.quality, root_command(work))
    accepted(work.quality, complete_command(work, (0, 1)))
    current = fixed_issue(work)
    expiry = now() + timedelta(hours=2)
    for kind in ("duty", "qualification"):
        import_authority(
            work,
            "quality",
            kind,
            subject_id=str(work.quality.human),
            operations=[candidate_commands.OPERATION],
            external_id=f"candidate-snapshot-{work.issue_id}-{kind}",
            valid_from=(now() - timedelta(minutes=1)).isoformat(),
            valid_until=expiry.isoformat(),
        )

    def counts():
        with session(work) as s:
            return {
                cls.__tablename__: s.scalar(select(func.count()).select_from(cls))
                for cls in (
                    QualityIssueVersion,
                    QualityIssueCurrent,
                    CapaVerificationEvidence,
                    Confirmation,
                    RequestKey,
                    Receipt,
                    Audit,
                    Outbox,
                )
            }

    base = f"/v1/categories/{work.setup.category}/products/{work.setup.product}"
    command = cmd(
        work.quality,
        candidate_commands.OPERATION,
        {
            "issue_id": str(work.issue_id),
            "expected_issue_revision": current.revision,
            "capa_id": str(work.capa_id),
            "visibility": "private",
            "reason": "Read actual incomplete candidate without any business write",
        },
    )

    def get():
        return work.quality.client.get(
            base + "/capa-candidates",
            headers=work.quality.headers,
            params={"issue_id": str(work.issue_id)},
        )

    def inputs():
        return work.quality.client.post(
            base + "/quality-followup/inputs", headers=work.quality.headers, json=command
        )

    anchor, inspect = anchor_owner.read_anchor_from_actual_owner, verification.inspect_candidate
    fixed_result = verification.quality._result
    calls = {"anchor": 0, "inspect": 0, "basis_results": 0}

    def read_anchor(s, *args, **kwargs):
        assert s.info["read_snapshot"] is True
        assert s.connection().get_isolation_level() == "REPEATABLE READ"
        assert s.scalar(text("SHOW transaction_read_only")) == "on"
        calls["anchor"] += 1
        return anchor(s, *args, **kwargs)

    def inspect_once(*args, **kwargs):
        calls["inspect"] += 1
        return inspect(*args, **kwargs)

    def fixed_basis_result(*args, **kwargs):
        calls["basis_results"] += 1
        return fixed_result(*args, **kwargs)

    monkeypatch.setattr(anchor_owner, "read_anchor_from_actual_owner", read_anchor)
    monkeypatch.setattr(verification, "inspect_candidate", inspect_once)
    monkeypatch.setattr(verification.quality, "_result", fixed_basis_result)
    before = counts()
    for request in (get, inputs):
        calls.update(anchor=0, inspect=0, basis_results=0)
        fact_queries = []

        def selected_facts(
            _connection,
            _cursor,
            statement,
            _parameters,
            _context,
            _many,
            *,
            fact_queries=fact_queries,
        ):
            if (
                statement.lstrip().upper().startswith("SELECT")
                and "professional_authority_facts" in statement
            ):
                fact_queries.append(1)

        event.listen(work.setup.engine, "before_cursor_execute", selected_facts)
        try:
            response = request()
        finally:
            event.remove(work.setup.engine, "before_cursor_execute", selected_facts)
        assert response.status_code == 200, response.text
        value = response.json().get("host", response.json())
        assert value["allowed"] is True and value["required_source_read_set"]
        assert calls == {
            "anchor": 1,
            "inspect": 1,
            "basis_results": len(current.issue_snapshot["failures"]),
        }
        assert len(fact_queries) == 1
        assert counts() == before

    # A fixed basis is shared only by the same real snapshot/UOW. SAVEPOINT
    # changes and rollback cannot inherit an earlier preparation capability.
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.human,
        requester_id=work.quality.human,
        category_id=work.setup.category,
        read_snapshot=True,
    ) as s:
        calls.update(anchor=0, inspect=0, basis_results=0)
        basis = verification.load_followup_basis(
            s, work.quality.ctx, work.setup.product, work.issue_id, current.revision
        )
        assert (
            verification.recheck_followup_basis(s, work.quality.ctx, work.setup.product, basis)
            == basis
        )
        failures = len(current.issue_snapshot["failures"])
        assert calls["basis_results"] == failures
        savepoint = s.begin_nested()
        assert (
            verification.recheck_followup_basis(s, work.quality.ctx, work.setup.product, basis)
            == basis
        )
        assert calls["basis_results"] == failures * 2
        savepoint.rollback()
        assert (
            verification.recheck_followup_basis(s, work.quality.ctx, work.setup.product, basis)
            == basis
        )
        assert calls["basis_results"] == failures * 3
    assert counts() == before

    # Display/history may finish after the preparation's clock, or replace a
    # runtime issuer epoch. Neither can inherit the earlier positive assessment.
    history, actual_clock = capa_candidate_api._history, candidate_prepare._clock
    for dimension in ("clock", "runtime"):
        state = {"late": False}
        with monkeypatch.context() as patch:

            def displayed(*args, _state=state, _dimension=dimension, **kwargs):
                value = history(*args, **kwargs)
                _state["late"] = True
                if _dimension == "runtime":
                    patch.setattr(
                        work.setup.engine,
                        "_pdos_quality_policy_epochs",
                        {
                            **getattr(work.setup.engine, "_pdos_quality_policy_epochs", {}),
                            "synthetic-display-epoch": 1,
                        },
                    )
                return value

            patch.setattr(capa_candidate_api, "_history", displayed)
            if dimension == "clock":
                patch.setattr(
                    candidate_prepare,
                    "_clock",
                    lambda _state=state: (
                        expiry + timedelta(seconds=1) if _state["late"] else actual_clock()
                    ),
                )
            response = get()
        assert state["late"] is True
        assert response.status_code == 200, response.text
        assert response.json()["host"]["allowed"] is False
        assert any(value["code"] == "SOURCE_STALE" for value in response.json()["host"]["missing"])
        assert counts() == before

    # Genuine post-owner clock checks must remain after the last saved-group IO.
    clock, saved = candidate_prepare._clock, candidate_prepare._saved_origin_anchor
    for request in (get, inputs):
        state = {"saved_reads": 0, "late": False}

        def saved_group(*args, _state=state, **kwargs):
            value = saved(*args, **kwargs)
            _state["saved_reads"] += 1
            _state["late"] = _state["saved_reads"] >= 2
            return value

        with monkeypatch.context() as patch:
            patch.setattr(candidate_prepare, "_saved_origin_anchor", saved_group)
            patch.setattr(
                candidate_prepare,
                "_clock",
                lambda _state=state: expiry + timedelta(seconds=1) if _state["late"] else clock(),
            )
            response = request()
        assert state["late"] is True
        assert response.status_code == 403, response.text
        assert response.json()["code"] == "QUALIFICATION_REQUIRED"
        assert counts() == before

    with session(work) as s:
        original = s.get(UploadedOriginal, s.get(Artifact, work.completion_artifact_id).original_id)
        security = s.scalar(
            select(OriginalSecurity).where(OriginalSecurity.original_id == original.id)
        )
        reference, epoch = object_reference(original), security.epoch
    accepted(
        work.quality,
        cmd(
            work.quality,
            "evidence.original.withdraw",
            {
                "original_id": str(reference.id),
                "expected_epoch": epoch,
                "reason": "Withdraw the actual completion source between candidate requests",
            },
        ),
    )
    after_withdrawal = counts()
    response = inputs()
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "SOURCE_UNAVAILABLE"
    response = get()
    assert response.status_code == 200, response.text
    assert response.json()["host"]["allowed"] is False
    assert response.json()["host"]["source_status"] == "needs_recheck"
    assert counts() == after_withdrawal
    assert fixed_issue(work).id == current.id


def test_actual_candidate_rule_and_observation_keep_complete_sources_current_and_receipt(
    followup_work,
):
    work = followup_work
    accepted(work.quality, root_command(work))
    accepted(work.quality, complete_command(work, (0, 1)))
    current = fixed_issue(work)
    assert current.status == "awaiting_verification"
    operations = [
        candidate_commands.OPERATION,
        fact_commands.RULE_OPERATION,
        fact_commands.OBSERVATION_OPERATION,
        fact_commands.REVIEW_OPERATION,
    ]
    authority = {
        kind: import_authority(
            work,
            "quality",
            kind,
            subject_id=str(work.quality.human),
            operations=operations,
            external_id=f"capa-fact-{work.issue_id}-{kind}",
        )
        for kind in ("duty", "qualification")
    }
    value = cmd(
        work.quality,
        candidate_commands.OPERATION,
        {
            "issue_id": str(work.issue_id),
            "expected_issue_revision": current.revision,
            "capa_id": str(work.capa_id),
            "visibility": "private",
            "reason": "Record actual incomplete candidate without claiming effectiveness",
        },
    )
    with session(work) as s:
        inputs = candidates.inputs(
            s, work.quality.ctx, work.setup.product, Command.model_validate(value)
        )
    value["source_read_set"] = inputs["required_source_read_set"]
    candidate_receipt, _ = accepted(work.quality, value)
    assert candidate_receipt["subject_type"] == "capa_verification_candidate"
    assert fixed_issue(work).id == current.id  # Candidate does not decide or close the Issue.

    with session(work) as s:
        runtime = fact_service._runtime(s)
    runtime.host.owner.publisher = configure_local_profile(
        work.setup.engine,
        {
            "tenant_id": str(work.setup.tenant),
            "product_id": str(work.setup.product),
            "project_id": work.config["project"],
            "issuer_key": f"capa-rule-{work.issue_id}",
            "issuer_version": "synthetic-v1",
        },
    )
    clock = now()
    source = work.root_source.model_dump(mode="json")
    with session(work) as s:
        policy_source = policy.assess(
            s, work.quality.ctx, work.setup.product, UUID(work.config["project"]), current.purpose
        )["sources"][0]
    sample = current.issue_snapshot["failures"][0]["sample"]
    payload = {
        "issue_id": str(work.issue_id),
        "expected_issue_revision": current.revision,
        "capa_id": str(work.capa_id),
        "origin": {
            "id": str(current.id),
            "revision": current.revision,
            "snapshot_sha256": current.snapshot_sha256,
        },
        "external_id": f"rule-{work.issue_id}",
        "policy_ref": policy_source,
        "method": source,
        "criterion": source,
        "sampling": {
            "targets": [
                {
                    "key": "actual-sample",
                    "kind": "sample",
                    "ref": {"id": sample["id"], "revision": sample["revision"]},
                    "actual_configuration": sample["actual_configuration"],
                    "identity_sources": [source],
                }
            ],
            "minimum_records": 1,
            "sampling_method": source,
            "acceptance": source,
            "observation_from": (clock - timedelta(minutes=2)).isoformat(),
            "observation_until": (clock - timedelta(minutes=1)).isoformat(),
            "require_named_review": True,
            "require_run_review": True,
            "require_disposition": True,
        },
        "rule_material": {"method": "synthetic explicit observation"},
        "independence_material": {"required": True},
        "valid_from": (clock - timedelta(minutes=5)).isoformat(),
        "valid_until": (clock + timedelta(hours=1)).isoformat(),
        "reason": "Actual registered synthetic rule publication",
        "visibility": "private",
        "sources": [source],
    }
    checked = fact_commands.RulePublicationInput.model_validate(payload)
    fields = set(payload) - {"issue_id", "expected_issue_revision", "capa_id", "reason", "sources"}
    # The declared original excludes its own locator; no recursive source hash.
    fields.add("previous")
    publication = {
        "schema_version": "pdos-capa-rule-publication-source-v1",
        "nature": "synthetic",
        "scope": current.issue_snapshot["scope"],
        "issue_id": str(work.issue_id),
        "capa_id": str(work.capa_id),
        "purpose": current.purpose,
        "material": checked.model_dump(mode="json", include=fields),
    }
    registered = artifact(
        work.quality, json.dumps(publication), "Actual synthetic rule publication"
    )
    publication_ref = exact_source(work, registered).model_dump(mode="json")
    # Actual complete material beyond the removed 20-source business cap.
    extra_refs = []
    for index in range(21):
        extra = artifact(
            work.quality, f"Synthetic fixed supporting material {index}", f"Rule support {index}"
        )
        extra_refs.append(exact_source(work, extra).model_dump(mode="json"))
    payload["sources"] = [source, publication_ref, *extra_refs]
    rule_command = cmd(work.quality, fact_commands.RULE_OPERATION, payload)
    with session(work) as s:
        checked = fact_commands.RulePublicationInput.model_validate(payload)
        prepared = prepare_fact(
            s, work.quality.ctx, work.setup.product, checked, host=runtime.host, new_write=True
        )
        rule_command["source_read_set"] = [
            r.model_dump(mode="json") for r in prepared.required_source_read_set
        ]
        fact_service._discard(runtime, prepared)
    assert len(rule_command["source_read_set"]) > 20
    with session(work) as s:
        rule_receipt = publish_rule(
            s,
            work.quality.ctx,
            Command.model_validate(rule_command),
            publisher=runtime.host.owner.publisher,
        )
        saved = s.get(RuleFact, UUID(rule_receipt["subject_id"]))
        atom = read_fact_atom(
            s,
            work.quality.ctx,
            work.setup.product,
            kind="rule",
            fact_id=saved.id,
            revision=saved.revision,
        )
        ref = assemble_fact(
            saved.fact_body,
            atom.atom,
            expected_payload_sha256=saved.payload_sha256,
        ).ref.model_dump(mode="json")
    before_replay = actual_counts(work)
    with session(work) as s:
        replay = publish_rule(
            s,
            work.quality.ctx,
            Command.model_validate(rule_command),
            publisher=runtime.host.owner.publisher,
        )
    assert replay["id"] == rule_receipt["id"] and actual_counts(work) == before_replay

    occurred = clock - timedelta(seconds=70)
    record = {
        "target_key": "actual-sample",
        "occurred_at": occurred.isoformat(),
        "original_timezone": "UTC",
        "raw_material": {"observation": "synthetic observation, no effectiveness conclusion"},
    }
    observation_original = {
        "schema_version": "pdos-capa-observation-source-v1",
        "nature": "synthetic",
        "scope": current.issue_snapshot["scope"],
        "issue_id": str(work.issue_id),
        "capa_id": str(work.capa_id),
        "purpose": current.purpose,
        "rule": ref,
        "record": record,
        "observed_from": payload["sampling"]["observation_from"],
        "observed_until": payload["sampling"]["observation_until"],
        "at": {"occurred_at": clock.isoformat(), "original_timezone": "UTC"},
    }
    original = artifact(
        work.quality, json.dumps(observation_original), "Actual structured synthetic observation"
    )
    observation_ref = exact_source(work, original).model_dump(mode="json")
    value = cmd(
        work.quality,
        fact_commands.OBSERVATION_OPERATION,
        {
            "issue_id": str(work.issue_id),
            "expected_issue_revision": current.revision,
            "capa_id": str(work.capa_id),
            "rule": ref,
            "target_keys": ["actual-sample"],
            "observed_from": observation_original["observed_from"],
            "observed_until": observation_original["observed_until"],
            "at": {**observation_original["at"], "source": observation_ref},
            "records": [{**record, "sources": [observation_ref]}],
            "coverage_sources": [source],
            "sources": [observation_ref],
            "reason": "Save original actual observation without deciding effectiveness",
            "visibility": "private",
        },
    )
    url = f"/v1/categories/{work.setup.category}/products/{work.setup.product}/capa-facts/inputs"
    response = work.quality.client.post(url, headers=work.quality.headers, json=value)
    assert response.status_code == 200, response.text
    value = response.json()["command"]
    observation_receipt, approved = accepted(work.quality, value)
    assert observation_receipt["subject_type"] == "capa_observation"
    assert fixed_issue(work).id == current.id
    base_path = f"/v1/categories/{work.setup.category}/products/{work.setup.product}"
    candidate_read = work.quality.client.get(
        f"{base_path}/capa-candidates",
        headers=work.quality.headers,
        params={"issue_id": str(work.issue_id)},
    )
    assert candidate_read.status_code == 200, candidate_read.text
    assert len(candidate_read.json()["candidates"]) == 1
    assert candidate_read.json()["history_page"] == {"next_cursor": None}
    fact_read = work.quality.client.get(
        f"{base_path}/capa-facts",
        headers=work.quality.headers,
        params={"issue_id": str(work.issue_id)},
    )
    assert fact_read.status_code == 200, fact_read.text
    assert [item["ref"] for item in fact_read.json()["rules"]] == [ref]
    assert len(fact_read.json()["history"]) == 2
    assert fact_read.json()["history_page"] == {"next_cursor": None}
    before = actual_counts(work)
    replay = post(work.quality, approved)
    assert replay.status_code == 200 and replay.json()["id"] == observation_receipt["id"]
    assert actual_counts(work) == before
    revoked = import_authority(
        work,
        "quality",
        "qualification",
        state="revoked",
        subject_id=str(work.quality.human),
        operations=operations,
        external_id=f"capa-fact-{work.issue_id}-qualification",
        previous_id=authority["qualification"]["subject_id"],
        expected_previous_revision=authority["qualification"]["subject_revision"],
    )
    assert revoked
    before = actual_counts(work)
    changed = deepcopy(value)
    changed["command_id"], changed["idempotency_key"] = str(uuid4()), str(uuid4())
    changed["payload"]["reason"] = "New observation after actual qualification withdrawal"
    denied = work.quality.client.post(url, headers=work.quality.headers, json=changed)
    assert denied.status_code == 403, denied.text
    assert denied.json()["code"] == "QUALIFICATION_REQUIRED"
    assert actual_counts(work) == before
