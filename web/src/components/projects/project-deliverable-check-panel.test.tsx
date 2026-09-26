import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ProjectDeliverableCheckPanel } from "./project-deliverable-check-panel";

const projectId = "eeeeeeee-1111-4222-8333-444444444444";
const itemId = "ffffffff-5555-4666-8777-888888888888";

function item(overrides: Record<string, unknown> = {}) {
  return {
    id: itemId,
    phase_code: "evt",
    phase_name: "EVT",
    task_name: "密封测试",
    deliverable_name: "EVT 测试报告",
    requirement: "required",
    is_gate: false,
    status: "pending",
    evidence_reference: null,
    completion_note: null,
    ...overrides,
  };
}

describe("ProjectDeliverableCheckPanel", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(cleanup);

  it("summarises how many items block a gate", async () => {
    fetchMock.mockImplementation(async () =>
      Response.json({ items: [item(), item({ id: "x", is_gate: true })] }),
    );

    render(<ProjectDeliverableCheckPanel canManage projectId={projectId} />);

    expect(await screen.findByText(/共 2 项/)).toBeTruthy();
    expect(screen.getByText(/Gate 必需 1 项/)).toBeTruthy();
  });

  it("completing anything requires evidence, not just gate items", async () => {
    fetchMock.mockImplementation(async () => Response.json({ items: [item()] }));

    render(<ProjectDeliverableCheckPanel canManage projectId={projectId} />);
    await screen.findByText("EVT 测试报告");

    // Non-gate item, no evidence typed: the server would refuse, so does the UI.
    expect(
      screen.getByRole("button", { name: "标记完成" }).hasAttribute("disabled"),
    ).toBe(true);

    fireEvent.change(screen.getByLabelText("EVT 测试报告 证据或理由"), {
      target: { value: "TR-2026-001" },
    });
    expect(
      screen.getByRole("button", { name: "标记完成" }).hasAttribute("disabled"),
    ).toBe(false);
  });

  it("a gate item offers no waive path at all", async () => {
    fetchMock.mockImplementation(async () =>
      Response.json({ items: [item({ is_gate: true })] }),
    );

    render(<ProjectDeliverableCheckPanel canManage projectId={projectId} />);
    await screen.findByText("EVT 测试报告");

    expect(screen.queryByRole("button", { name: "标记不适用" })).toBeNull();
    expect(screen.getByText("Gate 必需项不可标记不适用")).toBeTruthy();
  });

  it("completion sends evidence_reference and waiving sends note", async () => {
    fetchMock.mockImplementation(async () => Response.json({ items: [item()] }));
    render(<ProjectDeliverableCheckPanel canManage projectId={projectId} />);
    await screen.findByText("EVT 测试报告");

    fireEvent.change(screen.getByLabelText("EVT 测试报告 证据或理由"), {
      target: { value: "TR-2026-001" },
    });
    fireEvent.click(screen.getByRole("button", { name: "标记完成" }));

    await waitFor(() => {
      const write = fetchMock.mock.calls.find((call) => String(call[0]).includes("/resolve"));
      expect(String(write?.[0])).toBe(
        `/api/projects/${projectId}/deliverable-checks/items/${itemId}/resolve`,
      );
      expect(JSON.parse(String(write?.[1]?.body))).toEqual({
        status: "completed",
        evidence_reference: "TR-2026-001",
      });
    });

    fetchMock.mockClear();
    fireEvent.change(screen.getByLabelText("EVT 测试报告 证据或理由"), {
      target: { value: "本项目不涉及该认证" },
    });
    fireEvent.click(screen.getByRole("button", { name: "标记不适用" }));

    await waitFor(() => {
      const write = fetchMock.mock.calls.find((call) => String(call[0]).includes("/resolve"));
      expect(JSON.parse(String(write?.[1]?.body))).toEqual({
        status: "not_applicable",
        note: "本项目不涉及该认证",
      });
    });
  });

  it("a viewer without gate management sees the list but no actions", async () => {
    fetchMock.mockImplementation(async () => Response.json({ items: [item()] }));

    render(<ProjectDeliverableCheckPanel canManage={false} projectId={projectId} />);
    await screen.findByText("EVT 测试报告");

    expect(screen.queryByRole("button", { name: "标记完成" })).toBeNull();
    expect(screen.queryByRole("button", { name: "按模板生成检查项" })).toBeNull();
  });
});
