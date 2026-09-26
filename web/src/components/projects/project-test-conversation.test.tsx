import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { ProjectTestConversation } from "./project-test-conversation";

const { findings } = vi.hoisted(() => ({ findings: vi.fn() }));
vi.mock("@/components/ai/ai-api", () => ({ requestFindings: findings }));

const candidate = {
  id: "finding", finding_type: "test_plan_change", status: "pending_review", accepted_payload: null,
  proposed_payload: { base_plan_id: "plan", base_digest: "a".repeat(64), summary: "待补条件", messages: ["新增功能"],
    base_items: [], changes: [], questions: ["请补充功能参数"] },
};

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("project test conversation", () => {
  beforeEach(() => { vi.clearAllMocks(); sessionStorage.clear(); findings.mockResolvedValue([]); });
  it("restores saved questions and sends follow-up against the correct finding", async () => {
    findings.mockResolvedValue([candidate]);
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: "created", finding_id: "finding" })));
    vi.stubGlobal("fetch", fetcher);
    render(<ProjectTestConversation projectId="project" planId="plan" />);
    fireEvent.click(screen.getByRole("button", { name: "用 AI 调整测试项" }));
    expect(await screen.findByText("请补充功能参数")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("描述新增功能、客户要求或补充条件"), { target: { value: "用户补充参数" } });
    fireEvent.click(screen.getByRole("button", { name: "生成调整建议" }));
    await waitFor(() => expect(fetcher).toHaveBeenCalledOnce());
    expect(fetcher.mock.calls[0][0]).toBe("/api/projects/project/npi/test-plans/plan/suggestions");
    expect(JSON.parse(fetcher.mock.calls[0][1].body)).toMatchObject({ message: "用户补充参数", previous_finding_id: "finding" });
    expect(screen.getByRole("link", { name: "前往 AI Review 审阅与应用" })).toHaveAttribute("href", "/ai-review?finding=finding");
  });
  it("keeps the draft and typed text when the model is unavailable", async () => {
    findings.mockResolvedValue([candidate]);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: "unavailable", finding_id: null }))));
    render(<ProjectTestConversation projectId="project" planId="plan" />);
    fireEvent.click(screen.getByRole("button", { name: "用 AI 调整测试项" }));
    await screen.findByText("请补充功能参数");
    fireEvent.change(screen.getByLabelText("描述新增功能、客户要求或补充条件"), { target: { value: "继续补充" } });
    fireEvent.click(screen.getByRole("button", { name: "生成调整建议" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("AI 暂不可用");
    expect(screen.getByLabelText("描述新增功能、客户要求或补充条件")).toHaveValue("继续补充");
    expect(screen.getByText("请补充功能参数")).toBeInTheDocument();
  });
  it("follows the queued operation and loads its saved questions", async () => {
    findings.mockResolvedValue([candidate]);
    const run = "00000000-0000-4000-8000-000000000001";
    const fetcher = vi.fn().mockImplementation(async (_url, init) => new Response(JSON.stringify(
      init?.method === "POST" ? { status: "queued", run_id: run, finding_id: null }
        : { status: "waiting_input", run_id: run, finding_id: "finding" }
    ), { status: init?.method === "POST" ? 202 : 200 }));
    vi.stubGlobal("fetch", fetcher);
    render(<ProjectTestConversation projectId="project" planId="plan" />);
    fireEvent.click(screen.getByRole("button", { name: "用 AI 调整测试项" }));
    await screen.findByText("请补充功能参数");
    fireEvent.change(screen.getByLabelText("描述新增功能、客户要求或补充条件"), { target: { value: "新要求" } });
    fireEvent.click(screen.getByRole("button", { name: "生成调整建议" }));
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.getByLabelText("描述新增功能、客户要求或补充条件")).toHaveValue(""));
    expect(fetcher.mock.calls[1][0]).toContain(`/suggestion-requests/${run}`);
    expect(sessionStorage.getItem("pdos:test-plan-run:project:plan")).toBeNull();
    expect(screen.getByRole("link", { name: "前往 AI Review 审阅与应用" })).toBeInTheDocument();
  });
  it("restores a pending operation and can cancel it without resubmitting", async () => {
    const run = "00000000-0000-4000-8000-000000000002";
    sessionStorage.setItem("pdos:test-plan-run:project:plan", run);
    let cancelled = false;
    const fetcher = vi.fn().mockImplementation(async (url) => {
      if (String(url).endsWith("/cancel")) { cancelled = true; return new Response("{}"); }
      return new Response(JSON.stringify({ run_id: run, status: cancelled ? "cancelled" : "queued", finding_id: null }));
    });
    vi.stubGlobal("fetch", fetcher);
    render(<ProjectTestConversation projectId="project" planId="plan" />);
    await waitFor(() => expect(fetcher).toHaveBeenCalledOnce());
    fireEvent.click(screen.getByRole("button", { name: "取消任务" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("任务已取消");
    expect(fetcher.mock.calls.every(([url]) => !String(url).endsWith("/suggestions"))).toBe(true);
    expect(sessionStorage.getItem("pdos:test-plan-run:project:plan")).toBeNull();
  });

});
