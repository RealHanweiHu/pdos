import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { KnowledgeSearch } from "./knowledge-search";

const { routerReplace } = vi.hoisted(() => ({ routerReplace: vi.fn() }));

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: routerReplace }) }));

function jsonResponse(body: object, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const identity = {
  tenant: { id: "tenant-1", slug: "beepump", name: "Beehive Technology" },
  user: {
    id: "quality-1",
    tenant_id: "tenant-1",
    username: "quality",
    display_name: "Quality",
    role: "quality",
    email: null,
    is_active: true,
  },
};

const stages = [{ id: "stage-1", code: "dvt", name: "DVT", description: null, sequence: 1 }];
const project = {
  id: "project-1",
  development_case_id: "case-1",
  customer_id: null,
  workflow: {
    id: "workflow-1",
    code: "npd",
    name: "NPD",
    description: null,
    version: 1,
    is_active: true,
    stages,
  },
  current_stage: stages[0],
  owner_user_id: "owner-1",
  code: "PRJ-001",
  name: "Pump platform",
  description: null,
  status: "active",
  start_date: null,
  target_date: null,
  created_at: "2026-08-12T16:00:00Z",
  updated_at: "2026-08-12T16:00:00Z",
};

function memory(overrides: Record<string, unknown> = {}) {
  return {
    id: "memory-1",
    project_id: "project-1",
    source_finding_id: null,
    source_ncr_id: null,
    created_by_user_id: "engineer-1",
    verified_by_user_id: null,
    archived_by_user_id: null,
    title: "Connector DVT lesson",
    content: "Validate connector pin mapping before DVT.",
    applicability: "Connector family A",
    tags: ["DVT", "connector"],
    source_refs: [],
    content_sha256: "a".repeat(64),
    review_digest: "b".repeat(64),
    knowledge_kind: "failure_case",
    status: "draft",
    verified_at: null,
    archived_at: null,
    created_at: "2026-08-12T16:00:00Z",
    updated_at: "2026-08-12T16:00:00Z",
    ...overrides,
  };
}

describe("KnowledgeSearch", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    fetchMock.mockReset();
    routerReplace.mockReset();
    vi.stubGlobal("fetch", fetchMock);
    window.history.replaceState(null, "", "/knowledge?project=project-1&memory=memory-1");
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("separates draft history from verified semantic results and enforces four eyes", async () => {
    const user = userEvent.setup();
    const draft = memory();
    const verified = memory({
      status: "verified",
      verified_by_user_id: "quality-1",
      verified_at: "2026-08-12T16:05:00Z",
    });
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input);
      if (path === "/api/session/me") return jsonResponse(identity);
      if (path === "/api/projects") return jsonResponse({ items: [project] });
      if (path === "/api/projects/project-1/memories" && !init?.method) {
        return jsonResponse({ items: [draft] });
      }
      if (path === "/api/knowledge/search") {
        return jsonResponse({
          source_status: "ready",
          items: [{
            memory: verified,
            similarity: 0.91,
            embedding_provider: "test",
            embedding_model: "memory-v1",
            href: "/knowledge?project=project-1&memory=memory-1",
          }],
        });
      }
      if (path.endsWith("/verify")) return jsonResponse(verified);
      throw new Error(`unexpected request: ${path}`);
    });

    render(<KnowledgeSearch />);

    expect(await screen.findByRole("heading", { name: "Knowledge Search" })).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "Memory 登记册" })).toHaveTextContent("草稿");
    expect(screen.getByRole("button", { name: "验证" })).toBeInTheDocument();
    await user.type(screen.getByLabelText("语义检索"), "connector lesson");
    await user.click(screen.getByRole("button", { name: "搜索已验证 Memory" }));

    const results = await screen.findByRole("region", { name: "Knowledge Search 结果" });
    expect(results).toHaveTextContent("已验证");
    expect(results).toHaveTextContent("相似度 91.0%");
    expect(results).not.toHaveTextContent("草稿");
    await user.click(screen.getByRole("button", { name: "验证" }));
    expect(await screen.findByRole("status")).toHaveTextContent("四眼验证");
    expect(fetchMock).toHaveBeenCalledWith("/api/projects/project-1/memories/memory-1/verify", expect.objectContaining({ method: "POST", body: JSON.stringify({ expected_review_digest: draft.review_digest }) }));
  });

  it("prevents the draft creator from presenting a self-verify action", async () => {
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input);
      if (path === "/api/session/me") return jsonResponse(identity);
      if (path === "/api/projects") return jsonResponse({ items: [project] });
      if (path === "/api/projects/project-1/memories" && !init?.method) {
        return jsonResponse({ items: [memory({ created_by_user_id: "quality-1" })] });
      }
      throw new Error(`unexpected request: ${path}`);
    });

    render(<KnowledgeSearch />);

    expect(await screen.findByText("需另一位成员验证")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "验证" })).not.toBeInTheDocument();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/projects/project-1/memories", expect.any(Object)));
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(0);
  });
});
