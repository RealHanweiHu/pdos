import pytest

from pdos_next.agent_kernel.verification import fill_counts
from pdos_next.errors import DomainError


def test_model_counts_are_replaced_and_repeated_rows_do_not_inflate_sample():
    rows = [
        {"row_id": "a", "model": "Pump A", "channel": "retail", "status": "ok"},
        {"row_id": "b", "model": "Pump B", "channel": "retail", "status": "partial"},
        {"row_id": "c", "model": "Pump B", "status": "ok"},
    ]
    output = {
        "status": "completed",
        "summary": "Synthetic",
        "result": {
            "sample_size": 999,
            "clusters": [
                {"cluster_id": "seal", "sample_size": 800, "share_percent": 90},
                {"cluster_id": "noise", "sample_size": 999},
            ],
            "assignments": [
                {"item_id": "a", "cluster_id": "seal"},
                {"item_id": "b", "cluster_id": "noise"},
            ],
            "excluded": [{"item_id": "c", "reason": "duplicate"}],
        },
    }
    checked = fill_counts(output, [{"rows": rows}, {"rows": [rows[0]]}])["result"]
    assert checked["sample_size"] == 2 and checked["excluded_count"] == 1
    assert (
        checked["clusters"][0]["sample_size"] == 1
        and checked["clusters"][0]["share_percent"] == "50"
    )
    assert checked["clusters"][0]["distributions"]["model"] == {"Pump A": 1}
    assert output["result"]["sample_size"] == 999


@pytest.mark.parametrize(
    "assignments",
    [
        [{"item_id": "missing", "cluster_id": "seal"}],
        [{"item_id": "a", "cluster_id": "seal"}, {"item_id": "a", "cluster_id": "seal"}],
        [{"item_id": "a", "cluster_id": "missing"}],
    ],
)
def test_invented_or_duplicate_assignments_cannot_be_counted(assignments):
    with pytest.raises(DomainError):
        fill_counts(
            {"result": {"clusters": [{"cluster_id": "seal"}], "assignments": assignments}},
            [{"rows": [{"row_id": "a"}]}],
        )


def test_candidate_model_rows_never_become_sample_facts():
    checked = fill_counts(
        {
            "result": {
                "clusters": [{"cluster_id": "a"}],
                "assignments": [{"item_id": "real", "cluster_id": "a"}],
            }
        },
        [
            {"tool": "research.fanout", "tier": "READ", "value": {"ledger": [{"row_id": "real"}]}},
            {"tool": "proposal.create", "tier": "T1", "value": {"rows": [{"row_id": "invented"}]}},
        ],
    )
    assert checked["result"]["sample_size"] == 1 and checked["result"]["unassigned_count"] == 0
