import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AiWriteTrialRegistration } from "./ai-write-trial-registration";

const base = "/api/ai/governance/write-policy/trials";
const binding = { operation_key: "meeting.minutes.draft", provider: "fixture-provider", model: "fixture-model", model_version: "fixture-revision", release_bundle_version: `sha256:${"a".repeat(64)}`, suite_version: "suite.v1", suite_digest: "b".repeat(64), adapter_version: "adapter.v1", policy_version: "policy.v1", policy_revision: 2 };
const key = "c".repeat(64);
const prepared = { as_of: "2026-09-27T00:00:00Z", candidates: [{ key, label: "会议纪要 · 已核实评测", binding, evaluation_id: "evaluation", published_at: "2026-09-20T00:00:00Z", expires_at: "3000-01-01T00:00:00Z" }], projects: [{ id: "project-1", code: "P1", name: "样机验证" }], policy_revision: 2, blockers: [] };
function fill(start = "2999-01-01T10:00", end = "2999-01-01T11:00") {
  fireEvent.change(screen.getByLabelText("独立评测候选"), { target: { value: key } });
  fireEvent.click(screen.getByRole("checkbox", { name: /样机验证/ }));
  for (const [label, value] of [
    ["观察开始时间", start], ["观察结束时间", end], ["最小办理数（份）", "20"],
    ["后续观察时长（小时）", "1.5"], ["抽检比例（%）", "12.5"], ["确认口径", "retained_original"],
    ["恢复政策版本名称", "recovery.v1"], ["恢复条件", "完成新评测与独立复核后再裁决"], ["登记说明", "固定样机项目的观察口径"],
  ]) fireEvent.change(screen.getByLabelText(label, { exact: label !== "恢复政策版本名称" }), { target: { value } });
}
function submit() { fireEvent.click(screen.getByRole("button", { name: "登记本次试运行" })); }
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("trial registration", () => {
  it("keeps candidates, projects and numeric choices empty and posts the selected trusted binding", async () => {
    const onRegistered = vi.fn();
    const fetcher = vi.fn<typeof fetch>().mockImplementation(async (_url, init) => Response.json(init?.method === "POST" ? { protocol: { id: "registered" }, replayed: false } : prepared));
    vi.stubGlobal("fetch", fetcher);
    render(<AiWriteTrialRegistration onRegistered={onRegistered} />);
    await screen.findByLabelText("独立评测候选");
    expect(screen.getByLabelText("独立评测候选")).toHaveValue("");
    expect(screen.getByRole("checkbox")).not.toBeChecked();
    expect(screen.getByLabelText("观察场景")).toHaveValue("real_business");
    expect(screen.getByLabelText("最小办理数（份）")).toHaveValue(null);
    expect(screen.getByLabelText("后续观察时长（小时）")).toHaveValue(null);
    expect(screen.getByLabelText("抽检比例（%）")).toHaveValue(null);
    fill(); submit();
    expect(await screen.findByText(/试运行已登记/)).toBeVisible();
    const post = fetcher.mock.calls.find(([, init]) => init?.method === "POST");
    expect(post?.[0]).toBe(base);
    const payload = JSON.parse(String(post?.[1]?.body));
    expect(payload.binding).toEqual(binding);
    expect(payload.preparation_digest).toBe(key);
    expect(payload.project_ids).toEqual(["project-1"]);
    expect(payload.window_start).toBe(new Date("2999-01-01T10:00").toISOString());
    expect(payload.configuration).toEqual({ minimum_handled_drafts: 20, cohort_window_seconds: 3600, minimum_followup_seconds: 5400, sampling_basis_points: 1250, confirmation_basis: "retained_original", recovery_protocol_version: "recovery.v1", recovery_conditions: "完成新评测与独立复核后再裁决" });
    expect(screen.getByLabelText("最小办理数（份）")).toHaveValue(null);
    expect(onRegistered).toHaveBeenCalledTimes(1);
  });

  it("locks an uncertain submission and retries the exact request without duplicate registration", async () => {
    let posts = 0;
    const onRegistered = vi.fn();
    const onPendingChange = vi.fn();
    const fetcher = vi.fn<typeof fetch>().mockImplementation(async (_url, init) => {
      if (init?.method !== "POST") return Response.json(prepared);
      if (++posts === 1) throw new TypeError("network down");
      return Response.json({ protocol: { id: "original-registration" }, replayed: true });
    });
    vi.stubGlobal("fetch", fetcher);
    render(<AiWriteTrialRegistration onRegistered={onRegistered} onPendingChange={onPendingChange} />);
    await screen.findByLabelText("独立评测候选"); fill(); submit();
    expect(await screen.findByRole("alert")).toHaveTextContent("已锁定本次内容");
    expect(screen.getByLabelText("登记说明")).toBeDisabled();
    expect(screen.getByRole("button", { name: "刷新登记资料" })).toBeDisabled();
    expect(onPendingChange).toHaveBeenLastCalledWith(true);
    fireEvent.click(screen.getByRole("button", { name: "重试原登记请求" }));
    await screen.findByText(/试运行已登记/);
    const writes = fetcher.mock.calls.filter(([, init]) => init?.method === "POST");
    expect(writes).toHaveLength(2);
    expect(writes[0][1]?.body).toBe(writes[1][1]?.body);
    expect(onRegistered).toHaveBeenCalledTimes(1);
    expect(onPendingChange).toHaveBeenLastCalledWith(false);
    expect(screen.getByLabelText("登记说明")).toBeEnabled();
  });

  it("rejects retrospective real-business windows and unlocks known conflicts for review", async () => {
    const fetcher = vi.fn<typeof fetch>().mockImplementation(async (_url, init) => init?.method === "POST" ? Response.json({ detail: { code: "PREPARATION_CHANGED" } }, { status: 409 }) : Response.json(prepared));
    vi.stubGlobal("fetch", fetcher);
    render(<AiWriteTrialRegistration onRegistered={vi.fn()} />);
    await screen.findByLabelText("独立评测候选"); fill("2020-01-01T10:00", "2020-01-01T11:00"); submit();
    expect(await screen.findByRole("alert")).toHaveTextContent("选择未来的开始时间");
    expect(fetcher.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(0);
    fireEvent.change(screen.getByLabelText("观察开始时间"), { target: { value: "2999-01-01T10:00" } });
    fireEvent.change(screen.getByLabelText("观察结束时间"), { target: { value: "2999-01-01T11:00" } });
    submit();
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("政策、评测或开始时间已变化"));
    expect(screen.getByLabelText("登记说明")).toBeEnabled();
    expect(screen.getByRole("button", { name: "刷新登记资料" })).toBeEnabled();
  });

  it("explains missing candidates without raw codes or a disconnected create button", async () => {
    vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockResolvedValue(Response.json({ ...prepared, candidates: [], blockers: ["no_trusted_evaluations", "unknown_internal_reason"] })));
    render(<AiWriteTrialRegistration onRegistered={vi.fn()} />);
    expect(await screen.findByText(/尚无可登记的独立评测候选/)).toBeVisible();
    expect(screen.getByText("· 尚无受信的独立评测发布记录")).toBeVisible();
    expect(screen.queryByRole("button", { name: "登记本次试运行" })).not.toBeInTheDocument();
    expect(screen.queryByText("unknown_internal_reason")).not.toBeInTheDocument();
  });
});
