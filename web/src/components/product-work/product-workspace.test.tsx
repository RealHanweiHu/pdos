import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ProductWorkspace } from "./product-workspace";

const push = vi.fn();
const replace = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/product-work",
}));

// The runner's Node build exposes a stub global localStorage (no full Web
// Storage API), so back the preference assertions with a real in-memory one.
const memoryStorage = new Map<string, string>();
vi.stubGlobal("localStorage", {
  getItem: (key: string) => memoryStorage.get(key) ?? null,
  setItem: (key: string, value: string) => void memoryStorage.set(key, value),
  removeItem: (key: string) => void memoryStorage.delete(key),
  clear: () => memoryStorage.clear(),
});

const identity = {
  tenant: { id: "tenant-1", slug: "beepump", name: "Beehive Technology" },
  user: {
    id: "user-1",
    tenant_id: "tenant-1",
    username: "owner",
    display_name: "Someone",
    role: "owner",
    email: null,
    is_active: true,
  },
};

const space = {
  id: "space-1",
  code: "MKT-OUTDOOR-PUMP",
  title: "户外便携充气设备",
  lifecycle: "draft",
  version: 1,
  payload_digest: "digest",
  owner_user_id: "user-1",
  user_groups: ["露营收纳", "自驾", "应急"],
  regions: ["华东", "华南"],
  use_scenarios: ["车载", "营地", "应急"],
  research_questions: ["谁在为便携充气付溢价", "现有泵的噪音痛点", "车载供电兼容性"],
};

function mockFetch() {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input);
    if (path === "/api/session/me") {
      return new Response(JSON.stringify(identity), { status: 200 });
    }
    if (path === "/api/product-work/spaces") {
      return new Response(JSON.stringify({ items: [space], can_create: true }), { status: 200 });
    }
    throw new Error(`unexpected request: ${path}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("ProductWorkspace market-space directory", () => {
  beforeEach(() => {
    memoryStorage.clear();
    push.mockReset();
    replace.mockReset();
  });
  afterEach(cleanup);

  it("renders spaces as a list with meta and lifecycle, not a dropdown", async () => {
    mockFetch();
    render(<ProductWorkspace />);
    expect(await screen.findByRole("button", { name: /户外便携充气设备/ })).toBeInTheDocument();
    expect(document.querySelector("select")).not.toBeInTheDocument();
    expect(screen.getByText(/3 个用户群 · 2 个地域 · 3 个场景 · 3 个研究问题/)).toBeInTheDocument();
    expect(screen.getByText("草稿")).toBeInTheDocument();
  });

  it("switches to a card view with a derived visual and persists the preference", async () => {
    mockFetch();
    render(<ProductWorkspace />);
    expect(await screen.findByRole("button", { name: /户外便携充气设备/ })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "卡片视图" }));
    expect(window.localStorage.getItem("pdos.productWork.view")).toBe("cards");
    expect(screen.getByText("MO")).toBeInTheDocument(); // derived monogram from MKT-OUTDOOR-PUMP
    await userEvent.click(screen.getByRole("button", { name: "列表视图" }));
    expect(window.localStorage.getItem("pdos.productWork.view")).toBe("list");
  });

  it("opens a space through the ?space= deep link when a row is clicked", async () => {
    mockFetch();
    render(<ProductWorkspace />);
    await userEvent.click(await screen.findByRole("button", { name: /户外便携充气设备/ }));
    expect(push).toHaveBeenCalledWith("/product-work?space=space-1");
  });
});
