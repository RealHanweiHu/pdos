"""One offline form-to-real-Payload contract check, no public transport."""

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from local_environment import ROOT, SERVER
from wave16_check import source_files


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    report = ROOT.parent / "docs/reports/evidence/pdos-next-wave17-20261003"
    output = report / "root-candidate-form-payload-contract-v1.json"
    if output.exists():
        raise RuntimeError("Preserve previous cross-language contract evidence")
    stage = ROOT / "staging/wave17"
    dependencies = {
        name: sha(stage / name)
        for name in ("candidate-form-contract.ts", "candidate-form.tsx", "candidate_commands.py")
    }
    public = source_files()
    sys.path.insert(0, str(SERVER))
    sys.path.insert(0, str(stage))
    from candidate_commands import semantic

    identities = [f"00000000-0000-4000-8000-{i:012d}" for i in range(1, 15)]
    source = {
        "artifact_id": identities[7],
        "expected_revision": 2,
        "line": 4,
        "quote": "原文 11.0000",
    }
    mapping = {
        "failure_id": "a" * 64,
        "run": {
            "id": identities[8],
            "revision": 3,
            "kind": "verification_run",
            "key": None,
        },
        "sample_id": identities[9],
        "sample_revision": 1,
        "actual_configuration_id": identities[10],
        "actual_configuration_revision": 2,
        "item_id": "length",
        "measurement_id": identities[11],
        "projection_id": identities[12],
        "applicability_sources": [source],
    }
    fixture = {
        "scope": {
            "tenant_id": identities[0],
            "product_id": identities[1],
            "project_id": identities[2],
            "principal_id": identities[3],
            "issue_id": identities[4],
            "capa_id": identities[5],
            "current_issue": {"id": identities[6], "revision": 9},
            "origin_issue": {"id": identities[13], "revision": 6},
            "failure_ids": ["a" * 64],
            "visibility": "private",
            "issue_label": "仅离线请求样本",
            "capa_label": "未保存",
        },
        "materials": {
            "links": [],
            "mappings": [
                {
                    "mapping": mapping,
                    "label": "精确映射样本",
                    "visibility": "private",
                    "original_value": "11.0000",
                    "conditions": "23°C / dry / A",
                    "occurred_at": "2026-10-03T08:08:20.788303+00:00",
                    "original_timezone": "UTC",
                    "detail": "仅请求结构，非实际复验",
                }
            ],
            "sources": [{"reference": source, "title": "原文出处样本", "visibility": "private"}],
        },
    }
    javascript = r"""
const fs = require('node:fs');
const ts = require(process.argv[1]);
const raw = fs.readFileSync(process.argv[2], 'utf8');
const fixture = JSON.parse(fs.readFileSync(0, 'utf8'));
const js = ts.transpileModule(raw, { compilerOptions: { target: ts.ScriptTarget.ES2022,
  module: ts.ModuleKind.CommonJS, strict: true } }).outputText;
const holder = { exports: {} };
new Function('exports', 'module', js)(holder.exports, holder);
const m = holder.exports;
const choice = fixture.materials.mappings[0].mapping;
const source = fixture.materials.sources[0].reference;
const base = { links: [], mappings: [], sources: [],
  reason: '保留部分候选，结论未知', visibility: 'private' };
const partial = m.candidatePayload(fixture.scope, fixture.materials,
  { ...base, mappings: [m.candidateMappingKey(choice)], sources: [m.candidateSourceKey(source)] });
const empty = m.candidatePayload(fixture.scope, fixture.materials, base);
if (!partial || !empty) throw new Error('Actual form helper failed partial request');
process.stdout.write(JSON.stringify({ partial, empty }));
"""
    run = subprocess.run(
        [
            "node",
            "-e",
            javascript,
            str(ROOT / "web/node_modules/typescript"),
            str(stage / "candidate-form-contract.ts"),
        ],
        input=json.dumps(fixture, ensure_ascii=False),
        capture_output=True,
        text=True,
        check=False,
    )
    (report / "root-candidate-form-payload-contract-v1.log").write_text(
        run.stdout + "\n" + run.stderr
    )
    if run.returncode:
        raise RuntimeError("Form helper failed; raw local fixture log preserved")
    produced = json.loads(run.stdout)
    for name, payload in produced.items():
        if semantic(payload) != payload or payload["expected_issue_revision"] != 9:
            raise RuntimeError(f"Real Python payload semantics differ from form: {name}")
        if "confirmation_token" in payload or "stable_anchor" in payload:
            raise RuntimeError("Form emitted a host-only or confirmation field")
    partial = produced["partial"]
    if partial["mappings"] != [mapping] or partial["sources"] != [source]:
        raise RuntimeError("Form rewrote complete mapping or exact source strings")
    if produced["empty"]["mappings"] or produced["empty"]["sources"]:
        raise RuntimeError("Partial empty request inferred additional facts")
    stable = public == source_files() and dependencies == {
        name: sha(stage / name) for name in dependencies
    }
    with output.open("x") as handle:
        json.dump(
            {
                "status": "PASS" if stable else "FAILED_SOURCE_CHANGED",
                "observed_at": datetime.now(UTC).isoformat(),
                "source_sha256": dependencies,
                "public_source_stable": public == source_files(),
                "staged_source_stable": stable,
                "node_exit_code": run.returncode,
                "checks": [
                    "Actual TS candidatePayload revalidates with actual Python canonical semantic",
                    "Current CAS9 remains distinct from origin6",
                    "Whole exact pair/nullable fields/source quote preserved",
                    "Empty candidate infers no mapping, observation or effective result",
                    "No token, anchor, inspection, approval or qualification fields produced",
                ],
                "raw_log_sha256": sha(report / "root-candidate-form-payload-contract-v1.log"),
                "fixture_only": True,
                "database_connections": 0,
                "public_operations": 0,
                "not_pg_or_browser_acceptance": True,
            },
            handle,
            ensure_ascii=False,
            indent=2,
        )
        handle.write("\n")
    print("Actual TS-to-Python candidate payload contract PASS", flush=True)
    if not stable:
        raise RuntimeError("Source changed during contract check")


if __name__ == "__main__":
    main()
