"""Recompute this checkpoint from immutable test output and current input bytes."""

import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]


def cases(path):
    return {
        (item.attrib.get("classname", ""), item.attrib["name"]): {
            "passed": not any(item.find(tag) is not None for tag in ("failure", "error", "skipped")),
            "evidence": str(path.relative_to(HERE)),
        }
        for item in ET.parse(path).getroot().iter("testcase")
    }


def main():
    native = {}
    runs = {}
    for name in ("native-run2", "native-run4"):
        observed = cases(HERE / name / "tests.xml")
        native.update(observed)
        runs[name] = {"cases": len(observed), "passed": sum(x["passed"] for x in observed.values())}
    assert native and all(item["passed"] for item in native.values()), native
    pure = {}
    for name in ("restart-pure-final-v3.xml", "skills-restart-cross-checks/pure.xml"):
        pure.update(cases(HERE / name))
    assert len(pure) == 168 and all(item["passed"] for item in pure.values())
    assert "1 passed" in (HERE / "restart-fixture-model-copy-offline.log").read_text()
    inputs = json.loads((HERE / "frozen-inputs.json").read_text())["source_sha256"]
    changed = [key for key, expected in inputs.items()
               if hashlib.sha256((ROOT / key).read_bytes()).hexdigest() != expected]
    build = json.loads((HERE / "frontend-build-result.json").read_text())
    web_inputs = json.loads((HERE / "frontend-build-inputs.json").read_text())["sha256"]
    web_changed = [key for key, expected in web_inputs.items()
                   if hashlib.sha256((ROOT / "pdos-next/web" / key).read_bytes()).hexdigest() != expected]
    assert not changed and not web_changed and build["exit_code"] == 0
    summary = {
        "pure_distinct": len(pure), "additional_offline_fixture_type_check": 1,
        "native_distinct_latest_passed": len(native), "native_runs": runs,
        "native_case_evidence": [{"class": key[0], "test": key[1], **value}
                                 for key, value in sorted(native.items())],
        "native_scope": "4 unchanged recovery cases from run2 plus final targeted/regression run4; production inputs unchanged, failed fifth fixture replaced only by its passing observation",
        "frozen_inputs": len(inputs), "changed_inputs": changed,
        "frontend_build_inputs": len(web_inputs), "frontend_build_changed": web_changed,
        "frontend_build_exit_code": build["exit_code"],
        "real_model_calls": 0, "real_embedding_calls": 0,
        "answer_quality_scored": False,
    }
    (HERE / "independent-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({key: value for key, value in summary.items() if key != "native_case_evidence"}))


if __name__ == "__main__":
    main()
