"""Explicit new triage after a proved rejection; preserve the original request.

This Root control entry point does not renew, alter or resend the rejected
confirmation. All other steps use the frozen actual Retest driver unchanged.
"""

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RETEST_SHA = "9fe91ec4f140f9e039fa2428bebd7b8d6196a1f959b76eded388ed4d6ef81a6f"
NEW_LABEL = "triage-runtime-reload-v1"
DECISION_KEYS = {
    "schema_version",
    "marker",
    "case_id",
    "fresh_generation",
    "rejected_record_sha256",
    "readback_reference",
    "readback_sha256",
    "new_label",
    "retest_source_sha256",
}


def sha(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def check_decision(decision, proof, rejected):
    if (
        type(decision) is not dict
        or set(decision) != DECISION_KEYS
        or decision["schema_version"] != "wave22-explicit-triage-continuation-v1"
        or decision["retest_source_sha256"] != RETEST_SHA
        or decision["new_label"] != NEW_LABEL
        or rejected.get("state") != "rejected"
        or rejected.get("error", {}).get("code") != "CONFIRMATION_SCOPE_CHANGED"
        or rejected.get("original", {}).get("operation") != "quality.issue.triage"
        or decision["rejected_record_sha256"] != sha(rejected)
        or proof.get("original_record_sha256") != sha(rejected)
        or proof.get("status") != "PASS"
        or proof.get("old_action_receipts") != 0
        or proof.get("old_request_keys") != 0
        or proof.get("old_confirmation_unconsumed") is not True
        or proof.get("current_issue", {}).get("revision") != 1
        or proof.get("current_issue", {}).get("status") != "open"
        or proof.get("case_id") != decision["case_id"]
        or proof.get("marker") != decision["marker"]
        or proof.get("rejected_command_id") != rejected["original"]["command_id"]
    ):
        raise ValueError("Exact proved rejection and explicit independent triage intent required")


def load_retest():
    path = ROOT / "tools/wave22_shared_retest.py"
    if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != RETEST_SHA:
        raise ValueError("Frozen actual Retest source changed")
    spec = importlib.util.spec_from_file_location("wave22_root_triage_frozen_retest", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--marker", required=True)
    parser.add_argument("--fresh-generation", required=True)
    parser.add_argument("--decision", type=Path, required=True)
    parser.add_argument("--confirm")
    parser.add_argument("--review-digest")
    parser.add_argument("--recover")
    args = parser.parse_args()
    module = load_retest()
    decision = module.first.private_json(args.decision)
    proof_path = (ROOT / decision["readback_reference"]).resolve()
    expected = (
        ROOT.parent
        / "docs/reports/evidence/pdos-next-wave22-20261003"
        / "retest-triage-rejected-no-write-readback-v1.json"
    )
    if proof_path != expected or proof_path.is_symlink():
        raise ValueError("Exact Root readback path required")
    raw = proof_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != decision["readback_sha256"]:
        raise ValueError("Root no-write readback changed")
    proof = json.loads(raw)

    class Continuation(module.SharedRetest):
        def step(self, label, *values, **options):
            if label == "triage":
                check_decision(decision, proof, self.data["requests"]["triage"])
                label = NEW_LABEL
            return super().step(label, *values, **options)

    try:
        tool = Continuation(
            args.marker,
            fresh_generation=args.fresh_generation,
            confirm=args.confirm,
            review_digest=args.review_digest,
            recover=args.recover,
        )
        if (
            decision["marker"] != args.marker
            or decision["fresh_generation"] != args.fresh_generation
            or decision["case_id"] != tool.data["case_id"]
        ):
            raise ValueError("New triage intent is outside the actual selected case")
        check_decision(decision, proof, tool.data["requests"]["triage"])
        previous = tool.data.get("explicit_triage_continuation")
        if previous is not None and previous != decision:
            raise ValueError("Original continuation intent changed")
        if previous is None:
            tool.data["explicit_triage_continuation"] = decision
            tool.save()
        tool.quality()
        print(json.dumps({"phase": tool.data["phase"], "old_triage_preserved": True}))
    except module.Pending as pending:
        value = tool.data["requests"][pending.label]
        print(
            json.dumps(
                {
                    "state": "awaiting_confirmation",
                    "label": pending.label,
                    "tier": value["tier"],
                    "review_digest": value["review_digest"],
                    "review": value["preview"]["review"],
                    "expires_at": value["preview"]["expires_at"],
                    "submitted": False,
                },
                ensure_ascii=False,
            )
        )
    except module.Unknown as failure:
        print(json.dumps({"state": "unknown", "label": failure.label, "reissued": False}))
        raise SystemExit(3) from None
    except Exception as failure:
        print(
            json.dumps(
                {
                    "state": "rejected",
                    "error_type": type(failure).__name__,
                    "code": getattr(failure, "code", None),
                }
            )
        )
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
