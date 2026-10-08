import { act, cleanup, renderHook } from "@testing-library/react";
import { createElement } from "react";
import { renderToString } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  getAvailablePerspectives,
  getDefaultPerspective,
  getPerspective,
  useWorkPerspective,
  type WorkPerspective,
} from "./workspace-experience";
import type { WorkspaceIdentity } from "./workspace-types";

let identitySequence = 0;
function identity(role: string, userId = `perspective-user-${++identitySequence}`, tenantId = "perspective-tenant"): WorkspaceIdentity {
  return {
    tenant: { id: tenantId, name: "测试组织", slug: tenantId },
    user: {
      id: userId, tenant_id: tenantId, username: userId, display_name: "测试成员",
      role, email: null, is_active: true,
    },
  };
}

describe("work perspectives", () => {
  beforeEach(() => {
    // Use jsdom's Storage; Node also exposes an unrelated localStorage global.
    vi.stubGlobal("localStorage", window.sessionStorage);
    window.localStorage.clear();
  });
  afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

  it("offers business perspectives to internal people without granting administration or inventing RBAC roles", () => {
    const business = ["personal", "product", "project", "engineering", "quality", "introduction", "supply", "portfolio"];
    for (const role of ["project_manager", "engineer", "quality"]) {
      expect(getAvailablePerspectives(role)).toEqual(business);
    }
    for (const role of ["owner", "admin"]) {
      expect(getAvailablePerspectives(role)).toEqual([...business, "administration"]);
    }
    for (const role of ["supplier", "customer", "product_manager", "management", "unknown"]) {
      expect(getAvailablePerspectives(role)).toEqual([]);
    }
    expect(getDefaultPerspective("engineer")).toBe("engineering");
    expect(getDefaultPerspective("quality")).toBe("quality");
    expect(getDefaultPerspective("project_manager")).toBe("personal");
    expect(getDefaultPerspective("admin")).toBe("personal");
  });

  it("keeps governance links within the administrative perspective and uses existing project tabs", () => {
    const tabs = ["overview", "work-items", "stages", "plan", "engineering", "quality", "materials", "gates", "documents", "decisions"];
    const routes = new Set(["/my-work", "/product-work", "/projects", "/portfolio", "/dashboard", "/requirements", "/cases", "/ask", "/ai-review", "/knowledge"]);
    for (const id of getAvailablePerspectives("engineer")) {
      const perspective = getPerspective(id);
      expect(tabs).toContain(perspective.primaryProjectTab);
      for (const route of perspective.priorityRoutes) {
        expect(routes.has(route)).toBe(true);
        expect(perspective.actionLabels[route]).toBeTruthy();
      }
      for (const step of perspective.steps) expect(routes.has(step.href)).toBe(true);
    }
    expect(getPerspective("administration").priorityRoutes).toContain("/governance/users");
  });

  it("keeps an external account's business perspectives unavailable and ignores a setter call", () => {
    const { result } = renderHook(() => useWorkPerspective(identity("customer", "external-perspective-user")));
    expect(result.current.available).toEqual([]);
    act(() => result.current.setPerspective("administration"));
    expect(result.current.perspective.id).toBe("personal");
    expect(window.localStorage.length).toBe(0);
  });

  it("persists the preference per tenant and user, without carrying it across identity changes", () => {
    const person = identity("engineer");
    const { result, rerender } = renderHook(({ current }) => useWorkPerspective(current), { initialProps: { current: person } });
    act(() => result.current.setPerspective("product"));
    expect(result.current.perspective.id).toBe("product");

    const otherUser = identity("engineer");
    rerender({ current: otherUser });
    expect(result.current.perspective.id).toBe("engineering");
    act(() => result.current.setPerspective("quality"));

    rerender({ current: identity("engineer", person.user.id, "another-perspective-tenant") });
    expect(result.current.perspective.id).toBe("engineering");
    rerender({ current: person });
    expect(result.current.perspective.id).toBe("product");
    rerender({ current: otherUser });
    expect(result.current.perspective.id).toBe("quality");
  });

  it("falls back from unknown or no longer available preferences and refuses administrative selection", () => {
    const person = identity("admin");
    const { result, rerender } = renderHook(({ current }) => useWorkPerspective(current), { initialProps: { current: person } });
    act(() => result.current.setPerspective("administration"));
    const key = window.localStorage.key(0)!;
    rerender({ current: { ...person, user: { ...person.user, role: "engineer" } } });
    expect(result.current.perspective.id).toBe("engineering");
    expect(result.current.available.some((item) => item.id === "administration")).toBe(false);
    act(() => result.current.setPerspective("administration"));
    expect(result.current.perspective.id).toBe("engineering");

    act(() => {
      window.localStorage.setItem(key, "unknown-perspective");
      window.dispatchEvent(new StorageEvent("storage", { key, newValue: "unknown-perspective" }));
    });
    expect(result.current.perspective.id).toBe("engineering");
    expect(getPerspective("unknown-perspective" as WorkPerspective).id).toBe("personal");
  });

  it("synchronizes mounted consumers and storage changes, including preference removal", () => {
    const person = identity("engineer");
    const first = renderHook(() => useWorkPerspective(person));
    const second = renderHook(() => useWorkPerspective(person));
    act(() => first.result.current.setPerspective("supply"));
    expect(second.result.current.perspective.id).toBe("supply");
    const key = window.localStorage.key(0)!;
    act(() => {
      window.localStorage.setItem(key, "portfolio");
      window.dispatchEvent(new StorageEvent("storage", { key, newValue: "portfolio" }));
    });
    expect(first.result.current.perspective.id).toBe("portfolio");
    expect(second.result.current.perspective.id).toBe("portfolio");
    act(() => {
      window.localStorage.removeItem(key);
      window.dispatchEvent(new StorageEvent("storage", { key, newValue: null }));
    });
    expect(first.result.current.perspective.id).toBe("engineering");
  });

  it("continues changing perspectives when preference storage cannot be read or written", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("storage unavailable"); });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("storage unavailable"); });
    const person = identity("quality");
    const { result, rerender } = renderHook(({ current }) => useWorkPerspective(current), { initialProps: { current: person } });
    expect(result.current.perspective.id).toBe("quality");
    act(() => result.current.setPerspective("project"));
    expect(result.current.perspective.id).toBe("project");
    rerender({ current: identity("quality") });
    expect(result.current.perspective.id).toBe("quality");
    rerender({ current: person });
    expect(result.current.perspective.id).toBe("project");
  });

  it("renders the role default on the server even when a different browser preference exists", () => {
    const person = identity("engineer");
    const { result } = renderHook(() => useWorkPerspective(person));
    act(() => result.current.setPerspective("product"));
    function ReadPerspective() { return useWorkPerspective(person).perspective.label; }
    expect(renderToString(createElement(ReadPerspective))).toBe(getPerspective("engineering").label);
  });
});
