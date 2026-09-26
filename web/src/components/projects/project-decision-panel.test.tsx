import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ProjectDecisionPanel } from "./project-decision-panel";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

const projectId = "dddddddd-dddd-4ddd-8ddd-dddddddddddd";
const approverId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const options = { members: [{ id: approverId, display_name: "项目批准人" }], tasks: [], gates: [] };
const receipt = { audit_id: 42, label: "任务完成", kind: "task", target_id: "task-1", executed_at: "2026-09-02T00:00:00Z" };
const decisionId = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee";

const decision = {
  id: decisionId,
  decision_kind: "technical_choice",
  title: "选用铝合金泵体",
  outcome: "EVT 起改用 6061 铝合金",
  context: null,
  options: [],
  trade_offs: null,
  rationale: "重量下降 12%",
  consequence: null,
  follow_up_state: "pending",
  follow_up_note: null,
  decided_at: "2026-09-01T00:00:00Z",
};

describe("ProjectDecisionPanel", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    vi.clearAllMocks();
    window.history.replaceState({}, "", "/projects");
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(cleanup);

  it("shows the decision log with its rationale and follow-up state", async () => {
    fetchMock.mockImplementation(async (input) => Response.json(String(input).endsWith("/options") ? options : String(input).endsWith("/execution-evidence") ? { items: [receipt] } : { items: [decision] }));

    render(<ProjectDecisionPanel canEdit projectId={projectId} />);

    expect(await screen.findByText("选用铝合金泵体")).toBeTruthy();
    expect(screen.getByText("EVT 起改用 6061 铝合金")).toBeTruthy();
    expect(screen.getByText(/重量下降 12%/)).toBeTruthy();
    expect(screen.getByText(/待跟进/)).toBeTruthy();
  });

  it("records a decision with only the fields the server accepts", async () => {
    fetchMock.mockImplementation(async (input) => Response.json(String(input).endsWith("/options") ? options : { items: [] }));
    render(<ProjectDecisionPanel canEdit projectId={projectId} />);
    await screen.findByText("尚无决策记录。");

    fireEvent.change(screen.getByLabelText("决策标题"), {
      target: { value: "选用铝合金泵体" },
    });
    fireEvent.change(screen.getByLabelText("决策结论"), {
      target: { value: "EVT 起改用 6061" },
    });
    for (const [label, value] of [["背景", "客户要求减重"], ["考虑的选项（每行一项）", "6061\n原材料"], ["方案权衡", "重量与成本"], ["选择理由", "满足减重目标"], ["后果与影响", "更新加工方案"], ["依据与证据引用（每行一条）", "EVT试验记录"]]) {
      fireEvent.change(screen.getByLabelText(label), { target: { value } });
    }
    fireEvent.change(screen.getByLabelText("批准人"), { target: { value: approverId } });
    fireEvent.click(screen.getByRole("button", { name: "记录决策" }));

    await waitFor(() => {
      const write = fetchMock.mock.calls.find((call) => call[1]?.method === "POST");
      expect(String(write?.[0])).toBe(`/api/projects/${projectId}/decisions`);
      expect(JSON.parse(String(write?.[1]?.body))).toEqual({
        decision_kind: "technical_choice",
        title: "选用铝合金泵体",
        outcome: "EVT 起改用 6061",
        context: "客户要求减重", options: ["6061", "原材料"], trade_offs: "重量与成本",
        rationale: "满足减重目标", consequence: "更新加工方案", evidence_refs: ["EVT试验记录"],
        owner_user_id: null, approver_user_id: approverId, follow_up_pending: false,
        follow_up_note: null, follow_up_task_id: null, gate_id: null,
      });
    });
  });

  it("posts a follow-up note against the right decision", async () => {
    fetchMock.mockImplementation(async (input) => Response.json(String(input).endsWith("/options") ? options : String(input).endsWith("/execution-evidence") ? { items: [receipt] } : { items: [decision] }));
    render(<ProjectDecisionPanel canEdit projectId={projectId} />);
    await screen.findByText("选用铝合金泵体");

    fireEvent.change(screen.getByLabelText("选用铝合金泵体 跟进说明"), {
      target: { value: "已复测通过" },
    });
    expect(screen.getByRole("button", { name: "确认执行完成" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "查找执行凭据" }));
    const choice = await screen.findByLabelText("选用铝合金泵体 执行凭据");
    fireEvent.change(choice, { target: { value: "42" } });
    await waitFor(() => expect(screen.getByRole("button", { name: "确认执行完成" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "确认执行完成" }));

    await waitFor(() => {
      const write = fetchMock.mock.calls.find((call) =>
        String(call[0]).includes("/follow-up"),
      );
      expect(String(write?.[0])).toBe(
        `/api/projects/${projectId}/decisions/${decisionId}/follow-up`,
      );
      expect(JSON.parse(String(write?.[1]?.body))).toEqual({ note: "已复测通过", execution_audit_id: 42 });
    });
  });

  it("a read-only role sees the log but cannot record anything", async () => {
    fetchMock.mockImplementation(async (input) => Response.json(String(input).endsWith("/options") ? options : String(input).endsWith("/execution-evidence") ? { items: [receipt] } : { items: [decision] }));

    render(<ProjectDecisionPanel canEdit={false} projectId={projectId} />);
    await screen.findByText("选用铝合金泵体");

    expect(screen.queryByRole("button", { name: "记录决策" })).toBeNull();
    expect(screen.queryByRole("button", { name: "确认执行完成" })).toBeNull();
  });

  it("surfaces a backend refusal rather than showing an empty log", async () => {
    fetchMock.mockImplementation(async () =>
      Response.json(
        { detail: { code: "PROJECT_ACCESS_DENIED", message: "Project access denied" } },
        { status: 403 },
      ),
    );

    render(<ProjectDecisionPanel canEdit projectId={projectId} />);

    expect(await screen.findByText("Project access denied")).toBeTruthy();
    // An access failure must never be rendered as "no decisions".
    expect(screen.queryByText("尚无决策记录。")).toBeNull();
  });
});
