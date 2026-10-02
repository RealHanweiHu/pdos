import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AiIssueTrialCurrent } from "./ai-issue-trial-current";
const protocol = "44444444-4444-4444-8444-444444444444", second = "55555555-5555-4555-8555-555555555555", base = `/api/projects/project/ai-issue-trials/${protocol}/current`;
function result(status = "meets_candidate_criteria") { return { status, criteria: { minimum_handled_runs: { actual: 12, required: 10, met: true }, followup_complete: true, confirmation: { numerator: 12, denominator: 12, basis_points: 10000, required: 9000, met: true }, withdrawal: { numerator: 0, denominator: 12, basis_points: 0, required: 500, met: true } }, reasons: [] }; }
function response() { return { version: "event-issue-trial-current-v1", checked_at: "2026-09-27T15:00:00Z", protocol_id: protocol, latest_collection_id: second, latest_collection_as_of: "2026-09-27T12:00:00Z", state: "current", original_result: result(), fresh_result: result(), reasons: [{ code: "provider_unverified", message: "本次未核验真实服务商调用证明" }], operational_requirements: [{ code: "sampling", message: "进入运行后按原登记比例持续抽检" }], qualification_granted: false, notice: "原采集保持不变，当前核对不授自动权限。" }; }
function expand() { fireEvent.click(screen.getByText("核对当前条件", { selector: "summary" })); }
function check() { fireEvent.click(screen.getByRole("button", { name: "核对当前条件" })); }
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
describe("Issue registered trial current checks", () => {
  it("checks only on explicit action and keeps operational sampling separate from qualification and per-request confirmation", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(Response.json(response())); vi.stubGlobal("fetch", fetcher); render(<AiIssueTrialCurrent projectId="project" protocolId={protocol} />);
    expect(fetcher).not.toHaveBeenCalled(); expand(); expect(fetcher).not.toHaveBeenCalled(); check();
    expect(await screen.findByText("当前核算条件满足")).toBeVisible(); expect(fetcher).toHaveBeenCalledWith(base, { method: "GET", cache: "no-store" });
    expect(within(screen.getByRole("region", { name: "原采集结果" })).getByText("100%")).toBeVisible(); expect(within(screen.getByRole("region", { name: "当前重算结果" })).getByText("100%")).toBeVisible();
    expect(within(screen.getByRole("region", { name: "当前核对说明" })).getByText("本次未核验真实服务商调用证明")).toBeVisible();
    const requirements = screen.getByRole("region", { name: "后续运行要求" }); expect(within(requirements).getByText("进入运行后按原登记比例持续抽检")).toBeVisible(); expect(within(requirements).getByText("抽检等要求用于后续运行，不作为逐次确认办理的前置条件。")).toBeVisible(); expect(screen.getByText(/数值条件满足不代表真实服务商调用已获证明/)).toBeVisible();
    expect(screen.queryByText(second)).not.toBeInTheDocument(); expect(screen.queryByRole("button", { name: /启用|登记|采集/ })).not.toBeInTheDocument();
  });
  it("shows original passing numbers beside a newly blocked result and explicitly preserves unavailable ratios", async () => {
    const fresh = result("does_not_meet_criteria"); fresh.criteria.confirmation = { numerator: 8, denominator: 12, basis_points: 6666, required: 9000, met: false };
    const body = { ...response(), state: "blocked", fresh_result: { ...fresh, reasons: [{ code: "changed", message: "原问题新增人工修改，当前比例低于原门槛" }], criteria: { ...fresh.criteria, withdrawal: { numerator: 0, denominator: 0, basis_points: null, required: 500, met: null } } } };
    vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockResolvedValue(Response.json(body))); render(<AiIssueTrialCurrent projectId="project" protocolId={protocol} />); expand(); check();
    expect(await screen.findByText("当前条件未满足")).toBeVisible(); expect(within(screen.getByRole("region", { name: "原采集结果" })).getByText("100%")).toBeVisible(); const latest = screen.getByRole("region", { name: "当前重算结果" }); expect(within(latest).getByText("66.66%")).toBeVisible(); expect(within(latest).getByText("—")).toBeVisible(); expect(within(latest).getByText("原问题新增人工修改，当前比例低于原门槛")).toBeVisible();
  });
  it("keeps missing evidence unavailable instead of inventing a passed current result", async () => {
    vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockResolvedValue(Response.json({ ...response(), state: "unavailable", latest_collection_id: null, latest_collection_as_of: null, original_result: null, fresh_result: null, reasons: [{ code: "collection_missing", message: "尚无原登记采集回执" }], operational_requirements: [] })));
    render(<AiIssueTrialCurrent projectId="project" protocolId={protocol} />); expand(); check(); expect(await screen.findByText("当前证据不足，暂无法核对")).toBeVisible(); expect(screen.getAllByText("暂无可核对结果，缺少的依据见下方说明。")).toHaveLength(2); expect(screen.getByText("尚无原登记采集回执")).toBeVisible(); expect(screen.queryByText("符合候选数值要求")).not.toBeInTheDocument();
  });
  it("ignores a prior protocol's response and rejects wrong-scope or granting receipts", async () => {
    let resolve!: (value: Response) => void;
    const fetcher = vi.fn<typeof fetch>().mockImplementationOnce(() => new Promise(done => { resolve = done; })).mockResolvedValueOnce(Response.json(response())).mockResolvedValueOnce(Response.json({ ...response(), protocol_id: second, qualification_granted: true })); vi.stubGlobal("fetch", fetcher);
    const view = render(<AiIssueTrialCurrent projectId="project" protocolId={protocol} />); expand(); check(); await waitFor(() => expect(resolve).toBeDefined()); view.rerender(<AiIssueTrialCurrent projectId="other" protocolId={second} />); expand(); expect(fetcher).toHaveBeenCalledTimes(1);
    await act(async () => resolve(Response.json(response()))); expect(screen.queryByText("当前核算条件满足")).not.toBeInTheDocument(); check(); expect(await screen.findByRole("alert")).toHaveTextContent("回执与原登记或资格口径不匹配"); expect(fetcher.mock.calls[1][0]).toBe(`/api/projects/other/ai-issue-trials/${second}/current`); check(); expect(await screen.findByRole("alert")).toHaveTextContent("回执与原登记或资格口径不匹配");
  });
  it("clears stale results on refresh and preserves server permission explanations", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(response())).mockResolvedValueOnce(Response.json({ detail: "当前项目权限已变化，不能核对" }, { status: 403 })); vi.stubGlobal("fetch", fetcher); render(<AiIssueTrialCurrent projectId="project" protocolId={protocol} />); expand(); check(); await screen.findByText("当前核算条件满足"); fireEvent.click(screen.getByRole("button", { name: "重新核对当前条件" })); expect(await screen.findByRole("alert")).toHaveTextContent("当前项目权限已变化，不能核对"); expect(screen.queryByRole("region", { name: "原采集结果" })).not.toBeInTheDocument(); expect(fetcher.mock.calls.every(call => call[1]?.method === "GET")).toBe(true);
  });
});
