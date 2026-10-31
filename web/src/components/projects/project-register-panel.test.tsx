import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ProjectCost } from "./project-register-api";
import { costTotals, ProjectRegisterPanel } from "./project-register-panel";

function jsonResponse(body: object, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const timestamps = { created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-01T00:00:00Z" };
const members = [
  { user_id: "user-1", display_name: "Initial Owner", role: "owner", is_active: true, assignable: true },
  { user_id: "user-2", display_name: "Erin Engineer", role: "engineer", is_active: true, assignable: true },
];
const resource = {
  id: "res-1",
  project_id: "project-1",
  code: "RES-001",
  name: "Firmware engineer",
  resource_type: "person",
  assigned_user_id: "user-2",
  allocation_percent: "60.00",
  start_date: "2026-11-01",
  end_date: null,
  status: "active",
  assignee_active_allocation_percent: "110.00",
  ...timestamps,
};
const estimate: ProjectCost = {
  id: "cost-1",
  project_id: "project-1",
  code: "COST-001",
  cost_type: "tooling",
  amount: "1200.50",
  currency: "CNY",
  status: "estimate",
  incurred_on: null,
  description: "Mould deposit",
  ...timestamps,
};
const actual: ProjectCost = { ...estimate, id: "cost-2", code: "COST-002", cost_type: "labor", amount: "80.00", status: "actual", description: null };

describe("ProjectRegisterPanel", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("sums costs per currency and status in cents", () => {
    const totals = costTotals([
      { ...estimate, amount: "0.10" },
      { ...estimate, id: "x", amount: "0.20" },
      { ...actual, currency: "USD", amount: "5.00" },
    ]);
    expect(totals.get("CNY")).toEqual({ estimate: 30, approved: 0, actual: 0 });
    expect(totals.get("USD")).toEqual({ estimate: 0, approved: 0, actual: 500 });
  });

  it("shows load and totals, registers a cost, and approves an estimate", async () => {
    const user = userEvent.setup();
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input);
      if (path === "/api/projects/project-1/resources" && !init?.method) return jsonResponse({ items: [resource] });
      if (path === "/api/projects/project-1/costs" && !init?.method) return jsonResponse({ items: [estimate, actual] });
      if (path === "/api/projects/project-1/costs" && init?.method === "POST") {
        return jsonResponse({ ...estimate, id: "cost-3", code: "COST-003", cost_type: "material", amount: "99.90", description: null }, 201);
      }
      if (path === "/api/projects/project-1/costs/cost-1/transitions") return jsonResponse({ ...estimate, status: "approved" });
      throw new Error(`unexpected request: ${path}`);
    });

    render(<ProjectRegisterPanel canEdit currentUserId="user-1" members={members} projectId="project-1" />);

    const row = await screen.findByTestId("resource-row");
    expect(row).toHaveTextContent("成员：Erin Engineer");
    expect(row).toHaveTextContent("本项目投入 60%");
    expect(row).toHaveTextContent("总负荷 110%（超负荷）");
    const totals = await screen.findByTestId("cost-totals-CNY");
    expect(totals).toHaveTextContent("预估¥1,200.50");
    expect(totals).toHaveTextContent("实际¥80.00");

    await user.selectOptions(screen.getByLabelText("成本类型"), "material");
    await user.type(screen.getByLabelText("金额（CNY）"), "99.9");
    await user.click(screen.getByRole("button", { name: "登记成本" }));
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/projects/project-1/costs",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ cost_type: "material", amount: "99.9" }) }),
    );
    expect(await screen.findByRole("status")).toHaveTextContent("成本已登记");
    expect(screen.getByTestId("cost-totals-CNY")).toHaveTextContent("预估¥1,300.40");

    const estimateRow = screen.getAllByTestId("cost-row").find((item) => item.textContent?.includes("COST-001"));
    await user.click(within(estimateRow!).getByRole("button", { name: "批准" }));
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/projects/project-1/costs/cost-1/transitions",
      expect.objectContaining({ body: JSON.stringify({ to_status: "approved" }) }),
    );
    expect(await screen.findByRole("status")).toHaveTextContent("成本已批准");
    expect(screen.getByTestId("cost-totals-CNY")).toHaveTextContent("已批准¥1,200.50");
  });

  it("keeps costs hidden and read-only for roles without project edit", async () => {
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path === "/api/projects/project-1/resources") return jsonResponse({ items: [resource] });
      throw new Error(`unexpected request: ${path}`);
    });

    render(<ProjectRegisterPanel canEdit={false} currentUserId="user-2" members={members} projectId="project-1" />);

    expect(await screen.findByTestId("resource-row")).toHaveTextContent("成员：Erin Engineer（我）");
    expect(screen.getByText("成本数据仅项目经理及以上角色可见。")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "添加资源" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "释放" })).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes("/costs"))).toBe(false);
  });
});
