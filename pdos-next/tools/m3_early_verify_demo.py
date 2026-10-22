"""Read actual browser-produced G0 results only from M3's labelled synthetic fixture."""

import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import m3_early_environment as fixture


def verify():
    state = fixture.state()
    demo = state["demo"]
    base = f"http://127.0.0.1:{demo['api_port']}/v1/categories/{demo['category_id']}"

    def get(path, actor="reviewer"):
        request = Request(
            base + path, headers={"Authorization": f"Bearer {demo[actor + '_token']}"}
        )
        with urlopen(request, timeout=10) as response:
            return json.load(response)

    submitted = get(f"/proposals/{demo['draft_id']}", "owner")
    approved = get(f"/proposals/{demo['review_id']}")
    assert submitted["status"] == "in_review"
    assert submitted["items"][0]["version"] == 2
    assert approved["status"] == "approved"
    decision = approved["decision"]
    definition = get(f"/g0-definitions/{decision['definition_id']}")
    assert definition["sealed"] and definition["revision"] == 1
    specs = {spec["key"]: spec for spec in definition["specs"]}
    assert specs["noise"]["item_status"] == "unknown"
    assert specs["noise"]["value"] is None and specs["noise"]["unit"] is None
    assert specs["display"]["text_value"] == "true"
    assert specs["display"]["item_status"] == "confirmed"
    open_items = get(f"/projects/{decision['project_id']}/open-items")["items"]
    assert len(open_items) == 2 and {item["kind"] for item in open_items} == {"task", "risk"}
    assert all(item["owner_id"] == demo["expert_id"] for item in open_items)
    assert all(item["due_date"] == "2026-10-25" for item in open_items)
    assert any(
        item["kind"] == "question" and item["content"]["status"] == "carried"
        for item in approved["items"]
    )
    bff = f"http://127.0.0.1:{demo['owner_web_port']}/api/v1/categories/{demo['category_id']}"
    rejected = []
    for path, method, expected in (
        (f"/proposals/{demo['draft_id']}", "POST", 405),
        ("/proposals?page_size=0", "GET", 422),
        ("/proposals?include_history=unexpected", "GET", 422),
    ):
        request = Request(
            bff + path,
            method=method,
            headers={"Cookie": f"pdos-next-session={demo['owner_token']}"},
        )
        try:
            with urlopen(request, timeout=10) as response:
                status = response.status
        except HTTPError as error:
            status = error.code
        assert status == expected, (path, status)
        rejected.append({"path": path, "method": method, "status": status})
    result = {
        "synthetic_only": True,
        "owner_ui_submit_and_edit": True,
        "read_only_product_manager_ui_approval": True,
        "native_definition_v1_sealed": True,
        "unknown_value_and_unit_remain_null": True,
        "boolean_and_confirmed_state_preserved": True,
        "project_task_and_risk_assigned_to_outside_expert": True,
        "question_carried": True,
        "result_ids": {key: decision[key] for key in ("product_id", "definition_id", "project_id")},
        "bff_rejections": rejected,
    }
    (fixture.REPORT / "actual-browser-results.json").write_text(json.dumps(result, indent=2) + "\n")
    print("Actual UI-generated G0 results and three BFF boundaries verified on M3 fixture")


if __name__ == "__main__":
    verify()
