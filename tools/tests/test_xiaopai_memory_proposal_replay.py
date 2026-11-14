"""The fixed proposal expressions on the labelled replay set; plain JSON, no services.

The numbers below are what was measured when the lists were last changed
(P121 第 9 项, D476). They only go down: changing ``triggers`` so that more
labelled messages are wrongly admitted or missed fails here, and a deliberate
change must re-measure on a fresh held-out set and update the evidence.
"""

import json

import pytest
from pdos_next.agent.memory import triggers
from xiaopai_memory_proposal_replay import CASES, V1_NOTE_INTENT, report

# (false admits, misses) of the current lists, per split and rule.
MEASURED = {
    "tuning": {"remember": (1, 0), "alias": (0, 0), "correction": (0, 0), "discussion": (0, 0)},
    "dev": {"remember": (1, 1), "alias": (0, 0), "correction": (0, 1), "discussion": (0, 1)},
    "heldout": {"remember": (3, 9), "alias": (0, 5), "correction": (1, 8), "discussion": (0, 6)},
}


@pytest.fixture(scope="module")
def cases():
    return json.loads(CASES.read_text())


def test_case_file_is_a_synthetic_candidate_set(cases):
    assert cases["status"] == "candidate" and cases["synthetic"] and not cases["trusted_root"]
    ids = [item["id"] for item in cases["items"]]
    assert len(ids) == len(set(ids)) == 522
    assert {item["split"] for item in cases["items"]} == set(MEASURED)
    assert all(item["group"] in {"remember", "alias", "correction", "discussion"}
               and type(item["label"]) is bool and item["text"].strip()
               for item in cases["items"])


def test_measured_errors_do_not_grow(cases):
    result = report(cases)
    assert result["triggers_version"] == triggers.VERSION
    assert result["provider_calls"] == 0 and result["database_operations"] == 0
    for split, groups in MEASURED.items():
        for group, (false_admit, missed) in groups.items():
            current = result["splits"][split][group]["v2"]
            assert current["false_admit"] <= false_admit, (split, group, current)
            assert current["missed"] <= missed, (split, group, current)


def test_narrowed_list_drops_ordinary_statements_and_covers_d476():
    assert {"我一般", "我习惯"} <= set(V1_NOTE_INTENT)
    for ordinary in ("我一般用表格看周报", "我习惯先看含税价"):
        assert not triggers.remember(ordinary, ordinary)
    message = "这周的周报整理一下，以后给我表格形式的周报"
    assert triggers.remember(message, "以后给我表格形式的周报")
    # The expression must lie inside the quoted part, not merely somewhere in the message.
    assert not triggers.remember(message, "这周的周报整理一下")
