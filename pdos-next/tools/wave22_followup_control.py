"""Root-run followup controls; inert until one explicit phase/actual label.

No issuer installation, trusted Rule import, automatic Review or closure. Saved
source/report values and named clocks are selections, never qualification facts.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid5

RETEST_SHA = "9fe91ec4f140f9e039fa2428bebd7b8d6196a1f959b76eded388ed4d6ef81a6f"
FIXED_ANCHOR_SHA = "378a6b0c627c6d4fe2bc48cef10827c312c5e1f33b9ddcfe1620163243afbc5c"
PHASES = (
    "anchor-candidate",
    "rule-source",
    "observation-source",
    "observation",
    "link-current",
    "candidate",
    "review",
    "readback",
)


def layout_root(path):
    path = Path(path)
    if path.name != "wave22_followup_control.py":
        raise RuntimeError("Unexpected followup-control filename")
    if path.parent.name == "tools":
        return path.parent.parent
    if path.parent.name == "wave22-followup-control-staged" and path.parent.parent.name == ".local":
        return path.parents[2]
    raise RuntimeError("Unexpected followup-control layout")


ROOT = layout_root(Path(__file__).resolve())
CHECKPOINT = ROOT / ".local/wave22-followup-control.json"
PROFILE = ROOT / ".local/wave22-followup-rule-profile.json"
RULE_INPUT = ROOT / ".local/wave22-followup-rule-input.json"
PROMISE_SELECTION = ROOT / ".local/wave22-followup-promise-selection.json"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def retest_module():
    path = ROOT / "tools/wave22_shared_retest.py"
    if path.is_symlink() or not path.is_file() or sha(path) != RETEST_SHA:
        raise RuntimeError(
            "Exact actual bounded Retest dependency missing; no old generation fallback"
        )
    name = "wave22_followup_owned_retest"
    old = sys.modules.get(name)
    if old is not None:
        if Path(old.__file__).resolve() != path.resolve():
            raise RuntimeError("Retest module identity changed")
        return old
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


retest = retest_module()
first, Missing, Pending, Unknown = retest.first, retest.Missing, retest.Pending, retest.Unknown


def exact(raw, keys, schema):
    if type(raw) is not dict or set(raw) != keys or raw.get("schema_version") != schema:
        raise Missing("Exact explicit owned material schema required")
    return deepcopy(raw)


def fact_inputs(response, original):
    """Adapt only the actual successful fact inputs protocol, never a permission flag."""
    from pdos_next.contracts import Command

    if type(response) is not dict or set(response) != {"command", "review"}:
        raise Missing("Actual fact inputs command/review envelope required")
    command = Command.model_validate(response["command"]).model_dump(mode="json")
    expected = Command.model_validate(original).model_dump(mode="json")
    reads = command.pop("source_read_set")
    expected_reads = expected.pop("source_read_set")
    if command != expected or not isinstance(response["review"], dict):
        raise Missing("Actual inputs changed actor intent/key/body; no replacement")
    closed = first.helpers().merge_reads(reads)
    required = {(r["artifact_id"], r["expected_revision"]) for r in closed}
    if not {(r["artifact_id"], r["expected_revision"]) for r in expected_reads} <= required:
        raise Missing("Server full source closure must retain every original selected source")
    return {
        "operation": command["operation"],
        "allowed": True,  # local successful inputs shape, NOT a qualification claim
        "required_source_read_set": closed,
        "review": deepcopy(response["review"]),
    }


def full_ref(value):
    from pdos_next.domain.capa_effectiveness.facts import FactRef

    return FactRef.model_validate(value).model_dump(mode="json")


class FollowupControl(retest.SharedRetest):
    def __init__(self, marker, *, fresh_generation, confirm=None, review_digest=None, recover=None):
        sys.path[:0] = [str(ROOT / "server"), str(ROOT / "tools")]
        from local_environment import read_state, verified

        self.marker, self.read_state, self.verified = str(marker), read_state, verified
        self.confirm, self.review_digest, self.recover = confirm, review_digest, recover
        self.confirm_used = self.recover_used = False
        self.h = first.helpers()
        target = self.target()
        self.foundation = first.foundation_contract(
            first.private_json(first.FOUNDATION), self.marker
        )
        self.foundation_sha = first.digest_file(first.FOUNDATION)
        if len({self.actor(role) for role in ("maker", "observer", "independent_reviewer")}) != 3:
            raise Missing("Three distinct actual saved human principals required")
        self.foundation_binding_sha = first.build_foundation_binding(self.foundation, self.marker)
        build_raw = first.private_json(first.BUILD)
        self.build = first.build_contract(build_raw, self.foundation, self.foundation_binding_sha)
        self.build_sha = first.digest_file(first.BUILD)
        generation = str(UUID(fresh_generation))
        parent = retest.checkpoint_json(retest.CHECKPOINT)
        if (
            parent.get("schema_version") != "wave22-shared-retest-v3"
            or parent.get("marker") != self.marker
            or parent.get("source_mode") != "fresh"
            or parent.get("fresh_generation") != generation
            or parent.get("first_generation") is not None
            or parent.get("scope") != self.foundation["scope"]
            or parent.get("foundation_sha256") != self.foundation_sha
            or parent.get("build_sha256") != self.build_sha
            or self.foundation["tenant_id"] != target["preview_tenant_id"]
        ):
            raise Missing(
                "Exact shared completed Retest/fresh scope required; no default checkpoint"
            )
        required = {"issue", "capa", "root-cause", "complete"}
        if not required <= parent.get("receipts", {}).keys():
            raise Missing("Actual complete Root/CAPA receipts required before followup controls")
        self.namespace = str(uuid5(UUID(parent["case_id"]), "actual-followup-controls"))
        binding = {
            "schema_version": "wave22-followup-control-v1",
            "marker": self.marker,
            "scope": self.foundation["scope"],
            "fresh_generation": generation,
            "parent_case_id": parent["case_id"],
            "case_id": self.namespace,
            "foundation_sha256": self.foundation_sha,
            "build_sha256": self.build_sha,
            "issue_id": parent["issue_id"],
            "capa_id": parent["capa_id"],
            "capa_action_id": parent["capa_action_id"],
            "purpose": parent["purpose"],
            "build_id": parent["build_id"],
            "request_id": parent["request_id"],
            "run_id": parent["run_id"],
            "first_run_id": parent["first_run_id"],
            "retest_source_sha256": RETEST_SHA,
        }
        self.parent = parent  # immutable selections only; never write parent checkpoint
        if CHECKPOINT.exists() or CHECKPOINT.is_symlink():
            self.data = retest.checkpoint_json(CHECKPOINT)
            if any(self.data.get(k) != v for k, v in binding.items()):
                raise Missing("Saved followup scope/IDs/dependency changed")
        else:
            self.data = {
                **binding,
                "test_publication": deepcopy(parent["test_publication"]),
                "requests": {},
                "receipts": {},
                "events": {},
                "materials": {},
                "publications": {},
                "phase": "allocated_completed_origin_no_rule_or_review",
            }
            self.save()

    def actor(self, role):
        if role not in {"maker", "observer", "independent_reviewer"}:
            raise Missing("Exact shared actor role required")
        return self.foundation["actors"][role]["id"]

    def key(self, label, role="observer"):
        return f"wave22-followup-{self.namespace}-{role}-{label}"

    def save(self):
        if CHECKPOINT.is_symlink():
            raise Missing("Owned checkpoint symlink refused")
        retest.checkpoint_fits(self.data)
        self.h.private_write(CHECKPOINT, self.data)

    def request(self, role, method, path, *, body=None, params=None):
        value = super().request(role, method, path, body=body, params=params)
        if method == "POST" and path == f"/v1/products/{self.product}/capa-facts/inputs":
            return fact_inputs(value, body)
        return value

    def fixed_dependency(self):
        path = ROOT / "server/pdos_next/domain/capa_effectiveness/candidate_prepare.py"
        if sha(path) != FIXED_ANCHOR_SHA:
            raise Missing(
                "Actual fixed-anchor owner candidate not applied; no Rule/candidate workaround"
            )

    def host(self, role="maker", candidate_id=None):
        params = {"issue_id": self.data["issue_id"]}
        if candidate_id is not None:
            params["candidate_id"] = str(UUID(candidate_id))
        return self.request(role, "GET", f"/v1/products/{self.product}/capa-facts", params=params)

    def origin(self):
        self.fixed_dependency()
        row = self.completed()
        ref = self.data.get("fixed_origin")
        if ref is None:
            prepared = self.data.get("requests", {}).get("anchor-candidate")
            receipt = self.data.get("receipts", {}).get("anchor-candidate")
            if not prepared or not receipt or prepared["state"] != "saved":
                raise Missing("Actual first saved anchor candidate required before Rule")
            ref = deepcopy(prepared["preview"]["review"]["stable_anchor"]["origin"]["ref"])
            self.data["fixed_origin"] = ref
            self.save()
        from pdos_next.domain.capa_effectiveness.anchor import VersionRef
        from pdos_next.schemas.quality_issues.contracts import Issue
        from pdos_next.service import digest

        actual = VersionRef(
            id=row["id"],
            revision=row["revision"],
            snapshot_sha256=digest(Issue.model_validate(row["issue"]).model_dump(mode="json")),
        )
        if actual.model_dump(mode="json") != ref:
            raise Missing("Actual completed Current/original full Issue changed")
        return row, ref

    def anchor_candidate(self):
        self.fixed_dependency()

        def payload():
            row = self.completed()
            value = self.request(
                "maker",
                "GET",
                f"/v1/products/{self.product}/capa-candidates",
                params={"issue_id": self.data["issue_id"]},
            )["host"]
            if value.get("allowed") is not True:
                raise Missing("Actual candidate owner blocked; no permission default")
            return {
                "issue_id": self.data["issue_id"],
                "expected_issue_revision": row["revision"],
                "capa_id": self.data["capa_id"],
                "remediation_link_refs": [],
                "mappings": [],
                "sources": [],
                "reason": "Initial fixed anchor candidate; applicability/effectiveness unknown",
                "visibility": "product",
            }, self.reads(value["required_source_read_set"])

        self.step(
            "anchor-candidate",
            "maker",
            "quality.capa.verification.candidate.record",
            "capa_verification_candidate",
            payload,
            inputs="quality-followup/inputs",
        )
        self.origin()

    def material(self, label, path, keys, schema):
        raw = self.selected_material(label, path, keys)
        return exact(raw, keys, schema)

    def prepare_rule_source(self, material):
        from pdos_next.domain.capa_effectiveness.anchor import VersionRef
        from pdos_next.domain.capa_effectiveness.fact_commands import RulePublicationInput

        row, origin = self.origin()
        raw = self.material(
            "rule-source",
            material,
            {"schema_version", "payload", "issuer_key", "issuer_version", "include_promise"},
            "wave22-followup-rule-material-v1",
        )
        supplied = deepcopy(raw["payload"])
        for forbidden in (
            "issue_id",
            "expected_issue_revision",
            "capa_id",
            "origin",
            "visibility",
            "sources",
        ):
            if forbidden in supplied:
                raise Missing("Rule scope/anchor/source binding comes from actual saved owner")
        # Source references selected inside method/criterion/sampling remain exact.
        chosen = RulePublicationInput.model_validate(
            {
                **supplied,
                "issue_id": self.data["issue_id"],
                "expected_issue_revision": row["revision"],
                "capa_id": self.data["capa_id"],
                "origin": VersionRef.model_validate(origin),
                "sources": [supplied["method"]],
                "visibility": "product",
            }
        )
        until = chosen.sampling.observation_until
        if until < datetime.fromisoformat(
            row["issue"]["capa"]["requirement"]["observation_until"].replace("Z", "+00:00")
        ):
            raise Missing("Published Rule cannot shorten the actual CAPA observation requirement")
        actions = row["issue"]["capa"]["actions"]
        if not actions or any(value["completion"] is None for value in actions):
            raise Missing("Actual completion of every fixed CAPA action required for Rule")
        completed_at = max(
            datetime.fromisoformat(value["completion"]["at"]["occurred_at"].replace("Z", "+00:00"))
            for value in actions
        )
        if chosen.sampling.observation_from < completed_at:
            raise Missing("Fixed Rule observation interval cannot precede actual completion")
        references = [
            chosen.policy_ref,
            chosen.method,
            chosen.criterion,
            chosen.sampling.sampling_method,
            chosen.sampling.acceptance,
            *(source for target in chosen.sampling.targets for source in target.identity_sources),
        ]
        selected_reads = [
            {"artifact_id": str(source.id), "expected_revision": source.revision}
            for source in references
            if source.kind == "artifact"
        ]
        fields = {
            "origin",
            "previous",
            "external_id",
            "policy_ref",
            "method",
            "criterion",
            "sampling",
            "rule_material",
            "independence_material",
            "valid_from",
            "valid_until",
            "visibility",
        }
        publication = {
            "schema_version": "pdos-capa-rule-publication-source-v1",
            "nature": "synthetic",
            "scope": self.data["scope"],
            "issue_id": self.data["issue_id"],
            "capa_id": self.data["capa_id"],
            "purpose": self.data["purpose"],
            "material": chosen.model_dump(mode="json", include=fields),
        }
        rows = [publication]
        if type(raw["include_promise"]) is not bool:
            raise Missing("Explicit Promise document layout required")
        if raw["include_promise"]:
            _, request, run = self.current("verification-launch")
            if run is None or run["status"] != "planned":
                raise Missing("Actual second Plan required; cannot publish future Run identifiers")
            at = run["execution_plan"]["window"]["start"]
            first.promise_start(at, run["execution_plan"]["window"])
            rows.append(
                {
                    "request_id": self.data["request_id"],
                    "run_id": self.data["run_id"],
                    "purpose": self.data["purpose"],
                    "operation": "verification.schedule.promise",
                    "occurred_at": at,
                    "executor_id": self.actor("observer"),
                }
            )
        profile = {
            "tenant_id": self.foundation["tenant_id"],
            "product_id": self.product,
            "project_id": self.foundation["project_id"],
            "issuer_key": raw["issuer_key"],
            "issuer_version": raw["issuer_version"],
        }
        from pdos_next.capa_rule_publisher import _profile

        _profile(profile)
        return {
            "rows": rows,
            "chosen": chosen.model_dump(mode="json"),
            "profile": profile,
            "reads": self.reads(row["required_source_read_set"], selected_reads),
            "native_payload": {
                "title": "Shared fixed Rule and prospective Promise declaration",
                "content": "\n".join(self.h.canonical(v) for v in rows),
                "source_label": "Synthetic publication; no physical efficacy or saved Promise",
                "visibility": "product",
            },
        }

    def publication(self, label, role, blueprint_factory):
        """Freeze selections before preview; a saved original always precedes fresh IO.

        This is an immutable command blueprint, never a positive owner/cache gate.
        The separate fact command/import later repeats its real current guards.
        """
        publications = self.data.setdefault("publications", {})
        old = publications.get(label)
        if old is None:
            if label in self.data["requests"] or label in self.data["receipts"]:
                raise Missing("Original publication has no exact frozen blueprint")
            value = blueprint_factory()
            old = {"value": deepcopy(value), "sha256": first.value_sha(value)}
            publications[label] = old
            self.save()
        if set(old) != {"value", "sha256"} or first.value_sha(old["value"]) != old["sha256"]:
            raise Missing("Frozen publication blueprint changed")
        blueprint = deepcopy(old["value"])
        receipt = self.step(
            label,
            role,
            "evidence.artifact.register",
            "artifact",
            lambda: (deepcopy(blueprint["native_payload"]), deepcopy(blueprint["reads"])),
        )
        from pdos_next.contracts import PAYLOADS

        original = self.data["requests"][label]["original"]
        actual_payload = (
            PAYLOADS["evidence.artifact.register"]
            .model_validate(blueprint["native_payload"])
            .model_dump(mode="json", exclude_none=True)
        )
        if (
            original["payload"] != actual_payload
            or original["source_read_set"] != blueprint["reads"]
        ):
            raise Missing("Original native command differs from exact saved blueprint")
        refs = [
            {
                "artifact_id": receipt["subject_id"],
                "expected_revision": receipt["subject_revision"],
                "line": n,
                "quote": self.h.canonical(value),
            }
            for n, value in enumerate(blueprint["rows"], 1)
        ]
        return blueprint, receipt, refs

    def rule_source(self, *, material=None):
        from pdos_next.domain.capa_effectiveness.fact_commands import RulePublicationInput

        blueprint, receipt, refs = self.publication(
            "rule-publication", "maker", lambda: self.prepare_rule_source(material)
        )
        payload = RulePublicationInput.model_validate(
            {**blueprint["chosen"], "sources": [retest.source_ref(refs[0])]}
        ).model_dump(mode="json")
        profile = blueprint["profile"]
        packet = {
            "schema_version": "wave22-followup-rule-host-input-v1",
            "scope": self.data["scope"],
            "actor_id": self.actor("maker"),
            "command_id": str(uuid5(UUID(self.namespace), "maker:trusted-rule-import")),
            "idempotency_key": self.key("trusted-rule-import", "maker"),
            "payload": payload,
            "proposed_source_read_set": self.reads(
                blueprint["reads"],
                [
                    {
                        "artifact_id": refs[0]["artifact_id"],
                        "expected_revision": refs[0]["expected_revision"],
                    }
                ],
            ),
            "server_prepare_full_read_set_required": True,
            "no_public_endpoint": True,
        }
        self.export(PROFILE, profile)
        self.export(RULE_INPUT, packet)
        if len(refs) == 2:
            self.export(PROMISE_SELECTION, {"reference": refs[1], "publisher_role": "maker"})
        self.data["rule_publication"] = {
            "receipt": receipt,
            "reference": refs[0],
            "profile_sha256": sha(PROFILE),
            "host_input_sha256": sha(RULE_INPUT),
        }
        self.data["phase"] = "actual_rule_source_saved_host_install_import_required"
        self.save()

    def export(self, path, value):
        if path.exists() or path.is_symlink():
            if first.private_json(path) != value:
                raise Missing("Owned frozen export changed; no overwrite")
            return
        self.h.private_write(path, value)

    def prepare_observation_source(self, material):
        from pdos_next.domain.capa_effectiveness.fact_commands import ObservationPayload

        row, _ = self.origin()
        host = self.host("observer")
        rules = host.get("rules", [])
        if len(rules) != 1:
            raise Missing("One actual current trusted Rule required")
        raw = self.material(
            "observation-source",
            material,
            {
                "schema_version",
                "records",
                "observed_from",
                "observed_until",
                "at",
                "named_run_conclusions",
            },
            "wave22-followup-observation-material-v1",
        )
        if type(raw["at"]) is not dict or set(raw["at"]) != {"occurred_at", "original_timezone"}:
            raise Missing("Exact observed clock metadata required; source is actual publication")
        rule = full_ref(rules[0]["ref"])
        existing = self.data["rule_publication"]["reference"]
        seed = retest.source_ref(existing)
        # This placeholder is only for strict event/record shape validation; it
        # is replaced with the actual saved document ref before any API command.
        records = []
        for record in raw["records"]:
            if set(record) != {"target_key", "occurred_at", "original_timezone", "raw_material"}:
                raise Missing("Exact actual original observation record input required")
            records.append({**record, "sources": [seed]})
        payload = ObservationPayload.model_validate(
            {
                "issue_id": self.data["issue_id"],
                "expected_issue_revision": row["revision"],
                "capa_id": self.data["capa_id"],
                "rule": rule,
                "previous": rules[0]["previous"],
                "target_keys": [v["target_key"] for v in records],
                "observed_from": raw["observed_from"],
                "observed_until": raw["observed_until"],
                "at": {**raw["at"], "source": seed},
                "records": records,
                "coverage_sources": [seed],
                "sources": [seed],
                "reason": "Actual original records; completeness remains owner-evaluated",
                "visibility": "product",
            }
        )
        first.aware_past(payload.at.occurred_at.isoformat())
        rows = []
        for record in payload.records:
            value = record.model_dump(mode="json", exclude={"sources"})
            rows.append(
                {
                    "schema_version": "pdos-capa-observation-source-v1",
                    "nature": "synthetic",
                    "scope": self.data["scope"],
                    "issue_id": self.data["issue_id"],
                    "capa_id": self.data["capa_id"],
                    "purpose": self.data["purpose"],
                    "rule": rule,
                    "record": value,
                    "observed_from": payload.observed_from.isoformat(),
                    "observed_until": payload.observed_until.isoformat(),
                    "at": {
                        "occurred_at": payload.at.occurred_at.isoformat(),
                        "original_timezone": payload.at.original_timezone,
                    },
                }
            )
        named = raw["named_run_conclusions"]
        if named is not None:
            if set(named) != {"review_at", "review_text", "disposition_at", "disposition_text"}:
                raise Missing("Exact actual named Run conclusions required")
            _, request, run = self.current("verification-results")
            projection = run.get("current_projection") if run else None
            if not run or not projection or projection["basis_sha256"] != run["basis_sha256"]:
                raise Missing("Actual Compute required before any eight-field named conclusion")
            for label, operation in (
                ("review", "test.run.review"),
                ("disposition", "test.disposition.decide"),
            ):
                first.aware_past(named[label + "_at"])
                rows.append(
                    {
                        "request_id": self.data["request_id"],
                        "run_id": self.data["run_id"],
                        "purpose": self.data["purpose"],
                        "operation": operation,
                        "actor_id": self.actor("observer"),
                        "occurred_at": named[label + "_at"],
                        "text": named[label + "_text"],
                        "basis_sha256": run["basis_sha256"],
                    }
                )
        return {
            "rows": rows,
            "chosen": payload.model_dump(mode="json", exclude={"confirmation_token"}),
            "record_count": len(records),
            "named": deepcopy(named),
            "reads": self.reads(
                host["operations"]["quality.capa.observation.record"]["required_source_read_set"]
            ),
            "native_payload": {
                "title": "Shared actual observation and already-formed named Run proposals",
                "content": "\n".join(self.h.canonical(value) for value in rows),
                "source_label": "Synthetic system observation; raw metadata, no physical proof",
                "visibility": "product",
            },
        }

    def observation_source(self, *, material=None):
        from pdos_next.domain.capa_effectiveness.fact_commands import ObservationPayload

        blueprint, _, refs = self.publication(
            "observation-publication", "maker", lambda: self.prepare_observation_source(material)
        )
        count = blueprint["record_count"]
        named = blueprint["named"]
        data = deepcopy(blueprint["chosen"])
        for record, ref in zip(data["records"], refs[:count], strict=True):
            record["sources"] = [retest.source_ref(ref)]
        data["at"]["source"] = retest.source_ref(refs[0])
        data["coverage_sources"] = [retest.source_ref(refs[0])]
        data["sources"] = [retest.source_ref(v) for v in refs[:count]]
        self.data["observation_payload"] = ObservationPayload.model_validate(data).model_dump(
            mode="json", exclude={"confirmation_token"}
        )
        if named is not None:
            output = {**named, "event_sources": refs[count:]}
            self.export(ROOT / ".local/wave22-followup-run-conclusions.json", output)
        self.data["phase"] = "actual_observation_source_saved_not_observation_or_review"
        self.save()

    def observation(self):
        if "observation_payload" not in self.data:
            raise Missing("Actual observed source must be saved first")

        def payload():
            host = self.host("observer")
            op = host["operations"]["quality.capa.observation.record"]
            if op["allowed"] is not True:
                raise Missing("Actual observation operation blocked")
            return deepcopy(self.data["observation_payload"]), self.reads(
                op["required_source_read_set"]
            )

        self.step(
            "observation",
            "observer",
            "quality.capa.observation.record",
            "capa_observation",
            payload,
            inputs="capa-facts/inputs",
        )
        self.data["phase"] = "actual_observation_saved_no_independent_review"
        self.save()

    def link_current(self):
        def payload():
            self.origin()
            view = self.request(
                "maker",
                "GET",
                f"/v1/products/{self.product}/quality-followup",
                params={"issue_id": self.data["issue_id"]},
            )
            _, request, run = self.current("verification-results", role="maker")
            if (
                run is None
                or run["run_snapshot"]["professional_conclusion"] is None
                or run["run_snapshot"]["disposition"] is None
            ):
                raise Missing(
                    "Actual second Run named review/disposition required for Current link"
                )
            options = [
                value
                for value in view["output_options"]
                if value.get("logical_id") == self.data["request_id"]
                and value["ref"]["kind"] == "verification_request"
                and value["ref"]["id"] == request["id"]
                and value["ref"]["revision"] == request["revision"]
            ]
            if len(options) != 1:
                raise Missing("Actual paired Current owner output missing; no old Draft fallback")
            return {
                "issue_id": self.data["issue_id"],
                "expected_issue_revision": view["current"]["revision"],
                "capa_id": self.data["capa_id"],
                "action_id": self.data["capa_action_id"],
                "output_refs": [options[0]["ref"]],
                "sources": [],
                "reason": "Actual paired Current output; effectiveness and close remain unassessed",
            }, self.reads(
                view["required_source_read_set"], options[0].get("required_source_read_set", [])
            )

        self.step(
            "link-current",
            "maker",
            "quality.capa.followup.link",
            "capa_remediation_link",
            payload,
            inputs="quality-followup/inputs",
        )
        self.data["phase"] = "actual_current_link_saved_no_independent_review"
        self.save()

    def candidate(self, *, material=None):
        raw = self.material(
            "candidate",
            material,
            {"schema_version", "reason", "remediation_link_refs", "mappings", "sources"},
            "wave22-followup-candidate-material-v1",
        )

        def payload():
            row, _ = self.origin()
            host = self.request(
                "maker",
                "GET",
                f"/v1/products/{self.product}/capa-candidates",
                params={"issue_id": self.data["issue_id"]},
            )["host"]
            available = {v["ref"]["id"]: v["ref"] for v in host["materials"]["links"]}
            if (
                host["allowed"] is not True
                or not raw["mappings"]
                or not raw["remediation_link_refs"]
            ):
                raise Missing(
                    "Actual completed mappings/current Link required; no empty full candidate"
                )
            if any(available.get(v["id"]) != v for v in raw["remediation_link_refs"]):
                raise Missing("Only actual currently rechecked fixed Link options may be selected")
            return {
                "issue_id": self.data["issue_id"],
                "expected_issue_revision": row["revision"],
                "capa_id": self.data["capa_id"],
                "reason": raw["reason"],
                "remediation_link_refs": raw["remediation_link_refs"],
                "mappings": raw["mappings"],
                "sources": raw["sources"],
                "visibility": "product",
            }, self.reads(host["required_source_read_set"])

        self.step(
            "candidate",
            "maker",
            "quality.capa.verification.candidate.record",
            "capa_verification_candidate",
            payload,
            inputs="quality-followup/inputs",
        )

    def review(self, *, material=None):
        raw = self.material(
            "review",
            material,
            {
                "schema_version",
                "at",
                "pair_applicability",
                "action_fulfillment",
                "conclusion",
                "sources",
                "reason",
            },
            "wave22-followup-review-material-v1",
        )

        def payload():
            row, _ = self.origin()
            receipt = self.data["receipts"].get("candidate")
            if receipt is None:
                raise Missing("Actual full mapped Candidate receipt required")
            host = self.host("independent_reviewer", receipt["subject_id"])
            op = host["operations"]["quality.capa.verification.review"]
            if op["allowed"] is not True:
                raise Missing("Actual independent reviewer qualification/paired/coverage blocked")
            selected = host.get("candidate")
            if (
                not selected
                or selected["id"] != receipt["subject_id"]
                or len(host["rules"]) != 1
                or not host["observations"]
            ):
                raise Missing("Actual exact Candidate/Rule/ordered observations required")
            first.aware_past(raw["at"]["occurred_at"])
            return {
                "issue_id": self.data["issue_id"],
                "expected_issue_revision": row["revision"],
                "capa_id": self.data["capa_id"],
                "candidate": full_ref(selected),
                "rule": full_ref(host["rules"][0]["ref"]),
                "observations": [full_ref(v) for v in host["observations"]],
                "at": raw["at"],
                "pair_applicability": raw["pair_applicability"],
                "action_fulfillment": raw["action_fulfillment"],
                "conclusion": raw["conclusion"],
                "sources": raw["sources"],
                "reason": raw["reason"],
                "visibility": "product",
            }, self.reads(op["required_source_read_set"])

        self.step(
            "independent-review",
            "independent_reviewer",
            "quality.capa.verification.review",
            "capa_named_verification_review",
            payload,
            inputs="capa-facts/inputs",
        )
        self.data["phase"] = "actual_independent_named_review_saved_no_effectiveness_or_close"
        self.save()

    def readback(self):
        row, _ = self.origin()
        host = self.host(
            "independent_reviewer",
            self.data.get("receipts", {}).get("candidate", {}).get("subject_id"),
        )
        if (
            row["issue"]["capa"].get("effectiveness") is not None
            or row["issue"].get("closure") is not None
        ):
            raise Missing("This driver cannot advance effectiveness/close")
        actual = {v["ref"]["id"]: v for v in host["history"]}
        for label, kind in (("observation", "observation"), ("independent-review", "review")):
            receipt = self.data["receipts"].get(label)
            if receipt and (
                receipt["subject_id"] not in actual or actual[receipt["subject_id"]]["kind"] != kind
            ):
                raise Missing("Saved actual fact missing from immutable owner history")
        self.data["readback"] = {
            "checked_at": datetime.now(UTC).isoformat(),
            "fact_refs": [v["ref"] for v in host["history"]],
            "current_issue_revision": row["revision"],
            "source_count": len(
                self.reads(*(v["required_source_read_set"] for v in host["operations"].values()))
            ),
            "effectiveness": None,
            "close": False,
        }
        self.save()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--marker", required=True)
    parser.add_argument("--fresh-generation", required=True)
    parser.add_argument("--phase", choices=PHASES, required=True)
    parser.add_argument("--material", type=Path)
    parser.add_argument("--confirm")
    parser.add_argument("--review-digest")
    parser.add_argument("--recover")
    args = parser.parse_args()
    control = None
    try:
        control = FollowupControl(
            args.marker,
            fresh_generation=args.fresh_generation,
            confirm=args.confirm,
            review_digest=args.review_digest,
            recover=args.recover,
        )
        method = getattr(control, args.phase.replace("-", "_"))
        if args.phase in {"rule-source", "observation-source", "candidate", "review"}:
            method(material=args.material)
        else:
            method()
    except Pending as pending:
        saved = control.data["requests"][pending.label]
        print(
            json.dumps(
                {
                    "state": "awaiting_confirmation",
                    "label": pending.label,
                    "tier": saved["tier"],
                    "review_digest": saved["review_digest"],
                }
            )
        )
        return 2
    except Unknown as unknown:
        print(
            json.dumps({"state": "unknown", "label": unknown.label, "same_original_required": True})
        )
        return 2
    except Missing as error:
        print(json.dumps({"state": "blocked", "reason": str(error), "no_replacement": True}))
        return 2
    except ValueError:
        print(json.dumps({"state": "blocked", "reason": "Explicit typed material invalid"}))
        return 2
    except first.helpers().GuardedRequestError as error:
        print(json.dumps({"state": "rejected", "status": error.status, "code": error.code}))
        return 2
    print(
        json.dumps(
            {
                "phase": control.data["phase"],
                "saved_labels": sorted(control.data["receipts"]),
                "effectiveness": None,
                "close": False,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
