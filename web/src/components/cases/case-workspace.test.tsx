import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CaseWorkspace } from "./case-workspace";

const { routerReplace } = vi.hoisted(() => ({ routerReplace: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: routerReplace }),
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

const developmentCase = {
  id: "case-1",
  requirement_id: "requirement-1",
  code: "CASE-001",
  title: "Seal leakage development case",
  summary: "Evaluate the next pump platform.",
  status: "draft",
  business_case: { market_impact: "high" },
  created_by_user_id: "user-1",
  created_at: "2026-08-11T15:00:00Z",
  updated_at: "2026-08-11T15:00:00Z",
};

describe("CaseWorkspace", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    fetchMock.mockReset();
    routerReplace.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("loads an accessible empty state", async () => {
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path === "/api/session/me") return jsonResponse(identity);
      if (path === "/api/development-cases") return jsonResponse({ items: [] });
      throw new Error(`unexpected request: ${path}`);
    });

    render(<CaseWorkspace />);

    expect(await screen.findByRole("heading", { name: "开发案例" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "还没有开发案例" })).toBeInTheDocument();
  });

  it("edits content with a minimal PATCH", async () => {
    const user = userEvent.setup();
    const updated = {
      ...developmentCase,
      title: "Updated development case",
      updated_at: "2026-08-11T16:00:00Z",
    };
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input);
      if (path === "/api/session/me") return jsonResponse(identity);
      if (path === "/api/development-cases" && !init?.method) {
        return jsonResponse({ items: [developmentCase] });
      }
      if (path === "/api/development-cases/case-1" && init?.method === "PATCH") {
        return jsonResponse(updated);
      }
      throw new Error(`unexpected request: ${path}`);
    });

    render(<CaseWorkspace />);

    await screen.findByText("Seal leakage development case");
    await user.click(screen.getByRole("button", { name: "打开开发案例 CASE-001" }));
    const title = screen.getByLabelText("标题");
    await user.clear(title);
    await user.type(title, "Updated development case");
    await user.click(screen.getByRole("button", { name: "保存更改" }));

    expect(await screen.findByRole("status")).toHaveTextContent("开发案例已更新");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/development-cases/case-1",
      expect.objectContaining({
        method: "PATCH",
        body: JSON.stringify({ title: "Updated development case" }),
      }),
    );
  });

  it("executes an explicit state transition", async () => {
    const user = userEvent.setup();
    const evaluating = {
      ...developmentCase,
      status: "evaluating",
      updated_at: "2026-08-11T16:00:00Z",
    };
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input);
      if (path === "/api/session/me") return jsonResponse(identity);
      if (path === "/api/development-cases" && !init?.method) {
        return jsonResponse({ items: [developmentCase] });
      }
      if (
        path === "/api/development-cases/case-1/transitions" &&
        init?.method === "POST"
      ) {
        return jsonResponse(evaluating);
      }
      throw new Error(`unexpected request: ${path}`);
    });

    render(<CaseWorkspace />);

    await screen.findByText("Seal leakage development case");
    await user.click(screen.getByRole("button", { name: "打开开发案例 CASE-001" }));
    await user.click(screen.getByRole("button", { name: "进入评估" }));

    expect(await screen.findByRole("status")).toHaveTextContent("状态已更新为评估中");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/development-cases/case-1/transitions",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ to_status: "evaluating" }),
      }),
    );
  });

  it("announces a rejected transition as an error", async () => {
    const user = userEvent.setup();
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input);
      if (path === "/api/session/me") return jsonResponse(identity);
      if (path === "/api/development-cases" && !init?.method) {
        return jsonResponse({ items: [developmentCase] });
      }
      if (path.endsWith("/transitions")) {
        return jsonResponse({ detail: { code: "CASE_INVALID_TRANSITION" } }, 409);
      }
      throw new Error(`unexpected request: ${path}`);
    });

    render(<CaseWorkspace />);

    await screen.findByText("Seal leakage development case");
    await user.click(screen.getByRole("button", { name: "打开开发案例 CASE-001" }));
    await user.click(screen.getByRole("button", { name: "进入评估" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("状态未更新");
    expect(screen.getByRole("heading", { name: "编辑开发案例" })).toBeInTheDocument();
  });

  it("keeps internal viewer roles read-only", async () => {
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path === "/api/session/me") {
        return jsonResponse({ ...identity, user: { ...identity.user, role: "engineer" } });
      }
      if (path === "/api/development-cases") {
        return jsonResponse({ items: [developmentCase] });
      }
      throw new Error(`unexpected request: ${path}`);
    });

    render(<CaseWorkspace />);

    expect(await screen.findByText("Seal leakage development case")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "打开开发案例 CASE-001" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "进入评估" })).not.toBeInTheDocument();
  });

  it("redirects expired sessions and retries load errors", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({}, 401));
    const firstRender = render(<CaseWorkspace />);
    await waitFor(() => expect(routerReplace).toHaveBeenCalledWith("/login"));
    firstRender.unmount();

    const user = userEvent.setup();
    let unavailable = true;
    fetchMock.mockReset();
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path === "/api/session/me") return jsonResponse(identity);
      if (path === "/api/development-cases") {
        return unavailable ? jsonResponse({}, 503) : jsonResponse({ items: [] });
      }
      throw new Error(`unexpected request: ${path}`);
    });
    render(<CaseWorkspace />);
    expect(await screen.findByRole("heading", { name: "开发案例暂不可用" })).toBeInTheDocument();
    unavailable = false;
    await user.click(screen.getByRole("button", { name: "重新加载" }));
    expect(await screen.findByRole("heading", { name: "开发案例" })).toBeInTheDocument();
  });
});
