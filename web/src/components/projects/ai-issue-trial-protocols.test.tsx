import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AiIssueTrialProtocols } from "./ai-issue-trial-protocols";
const id = "55555555-5555-4555-8555-555555555555", olderId = "66666666-6666-4666-8666-666666666666", key = "a".repeat(64), base = "/api/projects/project/ai-issue-trials";
const binding = { operation_key: "event.issue.create", model_version: "MODEL_VERSION_NOT_FOR_DISPLAY", evaluation_id: id, binding_digest: "PRIVATE_DIGEST" };
function candidate() { return { key, label: "问题建议独立评测 · 已通过版本甲", binding, evaluation_id: id, published_at: "2026-09-27T10:00:00Z", expires_at: "2100-01-01T00:00:00Z" }; }
function preparation(canRegister = true, candidates = [candidate()]) { return { can_register: canRegister, policy_revision: 4, candidates, blockers: candidates.length ? [] : ["no_trusted_evaluations"] }; }
function protocol(identity = id) { return { id: identity, created_at: "2026-09-27T12:00:00Z", actor_name: "登记负责人", window_start: "2099-10-01T00:00:00Z", window_end: "2099-10-02T00:00:00Z", evidence_kind: "real_business", binding, binding_label: "原评测版本甲（固定）", configuration: { minimum_handled_runs: 12, minimum_followup_seconds: 3600, sampling_basis_points: 1250, confirmation_basis: "retained_original", recovery_protocol_version: "review-v1", recovery_conditions: "复核问题来源和批准口径", minimum_confirmation_basis_points: 9200, maximum_retraction_basis_points: 400 }, reason: "固定本项目观察口径", notice: "此登记不授自动资格，不开放模型调用。" }; }
function history(items = [protocol()], next: string | null = null) { return { items, next_before_id: next }; }
function open() { fireEvent.click(screen.getByText("项目问题正式试运行登记")); }
function fill() {
  for (const [label, value] of [["独立问题评测版本", key], ["试运行开始", "2099-10-01T10:30"], ["试运行结束", "2099-10-02T10:30"], ["最小办理数（个原请求）", "12"], ["最短跟踪时长（秒）", "3600"], ["抽检比例（%）", "12.5"], ["确认口径", "retained_original"], ["恢复政策版本名称", "review-v1"], ["恢复条件", "复核问题来源和批准口径"], ["登记说明", "固定本项目观察口径"]]) fireEvent.change(screen.getByLabelText(label), { target: { value } });
}
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
describe("project Issue trial registration", () => {
  it("loads only on demand and keeps original version history readable when no candidate can be registered", async () => {
    const fetcher = vi.fn<typeof fetch>(async input => Response.json(String(input).endsWith("preparation") ? preparation(false, []) : String(input).endsWith(id) ? protocol() : history()));
    vi.stubGlobal("fetch", fetcher); render(<AiIssueTrialProtocols projectId="project" />);
    expect(fetcher).not.toHaveBeenCalled(); open();
    expect(await screen.findByText("尚无受信的独立问题评测发布记录")).toBeVisible();
    expect(screen.queryByRole("button", { name: "登记本次项目试运行" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "查看原登记" }));
    expect(await screen.findByRole("region", { name: "原试运行登记" })).toBeVisible();
    expect(screen.getByText("原评测版本甲（固定） · 真实业务")).toBeVisible();
    expect(screen.getByText("不低于 92%")).toBeVisible(); expect(screen.getByText("不高于 4%")).toBeVisible();
    expect(screen.queryByText(/PRIVATE_DIGEST|MODEL_VERSION_NOT_FOR_DISPLAY/)).not.toBeInTheDocument();
  });
  it("requires explicit numbers and submits only the chosen trusted binding with the exact configuration", async () => {
    let posted: Record<string, unknown> | undefined;
    const fetcher = vi.fn<typeof fetch>(async (input, init) => {
      if (init?.method === "POST") { posted = JSON.parse(String(init.body)); return Response.json({ protocol: { ...protocol(), ...posted, configuration: { ...protocol().configuration, ...(posted!.configuration as object) } }, replayed: false }); }
      return Response.json(String(input).endsWith("preparation") ? preparation() : history([]));
    });
    vi.stubGlobal("fetch", fetcher); render(<AiIssueTrialProtocols projectId="project" />); open();
    await screen.findByRole("button", { name: "登记本次项目试运行" });
    expect(screen.getByLabelText("最小办理数（个原请求）")).toHaveValue(null); expect(screen.getByLabelText("最短跟踪时长（秒）")).toHaveValue(null); expect(screen.getByLabelText("抽检比例（%）")).toHaveValue(null);
    expect(screen.getByLabelText("独立问题评测版本")).toHaveValue(""); fill(); fireEvent.click(screen.getByRole("button", { name: "登记本次项目试运行" }));
    expect(await screen.findByText("试运行已登记，原窗口与配置已固定。登记不会开放模型或自动写入。")).toBeVisible();
    expect(posted).toEqual({ request_id: expect.any(String), preparation_digest: key, binding, window_start: new Date("2099-10-01T10:30").toISOString(), window_end: new Date("2099-10-02T10:30").toISOString(), evidence_kind: "real_business", configuration: { minimum_handled_runs: 12, minimum_followup_seconds: 3600, sampling_basis_points: 1250, confirmation_basis: "retained_original", recovery_protocol_version: "review-v1", recovery_conditions: "复核问题来源和批准口径" }, reason: "固定本项目观察口径" });
    expect(screen.getByLabelText("独立问题评测版本")).toHaveValue(""); expect(screen.getByLabelText("最小办理数（个原请求）")).toHaveValue(null);
  });
  it("retries the original registration after an uncertain result without changing its binding or request id", async () => {
    const posts: string[] = [];
    const fetcher = vi.fn<typeof fetch>(async (input, init) => {
      if (init?.method === "POST") { posts.push(String(init.body)); if (posts.length === 1) throw new Error("连接中断"); const body = JSON.parse(posts[0]); return Response.json({ protocol: { ...protocol(), ...body, configuration: { ...protocol().configuration, ...body.configuration } }, replayed: true }); }
      return Response.json(String(input).endsWith("preparation") ? preparation() : history([]));
    });
    vi.stubGlobal("fetch", fetcher); render(<AiIssueTrialProtocols projectId="project" />); open(); await screen.findByRole("button", { name: "登记本次项目试运行" }); fill(); fireEvent.click(screen.getByRole("button", { name: "登记本次项目试运行" }));
    const retry = await screen.findByRole("button", { name: "重试原试运行登记" }); expect(screen.getByLabelText("登记说明")).toBeDisabled(); expect(screen.getByRole("button", { name: "刷新试运行登记资料" })).toBeDisabled();
    fireEvent.click(retry); expect(await screen.findByText("已核对原登记回执，没有重复登记。")).toBeVisible(); expect(posts).toHaveLength(2); expect(posts[0]).toBe(posts[1]);
  });
  it("rejects past real-business windows and requires fresh preparation after a version conflict", async () => {
    let posts = 0;
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input, init) => { if (init?.method === "POST") { posts += 1; return Response.json({ detail: { code: "PREPARATION_CHANGED", message: "独立评测或政策已有变化，请刷新登记资料" } }, { status: 409 }); } return Response.json(String(input).endsWith("preparation") ? preparation() : history([])); }));
    render(<AiIssueTrialProtocols projectId="project" />); open(); await screen.findByRole("button", { name: "登记本次项目试运行" }); fill();
    fireEvent.change(screen.getByLabelText("试运行开始"), { target: { value: "2020-10-01T10:30" } }); fireEvent.change(screen.getByLabelText("试运行结束"), { target: { value: "2020-10-02T10:30" } }); fireEvent.click(screen.getByRole("button", { name: "登记本次项目试运行" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("真实业务须提前登记"); expect(posts).toBe(0);
    fireEvent.change(screen.getByLabelText("观察场景"), { target: { value: "synthetic" } }); expect(screen.getByText("模拟或受控重放不能取得真实业务资格。")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "登记本次项目试运行" })); expect(await screen.findByRole("alert")).toHaveTextContent("独立评测或政策已有变化");
    expect(screen.queryByRole("button", { name: "登记本次项目试运行" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "刷新试运行登记资料" })); await screen.findByRole("button", { name: "登记本次项目试运行" }); expect(screen.getByLabelText("独立问题评测版本")).toHaveValue(""); expect(posts).toBe(1);
  });
  it("pages fixed registrations and ignores a prior project's late detail", async () => {
    let resolve!: (value: Response) => void;
    const fetcher = vi.fn<typeof fetch>(async input => {
      const url = String(input);
      if (url.endsWith("preparation")) return Response.json(preparation(false, []));
      if (url === `${base}/${id}`) return new Promise(done => { resolve = done; });
      return Response.json(url.includes("before_id") || url.includes("/other/") ? history([protocol(olderId)]) : history([protocol()], id));
    });
    vi.stubGlobal("fetch", fetcher); const view = render(<AiIssueTrialProtocols projectId="project" />); open();
    fireEvent.click(await screen.findByRole("button", { name: "更早的试运行登记" })); await waitFor(() => expect(screen.getAllByRole("button", { name: "查看原登记" })).toHaveLength(2));
    expect(fetcher.mock.calls.some(call => call[0] === `${base}?limit=20&before_id=${id}`)).toBe(true);
    fireEvent.click(screen.getAllByRole("button", { name: "查看原登记" })[0]); await waitFor(() => expect(resolve).toBeDefined());
    view.rerender(<AiIssueTrialProtocols projectId="other" />); open(); await screen.findByRole("button", { name: "查看原登记" });
    await act(async () => resolve(Response.json({ ...protocol(), actor_name: "旧项目人员" })));
    expect(screen.queryByRole("region", { name: "原试运行登记" })).not.toBeInTheDocument();
  });
});
