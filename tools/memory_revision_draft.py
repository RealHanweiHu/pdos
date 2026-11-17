"""Prepare the draft version an adopted revision candidate names; never activates it.

记忆 M3 程序性闭环 (P88 第 3 项): an administrator adopting a revision candidate
only records which draft version to prepare. This offline step prepares it:

* prompt: ``prompt_admin.create_draft`` copies the base version into the prompt
  registry as ``draft`` (activation still needs ``tools/xiaopai_prompt.py
  activate`` with a passed A/B evaluation and a named reviewer);
* skill package: copies the base package to ``skill_packages/drafts/`` with the
  draft version. The skill catalog never loads that folder, so nothing changes for
  any tenant until a person edits the draft, runs its golden cases and enables and
  qualifies it by name.

Usage: python tools/memory_revision_draft.py '<decision draft JSON>'
       (the ``draft`` object of a skill revision decision).
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server"
SKILLS = SERVER / "pdos_next/agent/skill_packages"
PROMPTS = SERVER / "pdos_next/agent/prompt_packages"


def prepare(draft, *, skills=SKILLS, prompts=PROMPTS):
    version, base = draft["draft_version"], draft["base_version"]
    if not version.endswith("-draft") or version == base:
        raise SystemExit("A revision draft must be a new -draft version")
    if draft["target_kind"] == "prompt":
        sys.path.insert(0, str(SERVER))
        from pdos_next.agent.kernel.prompt_admin import create_draft

        create_draft(prompts, version, source=base)
        return {"prepared": "prompt", "version": version, "activated": False}
    if draft["target_kind"] != "skill_package":
        raise SystemExit("Unknown revision target")
    key = draft["key"]
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,79}", key):
        raise SystemExit("Unexpected skill key")
    source = Path(skills) / f"{key}.md"
    text = source.read_text()
    current = re.search(r"^version: (.+)$", text, re.M)
    if current is None or current.group(1).strip() != base:
        raise SystemExit("The skill package is no longer at the reviewed base version")
    target = Path(skills) / "drafts" / f"{key}-{version}.md"
    if target.exists():
        raise SystemExit("This draft already exists")
    target.parent.mkdir(exist_ok=True)
    target.write_text(text.replace(f"version: {base}", f"version: {version}", 1))
    return {"prepared": "skill_package", "path": str(target.relative_to(ROOT))
            if target.is_relative_to(ROOT) else str(target), "activated": False}


if __name__ == "__main__":
    print(json.dumps(prepare(json.loads(sys.argv[1])), ensure_ascii=False))
