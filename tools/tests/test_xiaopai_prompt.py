import json
import shutil
import sys
from pathlib import Path

from pdos_next.agent.kernel.prompt_admin import create_draft, register_draft

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from xiaopai_prompt import evaluate_ab  # noqa: E402

PACKAGE = ROOT / "server/pdos_next/agent/prompt_packages"


def inputs(tmp_path):
    package = tmp_path / "prompts"
    shutil.copytree(PACKAGE, package)
    case = {
        "id": "CTX-SYNTHETIC",
        "turns": [{"role": "user", "content": "固定合成历史"}],
        "final_prompt": "回答当前合成问题",
    }
    questions = {
        "version": "xiaopai-context-eval/v0",
        "status": "draft_for_review",
        "synthetic": True,
        "trusted_root": False,
        "cases": [case],
    }
    expanded = {
        case["id"]: [*case["turns"], {"role": "user", "content": case["final_prompt"]}],
    }
    question_path = tmp_path / "questions.json"
    expanded_path = tmp_path / "expanded.json"
    question_path.write_text(json.dumps(questions))
    expanded_path.write_text(json.dumps(expanded))
    return package, question_path, expanded_path


def test_ab_report_changes_only_prompt_and_never_fakes_model_quality(tmp_path):
    package, questions, expanded = inputs(tmp_path)
    draft = create_draft(package, "1.0.1-draft", source="1.0.0")
    path = package / "versions/1.0.1-draft.md"
    path.write_text(draft.content + "Keep the synthetic evaluation boundary explicit.\n")
    register_draft(package, draft.version)
    report = evaluate_ab(package, questions, expanded, "1.0.0", "1.0.1-draft")
    assert report["schema"] == "xiaopai-prompt-ab/v1"
    assert report["control_status"] == "passed"
    assert report["quality_status"] == "not_scored"
    assert report["provider_calls"] == report["database_operations"] == 0
    assert report["question_set"]["trusted_root"] is False
    assert report["baseline"]["version"] == "1.0.0"
    assert report["candidate"]["version"] == "1.0.1-draft"
    assert report["baseline"]["content_digest"] != report["candidate"]["content_digest"]
    assert len(report["cases"]) == 1
    assert report["cases"][0]["model_quality"] == "not_run"
    assert "+Keep the synthetic evaluation boundary explicit." in report["diff"]
    assert report["regressions"] == []
