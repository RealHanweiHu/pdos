"""Extend the real pre-project journey with immutable scoring and replay."""

from copy import deepcopy
from decimal import Decimal
from typing import Any, Protocol
from uuid import uuid4


class Post(Protocol):
    def __call__(self, path: str, body: dict[str, Any], status: int = 200) -> dict[str, Any]: ...


class Create(Protocol):
    def __call__(self, path: str, **body: Any) -> dict[str, Any]: ...


def verify_scoring_journey(
    post: Post,
    create: Create,
    product: dict[str, Any],
    market: dict[str, Any],
    strategy: dict[str, Any],
    content: dict[str, Any],
    owner: str,
    ref: dict[str, Any],
) -> None:
    from tests.test_product_manager_loop_api import command

    other = create(
        "/products",
        code="PUMP-OTHER",
        name="合成比较型号",
        level="model",
        parent_id=product["parent_id"],
        owner_user_id=owner,
    )
    other_content = deepcopy(content)
    other_content["included_features"] = ["lighting"]
    other_content["excluded_features"] = ["inflate"]
    definition = create(
        "/definitions", product_id=other["id"], strategy_id=strategy["id"], content=other_content
    )
    definition = post(
        f"/definitions/{definition['id']}/actions",
        {**command(definition), "action": "submit", "reason": "合成比较"},
    )
    for discipline in ["id", "md", "ee", "fw", "dqe"]:
        definition = post(
            f"/definitions/{definition['id']}/reviews",
            {
                **command(definition),
                "discipline": discipline,
                "review_round": definition["review_round"],
                "reviewed_source_digest": definition["review_digest"],
                "outcome": "approved",
                "reason": "合成专业核对",
                "sources": [ref],
            },
        )
    post(
        f"/definitions/{definition['id']}/actions",
        {
            **command(definition),
            "action": "publish",
            "reason": "合成比较发布",
            "reviewed_source_digest": definition["review_digest"],
        },
    )
    matrix = post("/product-matrix", {"product_line_id": product["product_line_id"]})
    choices = [
        dict(product_id=p["id"], release_id=p["release_id"])
        for p in matrix["items"]
        if p["id"] in [product["id"], other["id"]]
    ]
    assert len(choices) == 2
    prepared = post("/matrix-coverage-context", dict(segment_id=market["id"], choices=choices))
    calculation: dict[str, Any] = dict(
        segment_id=market["id"],
        choices=choices,
        expected_source_digest=prepared["source_digest"],
        criteria=[
            dict(
                key=key,
                source_locator="job_to_be_done",
                interpretation="合成所选需求",
                mode="feature",
                mappings=[dict(product_id=p["product_id"], item_key=key) for p in choices],
            )
            for key in ["inflate", "lighting"]
        ],
    )
    # Save a legacy v1 record first: optional scoring cannot invalidate historical replay.
    legacy = post("/matrix-coverage-calculation", calculation)
    old = post(
        "/matrix-record-save",
        dict(
            request_id=str(uuid4()),
            title="合成覆盖",
            reason="首版",
            calculation=calculation,
            expected_result_digest=legacy["result_digest"],
        ),
    )
    assert post("/matrix-record-replay", dict(record_id=old["id"]))["matches_saved"]
    policy: dict[str, Any] = dict(
        formula_version="product-coverage-weighted.v1",
        policy_key="test-policy",
        policy_version=1,
        title="合成覆盖政策",
        basis="显式合成口径，不是商业决策",
        weights=[
            dict(criterion_key="inflate", weight="0.7", basis="合成补气权重"),
            dict(criterion_key="lighting", weight="0.3", basis="合成照明权重"),
        ],
    )
    calculation["scoring_policy"] = policy
    result = post("/matrix-coverage-calculation", calculation)
    assert Decimal(result["scoring"]["selected_portfolio"]["score"]) == 100
    scores = {p["product_id"]: Decimal(p["score"]) for p in result["scoring"]["products"]}
    assert scores == {product["id"]: Decimal(70), other["id"]: Decimal(30)}
    body = dict(
        request_id=str(uuid4()),
        title="合成覆盖评分",
        reason="补显式权重",
        supersedes_id=old["id"],
        calculation=calculation,
        expected_result_digest=result["result_digest"],
    )
    saved = post("/matrix-record-save", body)
    assert post("/matrix-record-save", body)["id"] == saved["id"]
    assert saved["result"] == result and saved["version"] == 2
    assert (
        post("/matrix-record-read", dict(record_id=saved["id"]))["inputs"]["scoring_policy"]
        == policy
    )
    assert post("/matrix-record-replay", dict(record_id=saved["id"]))["matches_saved"]
    assert post("/matrix-record-refresh", dict(record_id=saved["id"]))["scoring_policy"] == policy
    policy["weights"][0]["weight"], policy["weights"][1]["weight"] = "0.2", "0.8"
    changed = post("/matrix-coverage-calculation", calculation)
    body = dict(
        request_id=str(uuid4()),
        title="合成新评分",
        reason="调权重",
        supersedes_id=saved["id"],
        calculation=calculation,
        expected_result_digest=changed["result_digest"],
    )
    post("/matrix-record-save", body, 409)  # cannot relabel changed policy as old version
    policy["policy_version"] = 2
    changed = post("/matrix-coverage-calculation", calculation)
    body["expected_result_digest"] = result["result_digest"]
    post("/matrix-record-save", body, 409)  # old result cannot be paired with new weights
    body["expected_result_digest"] = changed["result_digest"]
    latest = post("/matrix-record-save", body)
    assert latest["version"] == 3
    assert post("/matrix-record-replay", dict(record_id=latest["id"]))["matches_saved"]
    assert post("/matrix-record-replay", dict(record_id=old["id"]))["matches_saved"]
    assert post("/matrix-record-replay", dict(record_id=saved["id"]))["matches_saved"]
    post("/matrix-record-read", dict(record_id=str(uuid4())), 403)
    post("/matrix-coverage-calculation", {**calculation, "expected_source_digest": "0" * 64}, 409)
