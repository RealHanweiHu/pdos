import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { AgentRunsCard } from "./agent-runs-card";

const fetchMock = vi.fn<typeof fetch>();
const run = {
  id: "run-1", agent_key: "ai_chat", status: "waiting_input", can_cancel: true,
  window_started_at: "2026-09-11T00:00:00Z", window_ended_at: "2026-09-11T00:00:00Z",
  event_count: 0, started_at: "2026-09-11T00:00:00Z", completed_at: null,
  error_code: null, created_at: "2026-09-11T00:00:00Z",
};
function response(body: object, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}
beforeEach(() => { fetchMock.mockReset(); vi.stubGlobal("fetch", fetchMock); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it.each([false, true])("cancels a visible request or event (event=%s) and refreshes status", async (event) => {
  let cancelled = false;
  fetchMock.mockImplementation(async (url, options) => {
    if (String(url).endsWith("/cancel")) {
      expect(options?.method).toBe("POST"); cancelled = true;
      return response({ changed: true });
    }
    return response({ pending_review_findings: 1, items: [{ ...run,
      agent_key: event ? "project_intelligence" : run.agent_key,
      event_count: event ? 3 : 0,
      status: cancelled ? "cancelled" : event ? "queued" : run.status, can_cancel: !cancelled,
      error_code: cancelled ? event ? "EVENT_RUN_CANCELLED" : "APPLICATION_REQUEST_CANCELLED" : null,
    }] });
  });
  render(<AgentRunsCard projectId="project-1" />);
  await userEvent.setup().click(await screen.findByRole("button", { name: "取消任务" }));
  expect(await screen.findByText("已取消")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "取消任务" })).not.toBeInTheDocument();
  expect(screen.getByText("本项目待审 Finding 1")).toBeInTheDocument();
});

it("keeps the task available after a failed cancellation", async () => {
  fetchMock.mockImplementation(async (url) => String(url).endsWith("/cancel")
    ? response({ detail: { code: "APPLICATION_CONTROL_ACCESS_DENIED" } }, 403)
    : response({ pending_review_findings: 0, items: [run] }));
  render(<AgentRunsCard projectId="project-1" />);
  await userEvent.setup().click(await screen.findByRole("button", { name: "取消任务" }));
  expect(await screen.findByRole("alert")).toBeInTheDocument();
  expect(screen.getByText("等待补充")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "取消任务" })).toBeEnabled();
});
