"""Root-only READ ONLY observation of the actual saved synthetic completion."""

import hashlib
import json
import sys
from datetime import UTC, datetime
from uuid import UUID

from local_environment import ROOT, SERVER, read_state, verified

sys.path.insert(0, str(ROOT / "staging/wave17"))
sys.path.insert(0, str(SERVER))

from anchor import VersionRef  # noqa: E402
from anchor_storage import read_origin_descriptor  # noqa: E402
from pdos_next.database import engine_for  # noqa: E402
from pdos_next.domain.quality_execution.models import QualityIssueVersion  # noqa: E402
from pdos_next.errors import DomainError  # noqa: E402
from pdos_next.service import Context, digest  # noqa: E402
from sqlalchemy import select, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from wave16_check import source_files  # noqa: E402

REPORT = ROOT.parent / "docs/reports/evidence/pdos-next-wave17-20261003"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    target = REPORT / "origin-actual-readonly-v1.json"
    if target.exists():
        raise RuntimeError("Preserve previous observation; explicit new version required")
    state = verified(read_state())
    if state["port"] != 62513 or state["marker"] != "916f950f-2d2b-405d-b809-c15db75dc20c":
        raise RuntimeError("Wrong independent marked target")
    for field in ("admin_url", "app_url"):
        url = make_url(state[field])
        if url.host != "127.0.0.1" or url.port != 62513 or url.database != "pdos_test":
            raise RuntimeError("Explicit database identity differs")
    candidate = (
        ROOT.parent
        / "docs/reports/evidence/pdos-next-wave16-20261002/backend-candidate-source-v4.json"
    )
    public = json.loads(candidate.read_text())["files"]
    if source_files() != public:
        raise RuntimeError("Public source changed before observation")
    dependency_paths = [
        "anchor_storage.py",
        "anchor.py",
        "fact_atom_storage.py",
        "fact_storage_models.py",
        "fact_storage_codec.py",
        "facts.py",
        "paired.py",
        "lineage.py",
    ]
    dependencies = {p: sha(ROOT / "staging/wave17" / p) for p in dependency_paths}
    seed = ROOT / ".local/wave16-saved-ids.json"
    ids = json.loads(seed.read_text())
    tenant = UUID("1ad4cbb5-ddbb-4d6b-b2f7-0dd41c509f6b")
    actor = UUID("77465957-a05e-4663-85bf-34cd39ac43dd")
    pid = UUID("b1e23421-6c70-4fc5-a87f-96744baab2e8")
    engine = engine_for(state["app_url"])
    result = {
        "scope": "Actual existing local synthetic origin; no new fact/qualification/DDL",
        "target": "127.0.0.1:62513/pdos_test",
        "marker": state["marker"],
        "observed_at": datetime.now(UTC).isoformat(),
        "dependencies_sha256": dependencies,
        "public_candidate_sha256": sha(candidate),
        "saved_identity_source_sha256": sha(seed),
        "status": "FAILED",
    }
    try:
        with Session(engine) as s, s.begin():
            s.execute(text("SET TRANSACTION READ ONLY"))
            s.execute(
                text("SELECT set_config('pdos.tenant_id', :tenant, true)"), {"tenant": str(tenant)}
            )
            if s.scalar(text("SHOW transaction_read_only")) != "on":
                raise RuntimeError("Read-only transaction not established")
            row = s.scalar(
                select(QualityIssueVersion)
                .where(
                    QualityIssueVersion.tenant_id == tenant,
                    QualityIssueVersion.product_id == pid,
                    QualityIssueVersion.issue_id == UUID(ids["issue"]),
                    QualityIssueVersion.id == UUID(ids["complete_v6"]),
                )
                .execution_options(autoflush=False)
            )
            if row is None or row.revision != 6:
                raise RuntimeError("Actual saved completed origin missing")
            ref = VersionRef(id=row.id, revision=row.revision, snapshot_sha256=row.snapshot_sha256)
            read = read_origin_descriptor(s, Context(tenant, actor, actor), pid, row.issue_id, ref)
            result.update(
                {
                    "status": "PASS",
                    "transaction_read_only": True,
                    "origin_revision": read.origin.ref.revision,
                    "current_revision": read.current.ref.revision,
                    "full_descriptor_sha256": digest(read.model_dump(mode="json")),
                    "needs_lineage_owner": read.needs_lineage_owner,
                    "missing_owners": read.missing_owners,
                    "current_evidence_authorized": read.current_evidence_authorized,
                    "source_bytes_verified": read.source_bytes_verified,
                    "original_failures_verified": read.original_failures_verified,
                    "same_uow_consumption_attested": (
                        read.completion_group.same_uow_consumption_attested
                    ),
                    "preserved_actual_completion_clock": True,
                    "no_new_write_or_preview": True,
                }
            )
    except DomainError as failure:
        result["error"] = {"type": type(failure).__name__, "code": failure.code}
    except Exception as failure:
        result["error"] = {"type": type(failure).__name__}
    finally:
        engine.dispose()
    result["public_source_stable"] = source_files() == public
    result["staged_dependencies_stable"] = dependencies == {
        p: sha(ROOT / "staging/wave17" / p) for p in dependency_paths
    }
    with target.open("x") as output:
        json.dump(result, output, ensure_ascii=False, indent=2)
        output.write("\n")
    print(result["status"], result.get("error", {}))
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
