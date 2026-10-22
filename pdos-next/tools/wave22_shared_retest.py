"""Inert new shared remediation/second Run driver; Root alone runs explicit phases.

Original FirstRun/checkpoints are read only. No profile installation or automatic
Rule, Observation, Candidate, NamedReview, effectiveness, closure or release.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid5

FIRST_SOURCE_SHA = "e1613219fec3fd4ff8b6c954c3f023905a5290499ac47bb3240d40a8230e9659"
FRESH_SOURCE_SHA = "61a4ff4c0aab80485c6018b1bdb791daea5dba26d0a494b2bd33242ff8257c14"


def layout_root(path):
    path = Path(path).resolve()
    if path.name != "wave22_shared_retest.py":
        raise RuntimeError("Unexpected followup tool filename")
    if path.parent.name == "tools":
        return path.parent.parent
    if path.parent.name == "wave22-retest-staged" and path.parent.parent.name == ".local":
        return path.parents[2]
    if (
        path.parent.name in {"v2", "v3"}
        and path.parent.parent.name == "wave22-retest-staged"
        and path.parents[2].name == ".local"
    ):
        return path.parents[3]
    raise RuntimeError("Unexpected followup tool layout")


ROOT = layout_root(__file__)
CHECKPOINT = ROOT / ".local/wave22-shared-retest.json"
RESOURCE_PROFILE = ROOT / ".local/wave22-shared-retest-resource-profile.json"
RESOURCE_INPUT = ROOT / ".local/wave22-shared-retest-resource-input.json"
COMPLETION_PROFILE = ROOT / ".local/wave22-shared-retest-completion-profile.json"


def first_module():
    staged = Path(__file__).resolve().parent.name != "tools"
    source = (
        (ROOT / ".local/wave22-test-staged/v4/wave22_shared_test.py")
        if staged
        else (ROOT / "tools/wave22_shared_test.py")
    )
    if source.is_symlink() or hashlib.sha256(source.read_bytes()).hexdigest() != FIRST_SOURCE_SHA:
        raise RuntimeError("Exact frozen FirstRun v4 dependency required")
    spec = importlib.util.spec_from_file_location("wave22_retest_isolated_first_helpers", source)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    # Inherited methods use this object's overridden save/resources/step. Keep
    # the first module's original constants intact for its real origin seal.
    return module


first = first_module()
Missing, Pending, Unknown = first.Missing, first.Pending, first.Unknown


def source_ref(reference):
    from pdos_next.domain.configurations.schemas import DefinitionReference

    ref = DefinitionReference.model_validate(reference).model_dump(mode="json")
    return {
        "id": ref["artifact_id"],
        "revision": ref["expected_revision"],
        "kind": "artifact",
        "position": f"line:{ref['line']};quote_sha256:"
        + hashlib.sha256(ref["quote"].encode()).hexdigest(),
    }


def fresh_module():
    staged = Path(__file__).resolve().parent.name != "tools"
    source = ROOT / (
        ".local/wave22-fresh-request-staged/wave22_shared_fresh_request.py"
        if staged
        else "tools/wave22_shared_fresh_request.py"
    )
    if source.is_symlink() or hashlib.sha256(source.read_bytes()).hexdigest() != FRESH_SOURCE_SHA:
        raise Missing("Exact frozen fresh-request v1 dependency required; no old-source fallback")
    spec = importlib.util.spec_from_file_location("wave22_retest_isolated_fresh_helpers", source)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def canonical_generation(generation, flag):
    if type(generation) is not str:
        raise Missing(f"Explicit canonical {flag} UUID required; no default fallback")
    try:
        parsed = UUID(generation)
    except ValueError:
        raise Missing(f"Explicit canonical {flag} UUID required; no default fallback") from None
    if str(parsed) != generation:
        raise Missing(f"Explicit canonical {flag} UUID required; no default fallback")
    return generation


def selected_first_paths(generation):
    return first.generation_paths(canonical_generation(generation, "--first-generation"))


def selected_source(*, first_generation=None, fresh_generation=None):
    if (first_generation is None) == (fresh_generation is None):
        raise Missing("Exactly one explicit --first-generation or --fresh-generation required")
    if first_generation is not None:
        return "first", first_generation, selected_first_paths(first_generation), None
    generation = canonical_generation(fresh_generation, "--fresh-generation")
    helper = fresh_module()
    return "fresh", generation, helper.fresh_paths(generation), helper


def first_contract(data, foundation, build, *, generation, source_mode="first"):
    # The branch comes from an explicit server-tool argument, never inferred from
    # a checkpoint's schema, status or the presence of another default file.
    canonical_generation(generation, "selected-generation")
    if source_mode not in {"first", "fresh"}:
        raise Missing("Exact selected source mode required")
    reading = data.get("result_readback", {})
    computed = data.get("receipts", {}).get("compute", {})
    selected = data.get("prospective_generation", {})
    if source_mode == "first":
        selection_matches = (
            data.get("schema_version") == "wave22-shared-test-v1"
            and selected.get("id") == generation
            and selected.get("material", {}).get("generation") == generation
        )
        run_label = "original:run"
    else:
        selected = data.get("selection", {})
        archive = data.get("origin_archive")
        selection_matches = (
            data.get("schema_version") == "wave22-shared-fresh-request-v1"
            and data.get("generation") == generation
            and data.get("case_id") == generation
            and selected.get("generation") == generation
            and selected.get("scope") == foundation["scope"]
            and selected.get("purpose") == foundation["purpose"]
            and selected.get("build_id") == build["build"]["id"]
            and selected.get("sample_id") == data.get("original_sample_id")
            and type(archive) is dict
            and archive.get("run_id") != data.get("run_id")
        )
        run_label = "fresh:run"
    if (
        not selection_matches
        or data.get("phase") != "actual_original_definite_fail_no_issue_or_review"
        or data.get("run_id") != str(uuid5(UUID(generation), run_label))
        or data.get("scope") != foundation["scope"]
        or data.get("purpose") != foundation["purpose"]
        or data.get("build_id") != build["build"]["id"]
        or data.get("original_sample_id") == data.get("followup_sample_id")
        or [data.get("original_sample_id"), data.get("followup_sample_id")]
        != [s["id"] for s in build["samples"]]
        or reading.get("result") != "fail"
        or reading.get("run_id") != data.get("run_id")
        or reading.get("projection", {}).get("id") != computed.get("subject_id")
        or reading.get("projection", {}).get("revision") != computed.get("subject_revision")
        or reading.get("projection", {}).get("result") != "fail"
        or reading.get("projection", {}).get("basis_sha256") is None
        or type(reading.get("run_revision")) is not int
        or reading["run_revision"] < 1
        or not reading.get("run_version_id")
        or not reading.get("request_version_id")
        or type(reading.get("request_revision")) is not int
        or reading["request_revision"] < 1
        or reading.get("report_sha256") != data.get("report_sha256")
        or not data.get("report_sha256")
        or not all(k in data.get("receipts", {}) for k in ("results", "run-start", "compute"))
    ):
        raise Missing("Actual new shared FirstRun saved definite-fail projection required")
    return data


def read_selected_origin(data, *, source_mode, fresh_helper=None):
    """Use the actual frozen source owner's file seal, never its live constructor."""
    if source_mode == "first":
        original = first.SharedTest.__new__(first.SharedTest)
        original.data = data
        original._origin_files(data["prospective_generation"])
        return
    if source_mode != "fresh" or fresh_helper is None:
        raise Missing("Fresh source requires its exact selected owner helper")
    owner = fresh_helper.SharedFreshRequest.__new__(fresh_helper.SharedFreshRequest)
    owner.selection = data["selection"]
    (
        owner.first_checkpoint,
        owner.first_profile_path,
        owner.first_resource_input_path,
    ) = fresh_helper.first.generation_paths(owner.selection["source_generation"])
    owner.first_data = data["origin_archive"]
    owner.foundation_sha = data["foundation_sha256"]
    owner.build_sha = data["build_sha256"]
    # This rereads the saved old Plan/Promise/archive, exact exports and Root's
    # actual readback/decision files. It has no target/HTTP/DB initialization.
    owner.origin_guard()


def retained_resource_profile(original, raw, scope):
    """One exact scope, same issuer identity, full finite old ledger plus new declarations."""
    from pdos_next.test_resource_bootstrap import _profile

    keys = {"tenant_id", "product_id", "issuer_key", "issuer_version", "decisions"}
    if (
        type(original) is not dict
        or set(original) != keys
        or original["tenant_id"] != scope["tenant_id"]
        or original["product_id"] != scope["product_id"]
        or original["issuer_version"] != "v2"
    ):
        raise Missing("Actual same-scope first-generation issuer identity required")
    profile = deepcopy(original)
    profile["decisions"] += [
        {"binding": raw["binding"], "resource": r["resource"], "decision": d}
        for r in raw["resources"]
        for d in r["facts"]
    ]
    # Parse actual bootstrap DTOs only; no target/issuer/qualification changes.
    _profile(
        {k: profile[k] for k in ("tenant_id", "product_id", "decisions")}, strict_material=True
    )
    return profile


CHECKPOINT_MAX_BYTES = 8 * 1024 * 1024


def checkpoint_json(path):
    """Only internal complete history gets the larger finite private-file bound."""
    return first.private_json(path, limit=CHECKPOINT_MAX_BYTES)


def checkpoint_fits(value):
    encoded = json.dumps(value, ensure_ascii=False, indent=2, default=first.helpers().encode) + "\n"
    if len(encoded.encode()) > CHECKPOINT_MAX_BYTES:
        raise Missing("Complete checkpoint exceeds fixed 8 MiB bound; retain original")


class SharedRetest(first.SharedTest):
    def __init__(
        self,
        marker,
        *,
        first_generation=None,
        fresh_generation=None,
        confirm=None,
        review_digest=None,
        recover=None,
    ):
        source_mode, generation, source_paths, fresh_helper = selected_source(
            first_generation=first_generation, fresh_generation=fresh_generation
        )
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
        self.foundation_binding_sha = first.build_foundation_binding(self.foundation, self.marker)
        build_raw = first.private_json(first.BUILD)
        self.build = first.build_contract(build_raw, self.foundation, self.foundation_binding_sha)
        self.build_case_id, self.build_sha = build_raw["case_id"], first.digest_file(first.BUILD)
        self.first_generation, self.fresh_generation = first_generation, fresh_generation
        self.source_mode = source_mode
        self.first_checkpoint, self.first_profile_path, self.first_resource_input_path = (
            source_paths
        )
        self.first_data = first_contract(
            checkpoint_json(self.first_checkpoint),
            self.foundation,
            self.build,
            generation=generation,
            source_mode=source_mode,
        )
        read_selected_origin(self.first_data, source_mode=source_mode, fresh_helper=fresh_helper)
        self.first_profile = first.private_json(self.first_profile_path)
        self.first_profile_sha = first.digest_file(self.first_profile_path)
        first_input = first.private_json(self.first_resource_input_path)
        if first_input != self.first_data.get("resource_input"):
            raise Missing("First-generation resource export must be complete and exact")
        first_entries = [
            {"binding": first_input["binding"], "resource": r["resource"], "decision": d}
            for r in first_input["resources"]
            for d in r["facts"]
        ]
        if any(entry not in self.first_profile.get("decisions", []) for entry in first_entries):
            raise Missing("First-generation actual finite ledger must retain every saved decision")
        self.first_sha = first.digest_file(self.first_checkpoint)
        self.namespace = str(uuid5(UUID(generation), "shared-followup-second-run"))
        if self.foundation["tenant_id"] != target["preview_tenant_id"]:
            raise Missing("Actual target tenant mismatch")
        binding = {
            "schema_version": "wave22-shared-retest-v3",
            "marker": self.marker,
            "scope": self.foundation["scope"],
            "foundation_sha256": self.foundation_sha,
            "build_sha256": self.build_sha,
            "build_case_id": self.build_case_id,
            "build_foundation_sha256": self.foundation_binding_sha,
            "first_run_checkpoint_sha256": self.first_sha,
            "source_mode": source_mode,
            "first_generation": first_generation,
            "fresh_generation": fresh_generation,
            "first_source_sha256": FIRST_SOURCE_SHA,
            "fresh_source_sha256": FRESH_SOURCE_SHA if source_mode == "fresh" else None,
            "first_resource_profile_sha256": self.first_profile_sha,
            "first_resource_input_sha256": first.digest_file(self.first_resource_input_path),
            "case_id": self.namespace,
        }
        if CHECKPOINT.exists() or CHECKPOINT.is_symlink():
            self.data = checkpoint_json(CHECKPOINT)
            if any(self.data.get(k) != v for k, v in binding.items()):
                raise Missing("Original followup inputs or namespace changed; no new intent")
        else:
            self.data = {
                **binding,
                "purpose": self.foundation["purpose"],
                "build_id": self.first_data["build_id"],
                "first_run_id": self.first_data["run_id"],
                "first_request_id": self.first_data["request_id"],
                "preparation_request_id": str(uuid5(UUID(self.namespace), "second:preparation")),
                "request_id": str(uuid5(UUID(self.namespace), "second:formal")),
                "run_id": str(uuid5(UUID(self.namespace), "second:run")),
                "test_equipment_id": self.first_data["test_equipment_id"],
                "original_sample_id": self.first_data["followup_sample_id"],
                "followup_sample_id": self.first_data["original_sample_id"],
                "capa_id": str(uuid5(UUID(self.namespace), "capa")),
                "capa_action_id": str(uuid5(UUID(self.namespace), "capa-action")),
                "test_publication": deepcopy(self.first_data["test_publication"]),
                "publication_receipt": deepcopy(self.first_data["publication_receipt"]),
                "requests": {},
                "receipts": {},
                "events": {},
                "materials": {},
                "phase": "allocated_no_issue_or_second_run",
            }
            self.save()
        if (
            self.data["run_id"] == self.first_data["run_id"]
            or self.data["request_id"] == self.first_data["request_id"]
        ):
            raise Missing("Followup must be a distinct real logical Request and Run")

    def key(self, label, role="observer"):
        return f"wave22-retest-{self.namespace}-{role}-{label}"

    def save(self):
        if CHECKPOINT.is_symlink():
            raise Missing("New followup checkpoint symlink refused")
        checkpoint_fits(self.data)
        self.h.private_write(CHECKPOINT, self.data)

    def selected_material(self, label, path, keys):
        old = self.data["materials"].get(label)
        raw = first.private_json(path) if path is not None else deepcopy(old)
        if type(raw) is not dict or set(raw) != set(keys):
            raise Missing("Exact explicit followup material required")
        if old is not None and self.h.canonical(old) != self.h.canonical(raw):
            raise Missing("Original fixed followup material cannot change")
        if old is None:
            self.data["materials"][label] = raw
            self.save()
        return raw

    def source_budget(self):
        """Describe complete saved read declarations; never attest current availability."""
        groups = [
            self.foundation["sources"]["foundation"]["required_source_read_set"],
            self.build["required_source_read_set"],
            self.first_data["result_readback"]["required_source_read_set"],
            *[
                r["original"]["source_read_set"]
                for r in self.data["requests"].values()
                if "original" in r
            ],
        ]
        groups.extend(
            [{"artifact_id": r["subject_id"], "expected_revision": r["subject_revision"]}]
            for r in self.data["receipts"].values()
            if r.get("operation") == "evidence.artifact.register"
            and r.get("subject_type") == "artifact"
        )
        groups.append(self.data.get("capture", {}).get("required_source_read_set", []))
        groups.append(self.data.get("selected_native_source_reads", []))
        complete = self.h.merge_reads(*groups)
        return {
            "state": "saved_source_declarations_not_current_qualification",
            "source_count": len(complete),
            "remaining_until_limit": 20 - len(complete),
            "not_yet_saved_required_event_or_report_groups": [
                label
                for label in (
                    "event-handoff",
                    "event-promise",
                    "event-start",
                    "report-upload",
                    "event-return",
                    "event-named-conclusions",
                )
                if label not in self.data["receipts"] and label not in self.data
            ],
            "complete_current_owner_reads_still_required": True,
            "named_review_effectiveness_and_close_available": False,
        }

    def quality(self, *, material=None):
        raw = self.selected_material(
            "issue",
            material,
            {
                "title",
                "hypothesis",
                "action_text",
                "requirement_method",
                "requirement_acceptance",
                "observation_until",
                "sources",
            },
        )
        refs = [source_ref(v) for v in raw["sources"]]
        source_reads = [{"artifact_id": v["id"], "expected_revision": v["revision"]} for v in refs]
        if not refs:
            raise Missing("Actual full hypothesis/requirement sources required")

        def create():
            view = self.request(
                "maker",
                "GET",
                f"/v1/products/{self.product}/quality-execution",
                params={"run_id": self.first_data["run_id"], "build_id": self.data["build_id"]},
            )
            failures = [
                v
                for v in view["failures"]
                if v["available"] and v["failure"]["run"]["id"] == self.first_data["run_id"]
            ]
            if len(failures) != 1 or not failures[0]["event_ids"]:
                raise Missing("Actual unique original definite failure/current owner proof missing")
            failure = failures[0]
            self.data["failure"] = deepcopy(failure["failure"])
            self.save()
            return {
                "run_id": self.first_data["run_id"],
                "measurement_id": failure["failure"]["measurement_id"],
                "event_id": failure["event_ids"][0],
                "title": raw["title"],
                "visibility": "product",
            }, self.reads(failure["required_source_read_set"], source_reads)

        result = self.step(
            "issue",
            "maker",
            "quality.issue.create",
            "quality_issue",
            create,
            inputs="quality-execution/inputs",
        )
        self.data["issue_id"] = result["result"]["issue_id"]
        self.save()

        def triage():
            row = self.current_issue()
            return {
                "issue_id": self.data["issue_id"],
                "expected_issue_revision": row["revision"],
                "reason": "Named current shared original failure triage",
            }, row["required_source_read_set"]

        self.step(
            "triage",
            "maker",
            "quality.issue.triage",
            "quality_issue",
            triage,
            inputs="quality-execution/inputs",
        )

        def capa():
            row = self.current_issue()
            failure_ids = [v["identity"] for v in row["issue"]["failures"]]
            return {
                "issue_id": self.data["issue_id"],
                "expected_issue_revision": row["revision"],
                "capa_id": self.data["capa_id"],
                "hypotheses": [{"text": raw["hypothesis"], "sources": refs}],
                "actions": [
                    {
                        "id": self.data["capa_action_id"],
                        "kind": "corrective",
                        "text": raw["action_text"],
                        "executor_id": self.actor("maker"),
                        "completion": None,
                    }
                ],
                "requirement": {
                    "method": raw["requirement_method"],
                    "acceptance": raw["requirement_acceptance"],
                    "observation_until": raw["observation_until"],
                    "required_failure_ids": failure_ids,
                },
            }, self.reads(row["required_source_read_set"], source_reads)

        self.step(
            "capa",
            "maker",
            "quality.capa.draft",
            "quality_issue",
            capa,
            inputs="quality-execution/inputs",
        )
        self.data["phase"] = "current_shared_capa_draft_no_root_or_completion"
        self.save()

    def current_issue(self):
        if "issue_id" not in self.data:
            raise Missing("Actual shared Issue/CAPA must be saved first")
        view = self.request(
            "maker",
            "GET",
            f"/v1/products/{self.product}/quality-execution",
            params={"issue_id": self.data["issue_id"]},
        )
        pointer = view.get("current_by_issue", {}).get(self.data["issue_id"])
        rows = [
            r for r in view.get("issues", []) if pointer and r["id"] == pointer["issue_version_id"]
        ]
        if len(rows) != 1 or rows[0]["revision"] != pointer["revision"]:
            raise Missing("Exact actual Current Issue missing")
        row = rows[0]
        if (
            row["source_status"] != "current"
            or row["visibility"] != "product"
            or row["owner_id"] != self.actor("maker")
        ):
            raise Missing("Current shared Issue source/audience/owner not valid")
        if (
            row["project_id"] != self.foundation["project_id"]
            or row["purpose"] != self.data["purpose"]
        ):
            raise Missing("Current Issue exact scope/purpose differs")
        return row

    def remediation_sources(self, *, material=None):
        from pdos_next.domain.quality_followup.schemas import CompletionFact
        from pdos_next.quality_followup_bootstrap import ClassificationFact, CompletionProfile
        from pdos_next.service import digest

        old = self.data["materials"].get("remediation")
        supplied = first.private_json(material) if material is not None else old
        combined = type(supplied) is dict and "offer_at" in supplied
        keys = {"root_text", "completion_text", "occurred_at", "original_timezone", "valid_until"}
        if combined:
            keys |= {"offer_at", "accept_at"}
        raw = self.selected_material(
            "remediation",
            material,
            keys,
        )
        row = self.current_issue()
        capa = row["issue"].get("capa")
        if not capa or capa["id"] != self.data["capa_id"]:
            raise Missing("Actual fixed CAPA/action required")
        action = next((a for a in capa["actions"] if a["id"] == self.data["capa_action_id"]), None)
        if (
            not action
            or action["executor_id"] != self.actor("maker")
            or action["completion"] is not None
        ):
            raise Missing("Only actual uncompleted Maker action may record its observed completion")
        first.aware_past(raw["occurred_at"])
        expiry = datetime.fromisoformat(raw["valid_until"].replace("Z", "+00:00"))
        if expiry.tzinfo is None or not datetime.now(UTC) < expiry <= datetime.fromisoformat(
            self.foundation["bootstrap_expires_at"]
        ):
            raise Missing("Actual finite future classification expiry required")
        completion = CompletionFact.model_validate(
            {
                "issue_id": self.data["issue_id"],
                "capa_id": self.data["capa_id"],
                "action_id": self.data["capa_action_id"],
                "executor_id": self.actor("maker"),
                "operation": "quality.capa.actions.complete",
                "occurred_at": raw["occurred_at"],
                "original_timezone": raw["original_timezone"],
                "purpose": self.data["purpose"],
                "text": raw["completion_text"],
            }
        ).model_dump(mode="json")
        classification = ClassificationFact.model_validate(
            {
                **self.foundation["scope"],
                "issue_id": self.data["issue_id"],
                "capa_id": self.data["capa_id"],
                "action_id": action["id"],
                "executor_id": action["executor_id"],
                "purpose": self.data["purpose"],
                "action_sha256": digest({k: v for k, v in action.items() if k != "completion"}),
                "classification": "investigation",
                "nature": "synthetic",
                "valid_until": raw["valid_until"],
            }
        ).model_dump(mode="json")
        lines = [
            self.h.canonical(
                {
                    "nature": "synthetic",
                    "meaning": "named root-cause proposal; no effectiveness/closure",
                    "text": raw["root_text"],
                }
            ),
            self.h.canonical(completion),
            self.h.canonical(classification),
        ]
        handoff_rows = []
        if combined:
            if not all(
                label in self.data["receipts"]
                for label in ("preparation", "formal", "method", "actual-method")
            ) or not self.data.get("sample_ref"):
                raise Missing("Actual precompletion Formal and both Method facts required")
            times = [first.aware_past(raw[k]) for k in ("occurred_at", "offer_at", "accept_at")]
            if times != sorted(times):
                raise Missing("Observed completion/Offer/Accept clocks must be ordered")
            for key, role in (("offer", "maker"), ("accept", "observer")):
                event = {
                    "request_id": self.data["request_id"],
                    "sample_id": self.data["original_sample_id"],
                    "purpose": self.data["purpose"],
                    "operation": "verification.handoff." + key,
                    "occurred_at": raw[key + "_at"],
                    "actor_id": self.actor(role),
                }
                handoff_rows.append({"key": key, "raw": event, "text": self.h.canonical(event)})
            lines.extend(v["text"] for v in handoff_rows)
        result = self.step(
            "remediation-native",
            "maker",
            "evidence.artifact.register",
            "artifact",
            lambda: (
                {
                    "title": "Wave22 shared actual investigation material",
                    "content": "\n".join(lines),
                    "source_label": (
                        "Explicit synthetic root proposal/observed completion/classification; "
                        "no physical implementation"
                    ),
                    "visibility": "product",
                },
                [],
            ),
        )
        refs = [
            {
                "artifact_id": result["subject_id"],
                "expected_revision": result["subject_revision"],
                "line": i,
                "quote": line,
            }
            for i, line in enumerate(lines, 1)
        ]
        profile = CompletionProfile.model_validate(
            {
                **self.foundation["scope"],
                "entries": [
                    {
                        **{
                            k: v
                            for k, v in classification.items()
                            if k not in self.foundation["scope"]
                        },
                        "source": source_ref(refs[2]),
                    }
                ],
            }
        ).model_dump(mode="json")
        if COMPLETION_PROFILE.exists() or COMPLETION_PROFILE.is_symlink():
            if self.h.canonical(first.private_json(COMPLETION_PROFILE)) != self.h.canonical(
                profile
            ):
                raise Missing("Original finite newscope classification export changed")
        else:
            self.h.private_write(COMPLETION_PROFILE, profile)
        self.data["remediation_refs"] = refs
        if handoff_rows:
            self.data["events"]["handoff"] = {"publisher": "maker", "rows": handoff_rows}
            self.data["remediation_handoff_refs"] = refs[3:]
        self.data["completion_fact"] = completion
        self.data["completion_profile_sha256"] = hashlib.sha256(
            self.h.canonical(profile).encode()
        ).hexdigest()
        self.data["phase"] = "remediation_sources_saved_classification_not_installed"
        self.save()
        return {
            "phase": self.data["phase"],
            "completion_profile": str(COMPLETION_PROFILE.relative_to(ROOT)),
            "requires_root_explicit_plural_profile_configuration": True,
            "physical_action_fulfilled": None,
        }

    def root_cause(self):
        refs = self.data.get("remediation_refs")
        if not refs:
            raise Missing("Actual saved root proposal source required")

        def payload():
            row = self.current_issue()
            return {
                "issue_id": self.data["issue_id"],
                "expected_issue_revision": row["revision"],
                "text": self.data["materials"]["remediation"]["root_text"],
                "sources": [source_ref(refs[0])],
            }, self.reads(
                row["required_source_read_set"],
                [
                    {
                        "artifact_id": refs[0]["artifact_id"],
                        "expected_revision": refs[0]["expected_revision"],
                    }
                ],
            )

        self.step(
            "root-cause",
            "maker",
            "quality.issue.root_cause.decide",
            "quality_issue",
            payload,
            inputs="quality-followup/inputs",
        )
        self.data["phase"] = "named_root_saved_no_completion"
        self.save()

    def complete(self):
        refs = self.data.get("remediation_refs")
        if not refs:
            raise Missing("Actual nine-key completion/source and classification export required")

        def payload():
            row = self.current_issue()
            if row["issue"]["root_cause"] is None:
                raise Missing("Root-cause T2 must precede final actual completion")
            raw = self.data["completion_fact"]
            source = source_ref(refs[1])
            return {
                "issue_id": self.data["issue_id"],
                "expected_issue_revision": row["revision"],
                "completions": [
                    {
                        "id": raw["action_id"],
                        "executor_id": raw["executor_id"],
                        "text": raw["text"],
                        "evidence": [source],
                        "at": {
                            "occurred_at": raw["occurred_at"],
                            "original_timezone": raw["original_timezone"],
                            "source": source,
                        },
                    }
                ],
            }, self.reads(
                row["required_source_read_set"],
                [
                    {
                        "artifact_id": refs[1]["artifact_id"],
                        "expected_revision": refs[1]["expected_revision"],
                    }
                ],
            )

        self.step(
            "complete",
            "maker",
            "quality.capa.actions.complete",
            "quality_issue",
            payload,
            inputs="quality-followup/inputs",
        )
        self.completed()
        self.data["phase"] = "actual_investigation_completed_no_effectiveness"
        self.save()

    def completed(self):
        row = self.current_issue()
        capa = row["issue"].get("capa")
        if (
            row["status"] != "awaiting_verification"
            or row["issue"]["root_cause"] is None
            or not capa
            or capa["id"] != self.data["capa_id"]
        ):
            raise Missing("Actual completed current CAPA/root required, no invented completion")
        action = next((a for a in capa["actions"] if a["id"] == self.data["capa_action_id"]), None)
        if (
            not action
            or action["completion"] is None
            or action["executor_id"] != self.actor("maker")
        ):
            raise Missing("Exact actual Maker completion missing")
        if capa.get("effectiveness") is not None or row["issue"].get("closure") is not None:
            raise Missing("This limited driver does not advance effective/close")
        return row

    def handoff(self, *, offer_at=None, accept_at=None):
        self.completed()
        refs = self.data.get("remediation_handoff_refs")
        if refs is None:
            return super().handoff(offer_at=offer_at, accept_at=accept_at)
        self.publication()
        self._methods()
        rows = self.data["events"]["handoff"]["rows"]
        for (action, role, provided), row, ref in zip(
            (("offer", "maker", offer_at), ("accept", "observer", accept_at)),
            rows,
            refs,
            strict=True,
        ):
            first.aware_past(row["raw"]["occurred_at"])
            if provided is not None and provided != row["raw"]["occurred_at"]:
                raise Missing("Combined observed handoff source clock cannot change")
            expected = {
                "request_id": self.data["request_id"],
                "sample_id": self.data["original_sample_id"],
                "purpose": self.data["purpose"],
                "operation": "verification.handoff." + action,
                "occurred_at": row["raw"]["occurred_at"],
                "actor_id": self.actor(role),
            }
            if row["raw"] != expected or ref["quote"] != self.h.canonical(expected):
                raise Missing("Combined handoff exact saved actor/scope/line mismatch")

            def payload(action=action, role=role, ref=ref, expected=expected):
                view, request, _ = self.current(role=role)
                sample, reads = self.selected(view)
                result = {
                    "request_id": self.data["request_id"],
                    "expected_request_revision": request["revision"],
                    "coverage": self.data["coverage"],
                    "at": {
                        "occurred_at": expected["occurred_at"],
                        "original_timezone": "UTC",
                        "source": source_ref(ref),
                    },
                    "sources": [self.ref(), ref],
                    "reason": "Exact shared followup A2 handoff after actual completed Origin",
                }
                result["samples" if action == "offer" else "returned_coverage"] = (
                    [sample] if action == "offer" else []
                )
                return result, self.reads(
                    request["required_source_read_set"],
                    reads,
                    [
                        {
                            "artifact_id": ref["artifact_id"],
                            "expected_revision": ref["expected_revision"],
                        }
                    ],
                )

            self.step(
                action, role, "verification.handoff." + action, "verification_request", payload
            )
        self.data["phase"] = "actual_second_accepted_after_completed_origin_no_run"
        self.save()

    def _methods(self):
        def method():
            _, row, _ = self.current()
            return {
                "request_id": self.data["request_id"],
                "expected_request_revision": row["revision"],
                "assessments": [
                    {
                        "item_id": "dimension",
                        **self.published("method"),
                        "sources": [self.published("method_source")],
                    }
                ],
                "reason": "Fixed current followup method, no CAPA conclusion",
            }, row["required_source_read_set"]

        self.step(
            "method", "observer", "verification.method.prepare", "verification_request", method
        )

        def actual_method():
            view, row, _ = self.current()
            sample, reads = self.selected(view)
            self.data["sample_ref"] = sample
            self.data["coverage"] = [{"sample_id": sample["id"], "item_id": "dimension"}]
            self.save()
            return {
                "request_id": self.data["request_id"],
                "expected_request_revision": row["revision"],
                "assessments": [
                    {
                        "sample": sample,
                        "item_id": "dimension",
                        "expected_assessment_revision": 0,
                        **self.published("actual_method"),
                        "sources": [self.published("actual_method_source")],
                    }
                ],
                "sources": [self.ref()],
                "reason": "Actual A2 method only, no inherited applicability",
            }, self.reads(row["required_source_read_set"], reads)

        self.step(
            "actual-method",
            "observer",
            "verification.actual_method.prepare",
            "verification_actual_method",
            actual_method,
        )

    def precompletion_prepare(self):
        """Independent owner draft/methods only; no Link, Plan, occupancy or Start."""
        self.draft(before_completion=True)
        self._methods()
        self.data["phase"] = "actual_precompletion_formal_methods_no_handoff_or_link"
        self.save()

    def start(self, *, occurred_at=None):
        row = self.completed()
        action = next(
            a for a in row["issue"]["capa"]["actions"] if a["id"] == self.data["capa_action_id"]
        )
        if occurred_at is None:
            occurred_at = (
                self.data["requests"]
                .get("run-start", {})
                .get("original", {})
                .get("payload", {})
                .get("at", {})
                .get("occurred_at")
            )
        at = first.aware_past(occurred_at)
        completed = first.aware_past(action["completion"]["at"]["occurred_at"])
        if at < completed:
            raise Missing("Actual second Start cannot predate the actual Maker completion")
        return super().start(occurred_at=occurred_at)

    def native_events(self, references, rows, *, publisher):
        """Re-read actual shared native lines/registration; no Rule/Observation qualification."""
        from pdos_next.domain.configurations.schemas import DefinitionReference
        from pdos_next.service import digest

        if publisher not in {"maker", "observer"} or len(references) != len(rows):
            raise Missing("Exact actual native publisher and event references required")
        refs = [DefinitionReference.model_validate(v).model_dump(mode="json") for v in references]
        identities = {(v["artifact_id"], v["expected_revision"]) for v in refs}
        if len(identities) != 1:
            raise Missing("Shared event lines must belong to one exact existing native source")
        identity, revision = next(iter(identities))
        workspace = self.get("workspace")
        candidates = [
            v for v in workspace["sources"] if v["id"] == identity and v["revision"] == revision
        ]
        if len(candidates) != 1:
            raise Missing("Exact current actual native source missing")
        actual = candidates[0]
        if (
            actual["status"] != "active"
            or actual["visibility"] != "product"
            or actual.get("original_id") is not None
            or digest(actual["content"]) != actual["content_hash"]
        ):
            raise Missing("Actual shared native source origin/hash/audience mismatch")

        def unique(entries):
            result = {}
            for key, value in entries:
                if key in result:
                    raise ValueError("Duplicate event key")
                result[key] = value
            return result

        lines = actual["content"].splitlines()
        for ref, expected in zip(refs, rows, strict=True):
            if ref["line"] > len(lines) or lines[ref["line"] - 1] != ref["quote"]:
                raise Missing("Shared native exact original line differs")
            try:
                event = json.loads(ref["quote"], object_pairs_hook=unique)
            except (ValueError, TypeError):
                raise Missing("Exact JSON event with unique fields required") from None
            if event != expected:
                raise Missing("Existing whole event scope/actor/time/basis differs")
        receipts = [
            v
            for v in workspace["receipts"]
            if v["operation"] == "evidence.artifact.register"
            and v["subject_id"] == identity
            and v["subject_revision"] == revision
        ]
        if len(receipts) != 1:
            raise Missing("Actual canonical native registration Receipt missing")
        self.check_receipt(receipts[0], publisher, "evidence.artifact.register", "artifact")
        self.data["selected_native_source_reads"] = self.h.merge_reads(
            self.data.get("selected_native_source_reads", []),
            [{"artifact_id": identity, "expected_revision": revision}],
        )
        self.save()
        return refs

    def promise(self, *, occurred_at=None, material=None):
        if "promise" in self.data["requests"]:
            if material is not None:
                self.selected_material("promise-source", material, {"reference", "publisher_role"})
            if (
                occurred_at is not None
                and occurred_at
                != self.data["requests"]["promise"]["original"]["payload"]["at"]["occurred_at"]
            ):
                raise Missing("Original prepared Promise clock cannot change")
            # Preserve the original Command before any live Plan/current lookup.
            return super().promise(occurred_at=occurred_at)
        if material is not None or "promise-source" in self.data["materials"]:
            raw = self.selected_material(
                "promise-source", material, {"reference", "publisher_role"}
            )
            _, _, run = self.current("verification-launch")
            if run is None or run["status"] != "planned":
                raise Missing(
                    "Actual saved Plan required before shared Rule/Promise source selection"
                )
            at = (
                occurred_at if occurred_at is not None else run["execution_plan"]["window"]["start"]
            )
            first.promise_start(at, run["execution_plan"]["window"])
            expected = {
                "request_id": self.data["request_id"],
                "run_id": self.data["run_id"],
                "purpose": self.data["purpose"],
                "operation": "verification.schedule.promise",
                "occurred_at": at,
                "executor_id": self.actor("observer"),
            }
            refs = self.native_events(
                [raw["reference"]], [expected], publisher=raw["publisher_role"]
            )
            self.data["shared_promise_event"] = {
                "reference": refs[0],
                "at": {
                    "occurred_at": at,
                    "original_timezone": "UTC",
                    "source": source_ref(refs[0]),
                },
            }
            self.save()
            occurred_at = at
        return super().promise(occurred_at=occurred_at)

    def event(self, label, role, operation, occurred_at, *, executor=False, promise_window=None):
        shared = self.data.get("shared_promise_event") if label == "promise" else None
        if shared is None:
            return super().event(
                label,
                role,
                operation,
                occurred_at,
                executor=executor,
                promise_window=promise_window,
            )
        if (
            role != "observer"
            or operation != "verification.schedule.promise"
            or executor is not True
            or promise_window is None
            or shared["at"]["occurred_at"] != occurred_at
        ):
            raise Missing("Exact fixed shared Promise event required")
        first.promise_start(occurred_at, promise_window)
        return deepcopy(shared)

    def readback(self):
        _, request, run = self.current("verification-results")
        computed = self.data["receipts"].get("compute")
        projection = run.get("current_projection") if run else None
        if (
            not run
            or not projection
            or not computed
            or (projection["id"], projection["revision"])
            != (computed["subject_id"], computed["subject_revision"])
            or projection["basis_sha256"] != run["basis_sha256"]
        ):
            raise Missing("Actual deterministic second Run current projection missing")
        self.data["result_readback"] = {
            "run_id": run["run_id"],
            "run_version_id": run["id"],
            "run_revision": run["revision"],
            "request_version_id": request["id"],
            "request_revision": request["revision"],
            "projection": deepcopy(projection),
            "result": projection["result"],
            "required_source_read_set": self.reads(
                request["required_source_read_set"], run["required_source_read_set"]
            ),
            "readback_at": datetime.now(UTC).isoformat(),
            "effectiveness": None,
            "close": False,
        }
        self.data["phase"] = "actual_second_result_no_independent_review_or_close"
        self.save()
        return {
            "phase": self.data["phase"],
            "result": projection["result"],
            "independent_review_saved": False,
        }

    def conclusions(self, *, material=None):
        old = self.data["materials"].get("conclusions")
        supplied = first.private_json(material) if material is not None else old
        keys = {"review_text", "review_at", "disposition_text", "disposition_at"}
        if type(supplied) is dict and "event_sources" in supplied:
            keys.add("event_sources")
        raw = self.selected_material(
            "conclusions",
            material,
            keys,
        )
        events = self.conclusion_events(raw)
        for label, operation, text_key, time_key in (
            ("run-review", "test.run.review", "review_text", "review_at"),
            ("disposition", "test.disposition.decide", "disposition_text", "disposition_at"),
        ):

            def payload(label=label, operation=operation, text_key=text_key, time_key=time_key):
                _, request, run = self.current("verification-results")
                projection = run.get("current_projection") if run else None
                if projection is None:
                    raise Missing("Actual current deterministic Projection required before each T2")
                event = events["review" if operation == "test.run.review" else "disposition"]
                if event["basis_sha256"] != run["basis_sha256"]:
                    raise Missing(
                        "Actual conclusion source belongs to another result basis; no replacement"
                    )
                return {
                    "request_id": self.data["request_id"],
                    "expected_request_revision": request["revision"],
                    "run_id": self.data["run_id"],
                    "expected_run_revision": run["revision"],
                    "projection_id": projection["id"],
                    "expected_projection_revision": projection["revision"],
                    "expected_basis_sha256": run["basis_sha256"],
                    "text": raw[text_key],
                    "at": event["at"],
                    "sources": [event["reference"]],
                    "reason": "Named actual Run conclusion; no CAPA effectiveness/close",
                }, self.reads(
                    request["required_source_read_set"],
                    [
                        {
                            "artifact_id": event["reference"]["artifact_id"],
                            "expected_revision": event["reference"]["expected_revision"],
                        }
                    ],
                )

            self.step(
                label,
                "observer",
                operation,
                "test_run",
                payload,
                inputs="verification-results/inputs",
            )
        self.data["phase"] = "actual_second_run_named_conclusions_no_independent_capa_review"
        self.save()

    def conclusion_events(self, raw):
        """Actual result writer requires two exact eight-field named events, not generic six."""
        _, request, run = self.current("verification-results")
        projection = run.get("current_projection") if run else None
        if not run or not projection or projection.get("basis_sha256") != run.get("basis_sha256"):
            raise Missing("Actual current computed result basis required before named source")
        rows = []
        for _label, operation, text, occurred in (
            ("review", "test.run.review", raw["review_text"], raw["review_at"]),
            (
                "disposition",
                "test.disposition.decide",
                raw["disposition_text"],
                raw["disposition_at"],
            ),
        ):
            first.aware_past(occurred)
            rows.append(
                {
                    "request_id": self.data["request_id"],
                    "run_id": self.data["run_id"],
                    "purpose": self.data["purpose"],
                    "operation": operation,
                    "actor_id": self.actor("observer"),
                    "occurred_at": occurred,
                    "text": text,
                    "basis_sha256": run["basis_sha256"],
                }
            )
        if first.aware_past(rows[1]["occurred_at"]) < first.aware_past(rows[0]["occurred_at"]):
            raise Missing("Actual named conclusion clocks must be ordered")
        saved = self.data["events"].get("named-conclusions")
        if saved is None:
            self.data["events"]["named-conclusions"] = {"rows": rows}
            self.save()
        elif saved.get("rows") != rows:
            raise Missing("Fixed actual named conclusion source cannot change")
        content = "\n".join(self.h.canonical(v) for v in rows)
        if "event_sources" in raw:
            if type(raw["event_sources"]) is not list or len(raw["event_sources"]) != 2:
                raise Missing("Exact Review/Disposition full-line native reference pair required")
            refs = self.native_events(raw["event_sources"], rows, publisher="observer")
        else:
            result = self.step(
                "event-named-conclusions",
                "observer",
                "evidence.artifact.register",
                "artifact",
                lambda: (
                    {
                        "title": "Wave22 shared named Run conclusions",
                        "content": content,
                        "source_label": (
                            "Explicit already-observed synthetic named proposals; "
                            "no CAPA effectiveness"
                        ),
                        "visibility": "product",
                    },
                    self.reads(
                        request["required_source_read_set"], run["required_source_read_set"]
                    ),
                ),
            )
            refs = [
                {
                    "artifact_id": result["subject_id"],
                    "expected_revision": result["subject_revision"],
                    "line": number,
                    "quote": self.h.canonical(row),
                }
                for number, row in enumerate(rows, 1)
            ]
        outputs = {}
        for label, row, ref in zip(("review", "disposition"), rows, refs, strict=True):
            outputs[label] = {
                "reference": ref,
                "basis_sha256": row["basis_sha256"],
                "at": {
                    "occurred_at": row["occurred_at"],
                    "original_timezone": "UTC",
                    "source": source_ref(ref),
                },
            }
        return outputs

    def link(self, *, stage="current"):
        if stage not in {"draft", "current"}:
            raise Missing("Exact output stage required")
        self.completed()
        if stage == "current" and "disposition" not in self.data["receipts"]:
            raise Missing(
                "Actual second Run Review/Disposition required before current output link"
            )

        def payload():
            view = self.request(
                "maker",
                "GET",
                f"/v1/products/{self.product}/quality-followup",
                params={"issue_id": self.data["issue_id"]},
            )
            _, request, _ = self.current(
                "verification-results" if stage == "current" else "verification-handoff",
                role="maker",
            )
            options = [
                v
                for v in view["output_options"]
                if v.get("logical_id") == self.data["request_id"]
                and v["ref"]["kind"] == "verification_request"
                and v["ref"]["id"] == request["id"]
                and v["ref"]["revision"] == request["revision"]
            ]
            if len(options) != 1 or (stage == "draft" and request["status"] != "draft"):
                raise Missing(
                    "Actual owner/paired Current output option missing; no Draft/origin fallback"
                )
            return {
                "issue_id": self.data["issue_id"],
                "expected_issue_revision": view["current"]["revision"],
                "capa_id": self.data["capa_id"],
                "action_id": self.data["capa_action_id"],
                "output_refs": [options[0]["ref"]],
                "sources": [],
                "reason": "Actual fixed "
                + stage
                + " followup output; independent applicability/effectiveness remain unknown",
            }, self.reads(
                view["required_source_read_set"], options[0].get("required_source_read_set", [])
            )

        self.step(
            "link-" + stage,
            "maker",
            "quality.capa.followup.link",
            "capa_remediation_link",
            payload,
            inputs="quality-followup/inputs",
        )
        self.data["phase"] = "actual_" + stage + "_link_no_rule_or_independent_review"
        self.save()

    def step(self, label, role, operation, family, build_payload, *, inputs=None):
        """Existing originals precede dynamic GET factories and retain every byte/key/token."""
        from pdos_next.contracts import PAYLOADS, Command
        from pdos_next.service import T1_OPERATIONS, T2_OPERATIONS

        actor = self.actor(role)
        saved = self.data["requests"].get(label)
        command_id = str(uuid5(UUID(self.namespace), role + ":" + label))
        if saved is not None and (
            saved["role"] != role
            or saved["actor_id"] != actor
            or saved["original"]["operation"] != operation
            or saved["original"]["product_id"] != self.product
            or saved["original"]["command_id"] != command_id
            or saved["original"]["idempotency_key"] != self.key(label, role)
        ):
            raise Missing("Saved actor/scope/operation/command identity changed")
        if label in self.data["receipts"]:
            if saved is None:
                raise Missing("Actual saved Receipt requires original request")
            return self.check_receipt(self.data["receipts"][label], role, operation, family)
        cls = PAYLOADS.get(operation)
        if cls is None:
            raise Missing("Actual canonical payload not configured")
        if saved is None:
            payload, reads = build_payload()
            typed = cls.model_validate(payload).model_dump(mode="json", exclude_none=True)
            workspace = self.get("workspace", role)
            if workspace["product"]["id"] != self.product:
                raise Missing("Actual Product mismatch")
            original = Command(
                command_id=command_id,
                idempotency_key=self.key(label, role),
                operation=operation,
                product_id=self.product,
                expected_revision=workspace["product"]["revision"],
                source_read_set=self.reads(reads),
                payload=typed,
            ).model_dump(mode="json")
            if inputs:
                response = self.request(
                    role, "POST", f"/v1/products/{self.product}/{inputs}", body=original
                )
                if response.get("allowed") is not True or response.get("operation") != operation:
                    raise Missing("Actual command inputs not allowed; no optimistic command")
                original["source_read_set"] = self.h.merge_reads(
                    original["source_read_set"], response["required_source_read_set"]
                )
            saved = {
                "role": role,
                "actor_id": actor,
                "original": original,
                "body": deepcopy(original),
                "state": "ready",
            }
            self.data["requests"][label] = saved
            self.save()
        original = Command.model_validate(saved["original"]).model_dump(mode="json")
        body = Command.model_validate(saved["body"]).model_dump(mode="json")
        normalized = deepcopy(body)
        normalized["payload"] = cls.model_validate(body["payload"]).model_dump(
            mode="json", exclude_none=True, exclude={"confirmation_token", "approval_token"}
        )
        if self.h.canonical(normalized) != self.h.canonical(original):
            raise Missing("Original prepared command/material changed")
        if "preview" in saved and self.h.canonical(body) != self.h.canonical(
            saved["preview"]["command"]
        ):
            raise Missing("Original prepared token cannot change")
        if saved["state"] == "rejected":
            raise Missing("Original request refused; no fresh key/token repair")
        if saved["state"] in {"preview_sending", "preview_unknown"}:
            raise Missing("Actual preview recovery missing; no replacement preview")
        if (
            saved["state"] not in {"sending", "unknown"}
            and operation in T1_OPERATIONS | T2_OPERATIONS
        ):
            if "preview" not in saved:
                import httpx

                saved["state"] = "preview_sending"
                self.save()
                try:
                    preview = self.request(role, "POST", "/v1/commands/preview", body=original)
                except httpx.TransportError:
                    saved["state"] = "preview_unknown"
                    self.save()
                    raise Missing("Preview outcome unknown") from None
                prepared = Command.model_validate(preview["command"]).model_dump(mode="json")
                material = deepcopy(prepared)
                material["payload"] = cls.model_validate(prepared["payload"]).model_dump(
                    mode="json", exclude_none=True, exclude={"confirmation_token", "approval_token"}
                )
                if self.h.canonical(material) != self.h.canonical(original):
                    raise Missing("Actual preview changed fixed command")
                tier = "T2" if operation in T2_OPERATIONS else "T1"
                field = "approval_token" if tier == "T2" else "confirmation_token"
                if not prepared["payload"].get(field) or (
                    tier == "T2"
                    and (
                        preview.get("write_tier") != "T2"
                        or preview.get("named_decision") is not True
                    )
                ):
                    raise Missing("Actual named proof/tier missing")
                review = hashlib.sha256(
                    self.h.canonical({"command": prepared, "review": preview["review"]}).encode()
                ).hexdigest()
                saved.update(
                    preview=preview,
                    body=prepared,
                    tier=tier,
                    review_digest=review,
                    state="awaiting_confirmation",
                )
                self.save()
            if (
                self.confirm != label
                or self.confirm_used
                or self.review_digest != saved["review_digest"]
            ):
                raise Pending(label)
            self.confirm_used = True
        value = self._send(label, role, "/v1/commands")
        self.check_receipt(value, role, operation, family)
        self.data["receipts"][label] = value
        saved["state"] = "saved"
        self.save()
        return value

    def resources(self, *, window_start=None, window_end=None, valid_until=None):
        from pdos_next.domain.test_resources.schemas import TestResourceFactInput
        from pdos_next.domain.verification_launch.schemas import ExecutionPlan

        if "accept" not in self.data["receipts"]:
            raise Missing("Actual Offer/Accept required before fixed resources")
        self.publication()
        if "resource_input" not in self.data:
            if not all((window_start, window_end, valid_until)):
                raise Missing(
                    "Explicit future execution window and finite publication expiry required"
                )
            at = datetime.now(UTC)
            expiry = datetime.fromisoformat(valid_until.replace("Z", "+00:00"))
            plan = ExecutionPlan.model_validate(
                {
                    "window": {
                        "start": window_start,
                        "finish": window_end,
                        "original_timezone": "UTC",
                    },
                    "executor_id": self.actor("observer"),
                    "equipment": self.published("equipment"),
                    "calibration": self.published("calibration"),
                    "environment": self.published("environment"),
                    "conditions": self.published("conditions"),
                    "resource_fact_id": str(
                        uuid5(
                            UUID(self.namespace),
                            "retest:resource-selection-placeholder",
                        )
                    ),
                    "expected_resource_fact_revision": 1,
                }
            )
            if (
                expiry.utcoffset() is None
                or not at + timedelta(minutes=15) <= plan.window.start < plan.window.finish < expiry
                or expiry > datetime.fromisoformat(self.foundation["bootstrap_expires_at"])
            ):
                raise Missing(
                    "Explicit future plan needs >=15 minutes preparation horizon "
                    "and finite scope expiry"
                )
            binding = self.resource_binding(plan)
            original_resources = self.first_data.get("resource_input", {}).get("resources", [])
            resources = []
            for kind, identity, kinds in (
                ("equipment", self.data["test_equipment_id"], ("acceptance", "calibration")),
                ("person", self.actor("observer"), ("qualification",)),
            ):
                physical = [
                    r
                    for r in original_resources
                    if r["resource"]["id"] == identity and r["resource"]["kind"] == kind
                ]
                if len(physical) != 1:
                    raise Missing("Exact original physical resource mirror required")
                physical = physical[0]
                resources.append(
                    {
                        "resource": deepcopy(physical["resource"]),
                        "purposes": [self.data["purpose"]],
                        "operation_ids": ["test.run.start"],
                        "lifecycle": physical["lifecycle"],
                        "maintenance": deepcopy(physical["maintenance"]),
                        "capacity": physical["capacity"],
                        "calendar": deepcopy(physical["calendar"]),
                        "calendar_sources": self.published("resource_sources"),
                        "external_occupancies_complete": True,
                        "sources": self.published("resource_sources"),
                        "facts": [
                            {
                                "kind": k,
                                "purpose": self.data["purpose"],
                                "operation_id": "test.run.start",
                                "status": "accepted",
                                "valid_from": at.isoformat(),
                                "valid_until": expiry.isoformat(),
                                "named_decision_id": str(
                                    uuid5(
                                        UUID(self.namespace),
                                        "retest:" + kind + ":" + k,
                                    )
                                ),
                                "actor_id": self.actor("observer"),
                                "sources": self.published("resource_sources"),
                            }
                            for k in kinds
                        ],
                    }
                )
            raw = TestResourceFactInput.model_validate(
                {
                    "binding": binding,
                    "external_id": self.key("resource"),
                    "valid_from": at.isoformat(),
                    "valid_until": expiry.isoformat(),
                    "resources": resources,
                    "required_uses": [{"resource": r["resource"], "units": "1"} for r in resources],
                    "requirements_sources": self.published("requirements_sources"),
                    "sources": self.published("resource_sources"),
                    "reason": (
                        "Prospective exact local synthetic trusted publication; "
                        "no production or instrument claim"
                    ),
                }
            ).model_dump(mode="json")
            self.data["execution_plan"] = plan.model_dump(mode="json")
            self.data["resource_input"] = raw
            self.save()
        else:
            plan = self.data["execution_plan"]["window"]
            for provided, old in (
                (window_start, plan["start"]),
                (window_end, plan["finish"]),
                (valid_until, self.data["resource_input"]["valid_until"]),
            ):
                if provided and datetime.fromisoformat(
                    provided.replace("Z", "+00:00")
                ) != datetime.fromisoformat(old.replace("Z", "+00:00")):
                    raise Missing("Original window/publication cannot change")
        raw = self.data["resource_input"]
        original_profile = first.private_json(self.first_profile_path)
        if (
            first.digest_file(self.first_profile_path) != self.first_profile_sha
            or original_profile != self.first_profile
        ):
            raise Missing("Actual first-generation finite host profile changed")
        profile = retained_resource_profile(original_profile, raw, self.foundation["scope"])
        for path, value in ((RESOURCE_PROFILE, profile), (RESOURCE_INPUT, raw)):
            if path.exists() or path.is_symlink():
                if self.h.canonical(first.private_json(path)) != self.h.canonical(value):
                    raise Missing("Existing exact finite resource export differs")
            else:
                self.h.private_write(path, value)
        self.data["phase"] = "resource_exports_not_imported_or_installed"
        self.save()
        return {
            "resource_profile": str(RESOURCE_PROFILE.relative_to(ROOT)),
            "resource_input": str(RESOURCE_INPUT.relative_to(ROOT)),
            "requires_root_trusted_import_and_api_plural_reload": True,
        }

    def draft(self, *, before_completion=False):
        if before_completion:
            row = self.current_issue()
            capa = row["issue"].get("capa")
            actions = capa.get("actions", []) if capa else []
            if (
                not capa
                or capa["id"] != self.data["capa_id"]
                or not any(
                    a["id"] == self.data["capa_action_id"]
                    and a["executor_id"] == self.actor("maker")
                    and a["completion"] is None
                    for a in actions
                )
                or capa.get("effectiveness") is not None
                or row["issue"].get("closure") is not None
            ):
                raise Missing("Exact actual uncompleted shared CAPA required for early draft")
        else:
            self.completed()
        self.publication()
        self.step(
            "preparation",
            "observer",
            "verification.preparation.record",
            "verification_preparation",
            lambda: (
                {
                    "request_id": self.data["preparation_request_id"],
                    "expected_request_revision": 0,
                    "build_id": self.data["build_id"],
                    "expected_build_revision": self.build["build"]["revision"],
                    "title": "Wave22 shared new followup A2 dimension",
                    "purpose": self.data["purpose"],
                    "return_form": "Exact uploaded UTF-8 JSONL original; synthetic not instrument",
                    "items": [
                        {
                            "id": "dimension",
                            "feature": "Dimension",
                            "drawing": self.ref(2),
                            "method": self.published("method_source"),
                            "criterion": {"lower": "9.5", "upper": "10.5", "source": self.ref(2)},
                            "unit": "mm",
                            "conditions": "23 C, dry",
                            "material": "Synthetic material",
                            "sample_count": 1,
                            "cavities": ["A"],
                            "destructive": False,
                        }
                    ],
                    "documents": [
                        {
                            "id": "method",
                            "title": "Fixed method publication",
                            "item_ids": ["dimension"],
                            "source": self.published("method_source"),
                            "required": True,
                        }
                    ],
                    "sources": [self.ref()],
                    "reason": "New actual followup branch; original failed Run retained",
                },
                self.reads(),
            ),
        )

        def formal():
            view = self.get("verification")
            receipt = self.data["receipts"]["preparation"]
            prep = next((r for r in view["preparations"] if r["id"] == receipt["subject_id"]), None)
            if (
                not prep
                or prep["revision"] != receipt["subject_revision"]
                or prep["source_status"] != "current"
            ):
                raise Missing("Exact actual Preparation missing")
            return {
                "request_id": self.data["request_id"],
                "preparation_id": prep["id"],
                "expected_preparation_revision": prep["revision"],
                "preparation_sha256": prep["sha256"],
                "reason": "New shared Formal branch",
            }, prep["required_source_read_set"]

        self.step(
            "formal", "observer", "verification.request.create", "verification_request", formal
        )

        if not before_completion:
            self.completed()
        self.data["phase"] = "new_followup_formal_draft_saved_no_second_run"
        self.save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "phase",
        choices=(
            "quality",
            "source-budget",
            "remediation-sources",
            "root-cause",
            "complete",
            "precompletion-prepare",
            "draft",
            "link-draft",
            "handoff",
            "resources",
            "plan",
            "promise",
            "start",
            "report",
            "compute",
            "conclusions",
            "link-current",
            "readback",
        ),
    )
    parser.add_argument("--marker", required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--first-generation")
    source.add_argument("--fresh-generation")
    choice = parser.add_mutually_exclusive_group()
    choice.add_argument("--confirm")
    choice.add_argument("--recover")
    parser.add_argument("--review-digest")
    parser.add_argument("--material", type=Path)
    for option in (
        "offer-at",
        "accept-at",
        "occurred-at",
        "window-start",
        "window-end",
        "valid-until",
    ):
        parser.add_argument("--" + option)
    tool = None
    try:
        args = parser.parse_args()
        tool = SharedRetest(
            args.marker,
            first_generation=args.first_generation,
            fresh_generation=args.fresh_generation,
            confirm=args.confirm,
            review_digest=args.review_digest,
            recover=args.recover,
        )
        phases = {
            "source-budget": (tool.source_budget, {}),
            "quality": (tool.quality, {"material": args.material}),
            "remediation-sources": (tool.remediation_sources, {"material": args.material}),
            "root-cause": (tool.root_cause, {}),
            "complete": (tool.complete, {}),
            "precompletion-prepare": (tool.precompletion_prepare, {}),
            "draft": (tool.draft, {}),
            "link-draft": (tool.link, {"stage": "draft"}),
            "handoff": (tool.handoff, {"offer_at": args.offer_at, "accept_at": args.accept_at}),
            "resources": (
                tool.resources,
                {
                    "window_start": args.window_start,
                    "window_end": args.window_end,
                    "valid_until": args.valid_until,
                },
            ),
            "plan": (tool.plan, {}),
            "promise": (tool.promise, {"occurred_at": args.occurred_at, "material": args.material}),
            "start": (tool.start, {"occurred_at": args.occurred_at}),
            "report": (tool.report, {"material": args.material}),
            "compute": (tool.compute, {}),
            "conclusions": (tool.conclusions, {"material": args.material}),
            "link-current": (tool.link, {"stage": "current"}),
            "readback": (tool.readback, {}),
        }
        call, kwargs = phases[args.phase]
        result = call(**kwargs)
        print(
            json.dumps(
                result
                or {
                    "phase": tool.data["phase"],
                    "receipts_saved": len(tool.data["receipts"]),
                    "effectiveness": None,
                    "close": False,
                },
                ensure_ascii=False,
            )
        )
    except Pending as waiting:
        value = tool.data["requests"][waiting.label]
        print(
            json.dumps(
                {
                    "state": "awaiting_confirmation",
                    "label": waiting.label,
                    "tier": value["tier"],
                    "review_digest": value["review_digest"],
                    "review": value["preview"]["review"],
                    "expires_at": value["preview"]["expires_at"],
                    "submitted": False,
                },
                ensure_ascii=False,
            )
        )
    except Unknown as unknown:
        print(
            json.dumps(
                {"state": "unknown_original_retained", "label": unknown.label, "retry": False}
            )
        )
    except Exception as error:
        print(
            json.dumps(
                {
                    "state": "missing_or_rejected",
                    "error_type": type(error).__name__,
                    "code": getattr(error, "code", None),
                    "no_automatic_review_or_close": True,
                }
            )
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
