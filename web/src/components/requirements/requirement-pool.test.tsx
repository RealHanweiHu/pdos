import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { RequirementPool } from "./requirement-pool";

const { routerPush, routerReplace } = vi.hoisted(() => ({
  routerPush: vi.fn(),
  routerReplace: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: routerPush, replace: routerReplace }),
}));

function jsonResponse(body: object, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const identity = {
  tenant: { id: "tenant-1", slug: "beepump", name: "Beehive Technology" },
  user: {
    id: "user-1",
    tenant_id: "tenant-1",
    username: "owner",
    display_name: "Initial Owner",
    role: "owner",
    email: null,
    is_active: true,
  },
};

const customer = {
  id: "customer-1",
  code: "ACME",
  name: "Acme Pumps",
  status: "active",
};

const createdRequirement = {
  id: "requirement-1",
  code: "REQ-001",
  title: "Reduce seal leakage",
  description: "Target the next platform.",
  source: "customer_interview",
  status: "draft",
  priority: "high",
  acceptance_criteria: ["Leakage below 1 ml/h", "DVT report attached"],
  customer,
  created_by_user_id: "user-1",
  created_at: "2026-08-11T14:00:00Z",
  updated_at: "2026-08-11T14:00:00Z",
};

describe("RequirementPool", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    fetchMock.mockReset();
    routerReplace.mockReset();
    routerPush.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("loads the empty pool and creates a Customer-linked requirement", async () => {
    const user = userEvent.setup();
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input);
      if (path === "/api/session/me") return jsonResponse(identity);
      if (path === "/api/customers") return jsonResponse({ items: [customer] });
      if (path === "/api/requirements" && init?.method === "POST") {
        return jsonResponse(createdRequirement, 201);
      }
      if (path === "/api/requirements") return jsonResponse({ items: [] });
      throw new Error(`unexpected request: ${path}`);
    });

    render(<RequirementPool />);

    expect(await screen.findByRole("heading", { name: "需求池" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "还没有需求" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "新建需求" }));

    await user.type(screen.getByLabelText("需求编号"), "REQ-001");
    await user.type(screen.getByLabelText("标题"), "Reduce seal leakage");
    await user.selectOptions(screen.getByLabelText("客户"), "customer-1");
    await user.selectOptions(screen.getByLabelText("优先级"), "high");
    await user.clear(screen.getByLabelText("来源"));
    await user.type(screen.getByLabelText("来源"), "customer_interview");
    await user.type(screen.getByLabelText("描述"), "Target the next platform.");
    await user.type(
      screen.getByLabelText("验收标准（每行一条）"),
      "Leakage below 1 ml/h{enter}DVT report attached",
    );
    await user.click(screen.getByRole("button", { name: "保存需求" }));

    expect(await screen.findByRole("status")).toHaveTextContent("需求已创建");
    expect(screen.getByText("REQ-001")).toBeInTheDocument();
    expect(screen.getByText("Reduce seal leakage")).toBeInTheDocument();
    expect(screen.getByText("Acme Pumps")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/requirements",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          code: "REQ-001",
          title: "Reduce seal leakage",
          customer_id: "customer-1",
          priority: "high",
          source: "customer_interview",
          description: "Target the next platform.",
          acceptance_criteria: ["Leakage below 1 ml/h", "DVT report attached"],
        }),
      }),
    );
  });

  it("redirects an expired session without rendering tenant data", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ detail: { code: "INVALID_ACCESS_TOKEN" } }, 401),
    );

    render(<RequirementPool />);

    await waitFor(() => expect(routerReplace).toHaveBeenCalledWith("/login"));
    expect(screen.queryByRole("heading", { name: "需求池" })).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("fails closed when a pool response has an invalid shape", async () => {
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path === "/api/session/me") return jsonResponse(identity);
      if (path === "/api/customers") return jsonResponse({ items: [customer] });
      if (path === "/api/requirements") return jsonResponse({ items: [{ id: "broken" }] });
      throw new Error(`unexpected request: ${path}`);
    });

    render(<RequirementPool />);

    expect(await screen.findByRole("heading", { name: "需求池暂不可用" })).toBeInTheDocument();
    expect(screen.queryByText("broken")).not.toBeInTheDocument();
  });

  it("edits an existing requirement with a minimal patch", async () => {
    const user = userEvent.setup();
    const updated = {
      ...createdRequirement,
      title: "Reduce mechanical seal leakage",
      updated_at: "2026-08-11T15:00:00Z",
    };
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input);
      if (path === "/api/session/me") return jsonResponse(identity);
      if (path === "/api/customers") return jsonResponse({ items: [customer] });
      if (path === "/api/requirements/requirement-1" && init?.method === "PATCH") {
        return jsonResponse(updated);
      }
      if (path === "/api/requirements") {
        return jsonResponse({ items: [createdRequirement] });
      }
      throw new Error(`unexpected request: ${path}`);
    });

    render(<RequirementPool />);

    await screen.findByRole("heading", { name: "需求池" });
    await user.click(screen.getByRole("button", { name: "打开需求 REQ-001" }));
    expect(screen.getByRole("heading", { name: "编辑需求" })).toBeInTheDocument();
    const title = screen.getByLabelText("标题");
    expect(title).toHaveValue("Reduce seal leakage");
    await user.clear(title);
    await user.type(title, "Reduce mechanical seal leakage");
    await user.click(screen.getByRole("button", { name: "保存更改" }));

    expect(await screen.findByRole("status")).toHaveTextContent("需求已更新");
    expect(screen.getByText("Reduce mechanical seal leakage")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/requirements/requirement-1",
      expect.objectContaining({
        method: "PATCH",
        body: JSON.stringify({ title: "Reduce mechanical seal leakage" }),
      }),
    );
  });

  it("preserves an inactive Customer and converted status during a title edit", async () => {
    const user = userEvent.setup();
    const inactiveCustomer = { ...customer, status: "inactive" as const };
    const convertedRequirement = {
      ...createdRequirement,
      customer: inactiveCustomer,
      status: "converted" as const,
    };
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input);
      if (path === "/api/session/me") return jsonResponse(identity);
      if (path === "/api/customers") {
        return jsonResponse({ items: [inactiveCustomer] });
      }
      if (path === "/api/requirements/requirement-1" && init?.method === "PATCH") {
        return jsonResponse({ ...convertedRequirement, title: "Converted requirement updated" });
      }
      if (path === "/api/requirements") {
        return jsonResponse({ items: [convertedRequirement] });
      }
      throw new Error(`unexpected request: ${path}`);
    });

    render(<RequirementPool />);

    await screen.findByText("Reduce seal leakage");
    await user.click(screen.getByRole("button", { name: "打开需求 REQ-001" }));
    expect(screen.getByText("已转开发案（状态由转 Case 流程维护）")).toBeInTheDocument();
    expect(screen.queryByLabelText("状态")).not.toBeInTheDocument();
    expect(screen.getByLabelText("客户")).toHaveValue("customer-1");
    expect(screen.getByRole("option", { name: "ACME · Acme Pumps" })).not.toBeDisabled();
    const title = screen.getByLabelText("标题");
    await user.clear(title);
    await user.type(title, "Converted requirement updated");
    await user.click(screen.getByRole("button", { name: "保存更改" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/requirements/requirement-1",
        expect.objectContaining({
          method: "PATCH",
          body: JSON.stringify({ title: "Converted requirement updated" }),
        }),
      ),
    );
  });

  it("converts an approved Requirement through a separate formal action", async () => {
    const user = userEvent.setup();
    const approvedRequirement = { ...createdRequirement, status: "approved" as const };
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input);
      if (path === "/api/session/me") return jsonResponse(identity);
      if (path === "/api/customers") return jsonResponse({ items: [customer] });
      if (
        path === "/api/requirements/requirement-1/convert-to-case" &&
        init?.method === "POST"
      ) {
        return jsonResponse(
          {
            development_case: { id: "case-1", code: "CASE-001" },
            decision: { id: "decision-1" },
          },
          201,
        );
      }
      if (path === "/api/requirements") {
        return jsonResponse({ items: [approvedRequirement] });
      }
      throw new Error(`unexpected request: ${path}`);
    });

    render(<RequirementPool />);

    await screen.findByText("Reduce seal leakage");
    await user.click(screen.getByRole("button", { name: "打开需求 REQ-001" }));
    await user.click(screen.getByRole("button", { name: "转为开发案例" }));
    await user.type(screen.getByLabelText("案例编号"), "CASE-001");
    await user.clear(screen.getByLabelText("案例标题"));
    await user.type(screen.getByLabelText("案例标题"), "Seal leakage development case");
    await user.type(screen.getByLabelText("转化理由"), "Approved customer demand.");
    const businessCase = screen.getByLabelText("商业论证（JSON）");
    await user.clear(businessCase);
    await user.click(businessCase);
    await user.paste(JSON.stringify({ market_impact: "high" }));
    await user.click(screen.getByRole("button", { name: "确认转化" }));

    await waitFor(() => expect(routerPush).toHaveBeenCalledWith("/cases"));
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/requirements/requirement-1/convert-to-case",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          code: "CASE-001",
          title: "Seal leakage development case",
          summary: "Target the next platform.",
          business_case: { market_impact: "high" },
          rationale: "Approved customer demand.",
        }),
      }),
    );
  });

  it("keeps the Requirement pool read-only for internal non-editor roles", async () => {
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path === "/api/session/me") {
        return jsonResponse({
          ...identity,
          user: { ...identity.user, role: "engineer" },
        });
      }
      if (path === "/api/customers") return jsonResponse({ items: [customer] });
      if (path === "/api/requirements") {
        return jsonResponse({ items: [createdRequirement] });
      }
      throw new Error(`unexpected request: ${path}`);
    });

    render(<RequirementPool />);

    expect(await screen.findByText("Reduce seal leakage")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "新建需求" })).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "打开需求 REQ-001" }),
    ).not.toBeInTheDocument();
  });

  it("announces load failures and retries in place", async () => {
    const user = userEvent.setup();
    let unavailable = true;
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path === "/api/session/me") return jsonResponse(identity);
      if (path === "/api/customers") return jsonResponse({ items: [customer] });
      if (path === "/api/requirements") {
        return unavailable
          ? jsonResponse({ detail: { code: "REQUIREMENT_SERVICE_UNAVAILABLE" } }, 503)
          : jsonResponse({ items: [] });
      }
      throw new Error(`unexpected request: ${path}`);
    });

    render(<RequirementPool />);

    expect(await screen.findByRole("heading", { name: "需求池暂不可用" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("未能读取需求数据");
    unavailable = false;
    await user.click(screen.getByRole("button", { name: "重新加载" }));
    expect(await screen.findByRole("heading", { name: "需求池" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "还没有需求" })).toBeInTheDocument();
  });

  it("keeps a rejected create form open with an announced error", async () => {
    const user = userEvent.setup();
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input);
      if (path === "/api/session/me") return jsonResponse(identity);
      if (path === "/api/customers") return jsonResponse({ items: [] });
      if (path === "/api/requirements" && init?.method === "POST") {
        return jsonResponse({ detail: { code: "REQUIREMENT_CODE_CONFLICT" } }, 409);
      }
      if (path === "/api/requirements") return jsonResponse({ items: [] });
      throw new Error(`unexpected request: ${path}`);
    });

    render(<RequirementPool />);

    await screen.findByRole("heading", { name: "需求池" });
    await user.click(screen.getByRole("button", { name: "新建需求" }));
    await user.type(screen.getByLabelText("需求编号"), "REQ-001");
    await user.type(screen.getByLabelText("标题"), "Duplicate requirement");
    await user.click(screen.getByRole("button", { name: "保存需求" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("需求未保存");
    expect(screen.getByRole("heading", { name: "新建需求" })).toBeInTheDocument();
  });
});
