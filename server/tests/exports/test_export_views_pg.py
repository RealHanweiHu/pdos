"""BOM diff and test summary exports over the existing real command chains (D56)."""
# ruff: noqa: F811 -- imported fixtures register the existing command dependency tree.

from builds.test_configurations import (
    accepted,
    bom_payload,
    command,
    listed,
    revision_payload,
    source_definition,
)
from projects.test_project_first_plan import accepted as confirmed
from verification.results.fixtures import (  # noqa: F401
    accepted_work,
    capture,
    known_configuration,
    launch_work,
    operational_work,
    ready_work,
    results_work,
)
from verification.results.fixtures import command as result_command

from tests.exports.test_export_pg import audits, auth, book, checked_audit, data_rows, reader


def test_bom_diff_export_uses_get_bom_on_both_sides_and_private_bom_stays_private(setup):
    chain = source_definition(setup)
    first, _, _ = accepted(
        setup,
        command(setup, "engineering.bom.revise", bom_payload(chain["reference"]), chain["reads"]),
    )
    old = next(b for b in listed(setup)["boms"] if b["id"] == first["subject_id"])
    second, _, _ = accepted(
        setup,
        command(
            setup,
            "engineering.bom.revise",
            revision_payload(old, chain["reference"], quantity="3"),
            chain["reads"],
        ),
    )
    root = f"/v1/categories/{setup.category}/products/{setup.product}/exports/bom-diff"
    response = setup.client.get(
        root, params={"bom_id": second["subject_id"]}, headers=setup.headers
    )
    workbook = book(response)
    assert workbook.sheetnames == ["说明", "BOM 差异", "修订信息"]
    [row] = data_rows(workbook["BOM 差异"])
    header = [c.value for c in workbook["BOM 差异"][1]]
    values = dict(zip(header, row, strict=True))
    assert values["来源"] == "人工" and values["变化"] == "修改" and values["行号"] == "housing"
    assert values["上一版用量"] is None and values["本版用量"] == "3"
    assert "用量" in values["变化字段"] and "损耗率" in values["变化字段"]
    revisions = data_rows(workbook["修订信息"])
    assert [r[1] for r in revisions] == ["上一版", "本版"] and [r[3] for r in revisions] == [1, 2]
    checked_audit(setup, response, actor=setup.human, view="bom_diff", rows=3)

    first_export = setup.client.get(
        root, params={"bom_id": first["subject_id"]}, headers=setup.headers
    )
    [added] = data_rows(book(first_export)["BOM 差异"])
    assert added[2] == "新增"

    # Private BOM: the configurations page does not list it for a read-only member,
    # and the export refuses with the page's own error; no audit row is added.
    member = reader(setup)
    page = setup.client.get(
        f"/v1/categories/{setup.category}/products/{setup.product}/configurations",
        headers=auth(setup, member),
    )
    assert page.status_code == 200 and page.json()["boms"] == []
    before = len(audits(setup))
    refused = setup.client.get(
        root, params={"bom_id": second["subject_id"]}, headers=auth(setup, member)
    )
    assert refused.status_code == 403, refused.text
    assert refused.json()["code"] == "FORBIDDEN_SCOPE" and len(audits(setup)) == before


def test_test_summary_export_matches_current_runs_and_measurements(results_work):
    work = results_work
    setup = work.setup
    first, _ = capture(work, (0,))
    confirmed(work.quality, result_command(work, "test.results.import", captured=first))
    second, _ = capture(work, (1,))
    confirmed(
        work.quality, result_command(work, "test.results.import", captured=second, final=True)
    )
    root = f"/v1/categories/{setup.category}/products/{setup.product}"
    page = setup.client.get(
        root + "/verification-results", params={"build_id": work.build_id}, headers=setup.headers
    )
    assert page.status_code == 200, page.text
    current = [r for r in page.json()["runs"] if r["is_current"]]
    measured = sum(len(r["run_snapshot"]["measurements"]) for r in current)
    response = setup.client.get(
        root + "/exports/test-summary", params={"build_id": work.build_id}, headers=setup.headers
    )
    workbook = book(response)
    runs, values = data_rows(workbook["测试运行"]), data_rows(workbook["测量值"])
    assert len(runs) == len(current) == 1 and len(values) == measured == 2
    header = [c.value for c in workbook["测试运行"][1]]
    run = dict(zip(header, runs[0], strict=True))
    assert run["来源"] == "人工" and run["运行编号"] == str(work.binding.run_id)
    assert run["已测"] == 2 and run["缺测"] == run["覆盖组合"] - 2
    assert {r[5] for r in values} == {"10.0000"} and {r[6] for r in values} == {"mm"}
    checked_audit(setup, response, actor=setup.human, view="test_summary", rows=3)
    other = setup.client.get(
        root + "/exports/test-summary",
        params={"build_id": work.build_id},
        headers=auth(setup, setup.other_human),
    )
    assert other.status_code in {401, 403, 404}
