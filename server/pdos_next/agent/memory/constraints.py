"""Paraphrased constraints need the owner's confirmation (P85 第 7 项, P32 第 4 项补充).

Two paths:

* The owner adds or confirms a constraint in “本次携带”; it is written as the
  owner (``origin='human'`` work-state version) and marked 本人确认.
* 小Pai may *propose* a paraphrase ("按上次那样" → "只看 B2 版本、按欧标"). It is
  stored as pending and never sent to the model until the owner confirms it.

The frozen prompt 1.0.0 tells the model that paraphrases are rejected, so a
model proposal is an output-contract change: it needs a new prompt version and
Prompt A/B (memory design §4.1). Until a released prompt version is listed in
``PARAPHRASE_PROMPT_VERSIONS`` no model proposal is admitted at all.

Write gate (P84 第 7 项): only the owner's own words can trigger a proposal.
The trigger must be a verbatim fragment of the owner's message with page
material removed, and must contain an explicit reference or "remember"
expression from the fixed list below. Text from originals, mail, IM or OCR
(page material, tool results) can never trigger one.
"""

from uuid import NAMESPACE_URL, uuid5

from pdos_next.errors import DomainError

PARAPHRASE_PROMPT_VERSIONS = frozenset()  # No released prompt instructs proposals yet.
PENDING_LIMIT = 10
PER_RUN_LIMIT = 3
TEXT_LIMIT = 200
# Fixed, reviewed reference/"remember" expressions. Matching is literal.
MEMORY_INTENT = (
    "按上次", "照上次", "跟上次", "和上次", "像上次", "同上次", "还是上次", "上次那样",
    "老规矩", "还是那样", "记住", "以后都", "以后一律", "每次都",
)


def clean_text(value):
    text = " ".join(str(value or "").split())
    if not 1 <= len(text) <= TEXT_LIMIT:
        raise DomainError("VALIDATION_FAILED", f"约束须为 1–{TEXT_LIMIT} 个字。", 422)
    return text


def human_identity(session_id, text):
    return str(uuid5(NAMESPACE_URL, f"pdos-human-constraint:{session_id}:{text}"))


def proposal_identity(run_id, text):
    return str(uuid5(NAMESPACE_URL, f"pdos-paraphrase-constraint:{run_id}:{text}"))


def prompt_version(run):
    return ((run.versions or {}).get("prompt_identities", {}).get("main") or {}).get("version")


def admissible(run, proposals, goals, removed, *, page_material):
    """Return (pending items, rejected reasons). Deterministic; no model call."""
    from pdos_next.agent.kernel.work_state import user_goal

    if not proposals:
        return [], []
    if prompt_version(run) not in PARAPHRASE_PROMPT_VERSIONS:
        return [], [{"reason": "paraphrase_prompt_not_released"}]
    if (run.trigger != "conversation" or (run.versions or {}).get("dingtalk")
            or (run.versions or {}).get("memory_mode", {}).get("off")):
        return [], [{"reason": "paraphrase_channel_excluded"}]
    if not isinstance(proposals, list) or len(proposals) > PER_RUN_LIMIT:
        return [], [{"reason": "invalid_paraphrase_proposals"}]
    accepted, rejected = [], []
    for proposal in proposals:
        if not isinstance(proposal, dict) or set(proposal) != {"basis_run_id", "trigger", "text"}:
            rejected.append({"reason": "invalid_paraphrase_shape"})
            continue
        basis, trigger, text = proposal["basis_run_id"], proposal["trigger"], proposal["text"]
        own = user_goal(goals.get(basis, "")) if isinstance(basis, str) else ""
        if (not isinstance(trigger, str) or not trigger.strip() or basis not in goals
                or trigger not in own):
            rejected.append({"reason": "trigger_not_owner_words"})
            continue
        if not any(expression in trigger for expression in MEMORY_INTENT):
            rejected.append({"reason": "trigger_not_explicit_reference"})
            continue
        try:
            text = clean_text(text)
        except DomainError:
            rejected.append({"reason": "invalid_paraphrase_text"})
            continue
        if any(text in material or material and material in text
               for material in page_material if len(material) >= 6):
            rejected.append({"reason": "text_from_untrusted_material"})
            continue
        identity = proposal_identity(basis, text)
        if identity in removed:
            rejected.append({"reason": "dismissed_by_user", "id": identity})
            continue
        accepted.append({"id": identity, "run_id": basis, "text": text,
                         "trigger": trigger, "proposed_by": "xiaopai"})
    return accepted, rejected


def page_material(goals):
    """The untrusted page-material part of each message (after the boundary)."""
    from pdos_next.agent.kernel.work_state import PAGE_MATERIAL_BOUNDARY

    return [value.partition(PAGE_MATERIAL_BOUNDARY)[2].strip() for value in goals.values()
            if PAGE_MATERIAL_BOUNDARY in value]


def add(body, *, session_id, run_id, text):
    text = clean_text(text)
    identity = human_identity(session_id, text)
    # The owner re-adding a deleted constraint is the owner's own decision.
    body["removed_constraints"] = sorted(set(body["removed_constraints"]) - {identity})
    if not any(item["id"] == identity for item in body["constraints"]):
        body["constraints"].append({"id": identity, "run_id": run_id, "text": text,
                                    "origin": "human"})


def confirm(body, identity):
    pending = body.get("pending_constraints", [])
    item = next((value for value in pending if value["id"] == identity), None)
    if item is None:
        raise DomainError("NOT_FOUND", "这条待确认的约束已不存在。", 404)
    body["pending_constraints"] = [value for value in pending if value["id"] != identity]
    if not any(value["id"] == identity for value in body["constraints"]):
        body["constraints"].append({"id": identity, "run_id": item["run_id"],
                                    "text": item["text"], "origin": "human_confirmed"})


def dismiss(body, identity):
    pending = body.get("pending_constraints", [])
    if not any(value["id"] == identity for value in pending):
        raise DomainError("NOT_FOUND", "这条待确认的约束已不存在。", 404)
    body["pending_constraints"] = [value for value in pending if value["id"] != identity]
    body["removed_constraints"] = sorted(set(body["removed_constraints"]) | {identity})


def merge_pending(body, accepted):
    existing = {value["id"] for value in body.get("pending_constraints", [])}
    active = {value["id"] for value in body["constraints"]}
    merged = [*body.get("pending_constraints", []),
              *(item for item in accepted if item["id"] not in existing | active)]
    body["pending_constraints"] = merged[-PENDING_LIMIT:]


def void_pending(body):
    """The owner said it was only discussion: drop every unconfirmed paraphrase for good."""
    pending = body.get("pending_constraints", [])
    if pending:
        body["removed_constraints"] = sorted(
            set(body["removed_constraints"]) | {value["id"] for value in pending})
        body["pending_constraints"] = []
