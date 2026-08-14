"""Capture and verify read-only evidence for the S5-1 real-application gate."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from app.db.engine import get_engine
from app.integrations.dingtalk_exit_evidence import (
    DingTalkExitEvidenceError,
    capture_dingtalk_exit_baseline,
    parse_dingtalk_exit_baseline,
    serialize_dingtalk_exit_baseline,
    verify_dingtalk_exit_evidence,
)


def _baseline_text(source: str) -> str:
    if source == "-":
        return sys.stdin.read()
    path = Path(source)
    if not path.is_file() or path.is_symlink():
        raise DingTalkExitEvidenceError("DINGTALK_EVIDENCE_BASELINE_FILE_INVALID")
    try:
        return path.read_text()
    except (OSError, UnicodeError) as error:
        raise DingTalkExitEvidenceError("DINGTALK_EVIDENCE_BASELINE_FILE_INVALID") from error


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect read-only S5-1 exit evidence")
    subparsers = parser.add_subparsers(dest="action", required=True)
    capture = subparsers.add_parser("capture", help="write a pre-smoke baseline to stdout")
    capture.add_argument("--tenant-slug", required=True)
    capture.add_argument("--project-code", required=True)
    capture.add_argument("--release-sha", required=True)
    verify = subparsers.add_parser("verify", help="verify post-smoke evidence")
    verify.add_argument("--baseline", required=True, help="baseline path or - for stdin")
    verify.add_argument("--release-sha", required=True)
    arguments = parser.parse_args()
    engine = get_engine()
    try:
        if arguments.action == "capture":
            baseline = capture_dingtalk_exit_baseline(
                engine=engine,
                tenant_slug=arguments.tenant_slug,
                project_code=arguments.project_code,
                release_sha=arguments.release_sha,
            )
            sys.stdout.write(serialize_dingtalk_exit_baseline(baseline))
            return 0
        baseline = parse_dingtalk_exit_baseline(_baseline_text(arguments.baseline))
        report = verify_dingtalk_exit_evidence(
            engine=engine,
            baseline=baseline,
            release_sha=arguments.release_sha,
        )
    except DingTalkExitEvidenceError as error:
        print(f"FAIL evidence_contract: {error}")
        return 1
    except SQLAlchemyError:
        print("FAIL evidence_contract: DINGTALK_EVIDENCE_DATABASE_ERROR")
        return 1
    finally:
        engine.dispose()
    print(
        "EVIDENCE "
        f"release_sha={report.release_sha} "
        f"tenant_slug={report.tenant_slug} "
        f"project_code={report.project_code} "
        f"baseline_sha256={report.baseline_sha256} "
        f"verified_at={report.verified_at.isoformat()}"
    )
    for check in report.checks:
        print(f"{'PASS' if check.passed else 'FAIL'} {check.name}: {check.detail}")
    for attestation in report.human_attestations_required:
        print(f"HUMAN_REQUIRED: {attestation}")
    if not report.automated_ready:
        print("DingTalk automated exit evidence failed; no state was changed")
        return 1
    print("DingTalk automated exit evidence passed; human Exit Gate is still required")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
