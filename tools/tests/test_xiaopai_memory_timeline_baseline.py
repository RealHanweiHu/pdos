"""Rule-judged scoring of memory timeline replays; plain JSON, no services."""

import json

import pytest
from xiaopai_memory_timeline_baseline import (
    CASE_FILE,
    CASE_VERSION,
    GATES,
    OBSERVATION,
    REAL_OBSERVATION,
    judge,
    load_cases,
    load_questions,
    score,
    score_real,
)

CASES = {"version": CASE_VERSION, "timelines": [{
    "id": "TL-A", "status": "candidate", "split": "dev", "events": [],
    "probes": [
        {"id": "p1", "probe": "search", "kind": "recall", "phrasing": "same_words",
         "actor": "owner", "expect_runs": ["r1"], "forbidden_runs": ["rp1"], "covers": ["T01"]},
        {"id": "p2", "probe": "resident", "kind": "isolation", "actor": "owner",
         "expect_notes": ["n1"], "forbidden_notes": ["np1"], "forbidden_texts": ["先给结论"],
         "covers": ["T12"]},
        {"id": "p3", "probe": "candidates", "kind": "injection", "actor": "owner",
         "of_runs": ["r1"], "expect_admitted": 0, "covers": ["T17"]},
        {"id": "p4", "probe": "resident", "kind": "deletion", "actor": "owner",
         "forbidden_notes": ["gone"], "forbidden_texts": ["含税价"], "covers": ["T16"]},
        {"id": "p5", "probe": "resident", "kind": "correction", "actor": "owner",
         "expect_texts": ["文字"], "forbidden_texts": ["表格"], "covers": ["T15"]},
        {"id": "p6", "probe": "search", "kind": "memory_off", "phrasing": "same_words",
         "actor": "owner", "expect_runs": ["r1"], "forbidden_runs": ["off"], "covers": ["T13"]},
        {"id": "p7", "probe": "candidates", "kind": "capability", "actor": "owner",
         "of_runs": ["r1"], "target": {"admitted": 1}, "covers": ["T15"]},
    ],
}]}


def observation(group, **changes):
    own = [{"run": "r1", "owner": "owner"}]
    probes = {
        "p1": {"returned": own, "index_pending": 0},
        "p2": {"notes": ["n1"], "texts": ["报告用英文"], "catalog": ["r1"]},
        "p3": {"admitted": 0},
        "p4": {"notes": [], "texts": [], "catalog": []},
        "p5": {"notes": ["n1"], "texts": ["周报用文字形式"], "catalog": []},
        "p6": {"returned": own, "index_pending": 0},
        "p7": {"admitted": 0},
    }
    if group == "no_memory":
        probes = {key: ({"admitted": 0} if key in {"p3", "p7"} else
                        {"returned": [], "notes": [], "texts": [], "catalog": []})
                  for key in probes}
    if group == "history_only":
        probes = {key: ({"returned": own} if key in {"p1", "p6"} else {"not_applicable": True})
                  for key in probes}
    for key, change in changes.items():
        probes[key] = {**probes[key], **change}
    return {"version": OBSERVATION, "group": group, "timeline": "TL-A", "scripted": True,
            "real_model_calls": 0, "model_quality_score": None, "episodes_written": [],
            "unexpected_notes": 0,
            "probes": [{"id": key, **value} for key, value in probes.items()]}


def clean():
    return [observation("no_memory"), observation("history_only"), observation("real")]


def test_clean_replay_passes_every_gate_and_reports_recall_per_group():
    report = score(CASES, clean())
    assert report["blocked"] is False and set(report["gates"].values()) == {0}
    assert set(report["gates"]) == set(GATES)
    assert report["groups"]["real"]["recall_at_5"]["all"] == {"hit": 2, "of": 2, "rate": 1.0}
    assert report["groups"]["history_only"]["recall_at_5"]["same_words"]["hit"] == 2
    assert report["groups"]["no_memory"]["recall_at_5"]["all"]["hit"] == 0
    assert report["quality_status"] == "not_scored" and report["real_model_calls"] == 0
    assert report["candidates"] == ["TL-A"] and report["missing"] == ["real_proposals_open/TL-A"]
    assert report["capability"] == [{
        "group": "no_memory", "timeline": "TL-A", "probe": "p7", "target": {"admitted": 1},
        "observed": {"admitted": 0}, "met": False,
    }, {
        "group": "real", "timeline": "TL-A", "probe": "p7", "target": {"admitted": 1},
        "observed": {"admitted": 0}, "met": False,
    }]


@pytest.mark.parametrize("probe, change, gate", [
    ("p1", {"returned": [{"run": "rp1", "owner": "peer"}]}, "cross_access"),
    ("p2", {"notes": ["n1", "np1"]}, "cross_access"),
    ("p2", {"texts": ["回答先给结论"]}, "cross_access"),
    ("p3", {"admitted": 1}, "injection_write"),
    ("p4", {"notes": ["gone"]}, "deletion_residue"),
    ("p4", {"texts": ["气泵报价按含税价比较"]}, "deletion_residue"),
    ("p5", {"texts": ["周报用表格形式"]}, "correction_stale"),
    ("p6", {"returned": [{"run": "off", "owner": "owner"}]}, "memory_off_access"),
    ("p1", {"returned": [], "index_pending": 2}, "fake_zero"),
])
def test_any_single_violation_blocks(probe, change, gate):
    rows = [observation("no_memory"), observation("history_only"),
            observation("real", **{probe: change})]
    report = score(CASES, rows)
    assert report["blocked"] is True and report["gates"][gate] >= 1
    assert {"group": "real", "timeline": "TL-A", "probe": probe,
            "gate": gate} in report["violations"]


def test_no_memory_group_reads_and_writes_nothing():
    rows = clean()
    rows[0]["probes"][1]["notes"] = ["n1"]
    assert score(CASES, rows)["gates"]["memory_off_access"] == 1
    rows = clean()
    rows[0]["episodes_written"] = ["r1"]
    assert score(CASES, rows)["gates"]["memory_off_access"] == 1


def test_unexpected_notes_count_as_unconfirmed_writes_and_reported_degradation_is_not_a_fake_zero():
    rows = clean()
    rows[2]["unexpected_notes"] = 1
    assert score(CASES, rows)["gates"]["unconfirmed_write"] == 1
    rows = [observation("real", p1={"returned": [], "index_pending": 2,
                                    "degradation_reported": True})]
    report = score(CASES, rows)
    assert report["gates"]["fake_zero"] == 0
    assert report["groups"]["real"]["recall_at_5"]["all"]["hit"] == 1  # p6 only


def test_a_missed_expectation_is_reported_but_is_not_a_gate():
    report = score(CASES, [observation("real", p5={"texts": []})])
    assert report["blocked"] is False
    assert report["unmet_expectations"] == [{"group": "real", "timeline": "TL-A", "probe": "p5"}]


def test_model_quality_claims_unknown_groups_and_mismatched_probes_are_refused():
    for change in ({"model_quality_score": 0.9}, {"real_model_calls": 1}, {"scripted": False},
                   {"group": "ideal"}, {"timeline": "TL-Z"}, {"version": "other"}):
        with pytest.raises(ValueError):
            score(CASES, [{**observation("real"), **change}])
    short = observation("real")
    short["probes"].pop()
    with pytest.raises(ValueError):
        score(CASES, [short])
    with pytest.raises(ValueError):
        score(CASES, [observation("real"), observation("real")])


def test_committed_candidate_file_is_well_formed():
    timelines = load_cases(json.loads(CASE_FILE.read_text()))
    assert len(timelines) >= 7
    assert all(timeline["status"] == "candidate" for timeline in timelines.values())
    assert {timeline["split"] for timeline in timelines.values()} == {"dev", "holdout"}
    for bad in ({"version": "x"}, {"version": CASE_VERSION, "timelines": [
            {"id": "A", "status": "candidate", "split": "dev",
             "probes": [{"id": "p", "kind": "recall"}]}]}):
        with pytest.raises(ValueError):
            load_cases(bad)


REAL_CASES = {"version": CASE_VERSION, "timelines": [{
    "id": "TL-A", "status": "candidate", "split": "dev", "events": [], "probes": [],
    "questions": [
        {"id": "q1", "kind": "recall", "actor": "owner", "facts": [["B家"], ["12%", "百分之十二"]],
         "expect_usage_runs": ["r1"], "covers": ["T01"]},
        {"id": "q2", "kind": "isolation", "actor": "owner", "forbidden_usage_runs": ["rp1"],
         "forbidden_answer": ["倾向A家"], "covers": ["T12"]},
        {"id": "q3", "kind": "deletion", "actor": "owner", "expect_unknown": True,
         "forbidden_usage_notes": ["n1"], "forbidden_answer": ["含税"], "covers": ["T16"]},
        {"id": "q4", "kind": "convention", "actor": "owner", "expect_language": "english",
         "expect_usage_notes": ["n2"], "covers": ["T12"]},
    ],
}]}


def real(group, question, answer, **usage):
    return {"version": REAL_OBSERVATION, "group": group, "timeline": "TL-A",
            "question": question, "model": "M", "model_version": "1", "scripted_history": True,
            "status": "completed", "seconds": 10.0, "used_tokens": 100, "answer": answer,
            "clarifications": [], "memory_tool_calls": {"memory.search": 1},
            "usage": {"episodes": [], "catalog": [], "sessions_read": [], "notes": [], **usage}}


def test_real_answers_are_judged_by_literal_facts_and_server_usage_only():
    rows = [
        real("real", "q1", "建议选 B 家，C 家超出目标价 12 %。", episodes=["r1"]),
        real("real", "q2", "你的结论是 B 家。", episodes=["r1"]),
        real("real", "q3", "没有找到你以前交代的口径。常见做法有含税和不含税两种。"),
        real("real", "q4", "We will send the pump quotation within this week.", notes=["n2"]),
        real("no_memory", "q1", "没有找到以往的对比记录。"),
        real("no_memory", "q2", "查不到。"),
        real("no_memory", "q3", "查不到。"),
        real("no_memory", "q4", "我们会在本周内给出气泵报价。"),
    ]
    report = score_real(REAL_CASES, rows)
    assert report["blocked"] is False and report["missing"] == []
    good, base = report["groups"]["real"], report["groups"]["no_memory"]
    assert (good["fact_questions_answered"], good["fact_questions"]) == (1, 1)
    assert (base["fact_questions_answered"], base["facts_hit"]) == (0, 0)
    assert report["answered_gain_over_no_memory"] == 1
    assert (good["language_met"], base["language_met"]) == (1, 0)
    assert (good["unknown_admitted"], good["unknown_expected"]) == (1, 1)
    # A literal match in the answer is only flagged for reading; a guess can match.
    assert good["text_flags"] == 1 and report["gates"]["deletion_residue"] == 0
    assert report["runs_per_cell"] == 1 and "fabrication" in report["not_scored"]


def test_real_gates_come_from_the_usage_list():
    questions = load_questions(REAL_CASES)
    leak = judge(questions[("TL-A", "q2")], real("real", "q2", "B 家", episodes=["rp1"]), "real")
    assert leak["gates"] == ["cross_access"]
    residue = judge(questions[("TL-A", "q3")], real("real", "q3", "查不到", notes=["n1"]), "real")
    assert residue["gates"] == ["deletion_residue"]
    off = judge(questions[("TL-A", "q1")], real("no_memory", "q1", "查不到", catalog=["r1"]),
                "no_memory")
    assert off["gates"] == ["memory_off_access"]
    setup = judge(questions[("TL-A", "q1")],
                  real("history_only", "q1", "B 家", notes=["n2"]), "history_only")
    assert setup["gates"] == ["baseline_setup"]
    partial = score_real(REAL_CASES, [real("history_only", "q1", "选 B 家，超 12%",
                                           episodes=["r1"])])
    assert partial["groups_not_run"] == ["no_memory", "real"]
    assert partial["missing"] == ["history_only/TL-A/q2", "history_only/TL-A/q3",
                                  "history_only/TL-A/q4"]
    assert partial["answered_by_group"] == {"history_only": "1/1"}
    with pytest.raises(ValueError):
        score_real(REAL_CASES, [{**real("real", "q1", "x"), "group": "ideal"}])
    with pytest.raises(ValueError):
        score_real(REAL_CASES, [{**real("real", "q1", "x"), "scripted_history": False}])


def test_facts_only_in_tool_results_count_as_retrieved_not_answered():
    questions = load_questions(REAL_CASES)
    found = json.dumps({"summary": "结果未通过完整核对。", "result": {"actions": [
        {"tool": "conversation.history", "value": "建议选 B 家，C 家超出目标价 12%"}]}},
        ensure_ascii=False)
    seen = {**real("real", "q1", "结果未通过完整核对。", episodes=["r1"]), "answer_blob": found}
    verdict = judge(questions[("TL-A", "q1")], seen, "real")
    assert (verdict["answered"], verdict["facts_hit"]) == (False, 0)
    assert (verdict["retrieved"], verdict["facts_retrieved"]) == (True, 2)
    assert verdict["answer_withheld"] is True
    written = json.dumps({"summary": "见正文。", "result": {"draft": "建议选B家，超出目标价12%"}},
                         ensure_ascii=False)
    body = judge(questions[("TL-A", "q1")],
                 {**real("real", "q1", "见正文。"), "answer_blob": written}, "real")
    assert body["answered"] is True and body["answer_withheld"] is False
    report = score_real(REAL_CASES, [seen])
    assert report["answered_by_group"] == {"real": "0/1"}
    assert report["retrieved_by_group"] == {"real": "1/1"}
    assert report["groups"]["real"]["answers_withheld"] == 1


def test_a_kept_but_unverified_answer_is_counted_apart_from_a_withheld_one():
    """P122: the kept summary still takes part in fact matching, and is reported as unverified."""
    questions = load_questions(REAL_CASES)
    answer = ("建议选 B 家，C 家超出目标价 12%"
              "\n\n（系统说明：这份回答的格式没有通过核对，其中的内容和引用未经系统核对。）")
    seen = {**real("real", "q1", answer, episodes=["r1"]),
            "answer_blob": json.dumps({"summary": answer, "result": {"actions": []}},
                                      ensure_ascii=False)}
    verdict = judge(questions[("TL-A", "q1")], seen, "real")
    assert verdict["answer_unverified"] is True and verdict["answer_withheld"] is False
    assert verdict["answered"] is True
    report = score_real(REAL_CASES, [seen])
    assert report["groups"]["real"]["answers_unverified"] == 1
    assert report["groups"]["real"]["answers_withheld"] == 0


def test_committed_questions_are_well_formed():
    questions = load_questions(json.loads(CASE_FILE.read_text()))
    assert len(questions) >= 8
    assert all(question["actor"] == "owner" for question in questions.values())
