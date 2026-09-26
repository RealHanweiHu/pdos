import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ProjectAiChat } from "./project-ai-chat";

function jsonResponse(body: object, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("ProjectAiChat", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    fetchMock.mockReset();
    sessionStorage.clear();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  const emptyRuns = { items: [], pending_review_findings: 0 };

  function withRunsRoute(chatResponses: Response[]) {
    const queue = [...chatResponses];
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path.endsWith("/runs")) return jsonResponse(emptyRuns);
      const next = queue.shift();
      if (!next) throw new Error(`unexpected request: ${path}`);
      return next;
    });
  }

  it("renders only server-mapped citations for an answered question", async () => {
    const user = userEvent.setup();
    withRunsRoute([jsonResponse({
      status: "answered",
      answer: "当前有一个高暴露风险。",
      error_code: null,
      citations: [{
        reference_id: "risk:risk-1",
        entity: "risk",
        entity_id: "risk-1",
        label: "电机交付风险",
        href: "/projects?project=project-1&tab=risks&risk_id=risk-1",
        excerpt: "likelihood=4 · impact=5",
      }],
    })]);
    render(<ProjectAiChat projectId="project-1" />);
    await user.type(screen.getByLabelText("向项目 AI 提问"), "当前风险是什么？");
    await user.click(screen.getByRole("button", { name: "提问" }));

    expect(await screen.findByText("当前有一个高暴露风险。")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "跳转证据" })).toHaveAttribute(
      "href",
      "/projects?project=project-1&tab=risks&risk_id=risk-1",
    );
  });

  it("treats insufficient evidence and model removal as visible product states", async () => {
    const user = userEvent.setup();
    withRunsRoute([
      jsonResponse({ status: "insufficient_evidence", answer: null, citations: [], error_code: null }),
      jsonResponse({ status: "unavailable", answer: null, citations: [], error_code: "MODEL_UNAVAILABLE" }),
    ]);
    render(<ProjectAiChat projectId="project-1" />);
    const input = screen.getByLabelText("向项目 AI 提问");
    await user.type(input, "没有证据的问题");
    await user.click(screen.getByRole("button", { name: "提问" }));
    expect(await screen.findByText("知识库无此依据")).toBeInTheDocument();
    await user.clear(input);
    await user.type(input, "再次提问");
    await user.click(screen.getByRole("button", { name: "提问" }));
    expect(await screen.findByText("AI 暂停")).toBeInTheDocument();
  });

  it("shows recent agent runs with pending finding count and honest empty state", async () => {
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path.endsWith("/runs")) {
        return jsonResponse({
          items: [
            {
              id: "run-1",
              agent_key: "project_intelligence",
              status: "running",
              window_started_at: "2026-08-25T10:00:00Z",
              window_ended_at: "2026-08-25T10:05:00Z",
              event_count: 3,
              started_at: "2026-08-25T10:05:01Z",
              completed_at: null,
              error_code: null,
              created_at: "2026-08-25T10:05:00Z",
            },
          ],
          pending_review_findings: 2,
        });
      }
      throw new Error(`unexpected request: ${path}`);
    });
    render(<ProjectAiChat projectId="project-1" />);

    expect(await screen.findByText("运行中")).toBeInTheDocument();
    expect(screen.getByText("3 事件")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /本项目待审 Finding 2/ })).toHaveAttribute(
      "href",
      "/ai-review",
    );
  });

  it("reuses the same request after a lost response and creates a new id after completion", async () => {
    const user = userEvent.setup();
    const requests: { request_id: string; question: string }[] = [];
    fetchMock.mockImplementation(async (input, init) => {
      if (String(input).endsWith("/runs")) return jsonResponse(emptyRuns);
      requests.push(JSON.parse(String(init?.body)));
      if (requests.length === 1) throw new Error("Response lost");
      return jsonResponse({ status: "insufficient_evidence", answer: null, citations: [], error_code: null });
    });
    render(<ProjectAiChat projectId="project-1" />);
    await user.type(screen.getByLabelText("向项目 AI 提问"), "当前状态");
    await user.click(screen.getByRole("button", { name: "提问" }));
    expect(await screen.findByText("Response lost")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "提问" }));
    expect(await screen.findByText("知识库无此依据")).toBeInTheDocument();
    expect(requests[1].request_id).toBe(requests[0].request_id);
    await user.click(screen.getByRole("button", { name: "提问" }));
    expect(await screen.findByText("知识库无此依据")).toBeInTheDocument();
    expect(requests[2].request_id).not.toBe(requests[0].request_id);
  });
  it("continues a queued request after the component remounts without resubmitting", async () => {
    const user = userEvent.setup();
    const operation = { run_id: "run-queued", project_id: "project-1", request_id: "request-1",
      status: "queued", result: null, error_code: null };
    let submitted = 0;
    let completed = false;
    fetchMock.mockImplementation(async (input, init) => {
      if (String(input).endsWith("/runs")) return jsonResponse(emptyRuns);
      if (init?.method === "POST") { submitted++; return jsonResponse(operation, 202); }
      return jsonResponse(completed ? { ...operation, status: "succeeded", result: {
        status: "answered", answer: "后台已完成查证。", citations: [], error_code: null,
      } } : operation);
    });
    const view = render(<ProjectAiChat projectId="project-1" />);
    await user.type(screen.getByLabelText("向项目 AI 提问"), "项目状态？");
    await user.click(screen.getByRole("button", { name: "提问" }));
    expect(await screen.findByText("请求已保存，等待处理")).toBeInTheDocument();
    expect(sessionStorage.getItem("pdos-chat-request:project-1")).toBe("run-queued");
    view.unmount();
    completed = true;
    render(<ProjectAiChat projectId="project-1" />);
    expect(await screen.findByText("后台已完成查证。")).toBeInTheDocument();
    expect(submitted).toBe(1);
    expect(sessionStorage.getItem("pdos-chat-request:project-1")).toBeNull();
  });

  it("cancels a queued request and allows a new question", async () => {
    const user = userEvent.setup();
    const operation = { run_id: "run-queued", project_id: "project-1", request_id: "request-1",
      status: "queued", result: null, error_code: null };
    fetchMock.mockImplementation(async (input) => {
      if (String(input).endsWith("/runs")) return jsonResponse(emptyRuns);
      if (String(input).endsWith("/cancel")) return jsonResponse({ ...operation, status: "cancelled" });
      return jsonResponse(operation);
    });
    render(<ProjectAiChat projectId="project-1" />);
    await user.type(screen.getByLabelText("向项目 AI 提问"), "项目状态？");
    await user.click(screen.getByRole("button", { name: "提问" }));
    await user.click(await screen.findByRole("button", { name: "取消请求" }));
    expect(await screen.findByText("请求已取消，可以重新提问。")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "提问" })).toBeEnabled();
  });

  it("shows persistent questions and a review link for a run waiting on input", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ items: [{
      id: "waiting-run", agent_key: "quality_intelligence", status: "waiting_input",
      window_started_at: "2026-09-11T12:00:00Z", window_ended_at: "2026-09-11T12:00:01Z",
      event_count: 1, started_at: "2026-09-11T12:00:00Z", completed_at: null,
      error_code: null, created_at: "2026-09-11T12:00:00Z", input_wait: {
        id: "wait-1", finding_id: "finding-1", owner_user_id: "owner-1",
        questions: ["请确认本次测试的判定条件。"], summary: "测试要求尚缺判定条件",
        expires_at: "2026-09-11T12:10:00Z", resolved_at: null,
        resolution: null, continuation_run_id: null,
      },
    }], pending_review_findings: 1 }));
    render(<ProjectAiChat projectId="project-1" />);
    expect(await screen.findByText("等待补充")).toBeInTheDocument();
    expect(screen.getByText("请确认本次测试的判定条件。")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "查看问题与候选" })).toHaveAttribute("href", "/ai-review?finding=finding-1");
  });

});
