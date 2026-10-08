import { cleanup, renderHook } from "@testing-library/react";
import { createElement } from "react";
import { renderToString } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { configuredProjectTab, getAvailablePerspectives, getDefaultPerspective, getPerspective, getWorkHomeHref, useWorkPerspective } from "./workspace-experience";
import type { WorkspaceIdentity } from "./workspace-types";

function identity(role: string, userId = "person", tenantId = "company"): WorkspaceIdentity {
  return { tenant: { id: tenantId, name: "公司", slug: tenantId }, user: { id: userId, tenant_id: tenantId, username: userId, display_name: "小李", role, email: null, is_active: true } };
}

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("automatic personal work experience", () => {
  it("adds assigned modules once, follows revocation, and keeps the primary role", () => {
    const person = identity("engineer");
    person.user.work_modules = ["quality", "product", "engineering", "quality", "supply"];
    const { result, rerender } = renderHook(({ current }) => useWorkPerspective(current), { initialProps: { current: person } });
    expect(result.current.perspective.id).toBe("engineering");
    expect(result.current.available.map(item => item.id)).toEqual(["engineering", "product", "quality", "supply"]);
    expect(configuredProjectTab(person, "quality")).toBe("quality");
    expect(configuredProjectTab(person, "supply")).toBe("materials");
    expect(configuredProjectTab(person, "portfolio")).toBeNull();
    rerender({ current: { ...person, user: { ...person.user, work_modules: [] } } });
    expect(result.current.available.map(item => item.id)).toEqual(["engineering"]);
    expect(getAvailablePerspectives("customer", ["product"])).toEqual([]);
  });
  it.each([
    ["product_manager", "product"], ["project_manager", "project"],
    ["engineer", "engineering"], ["quality", "quality"],
    ["owner", "portfolio"], ["admin", "administration"],
  ])("derives %s's experience from the verified identity", (role, perspective) => {
    expect(getDefaultPerspective(role)).toBe(perspective);
    expect(getAvailablePerspectives(role)).toEqual([perspective]);
    expect(getWorkHomeHref(role)).toBe("/my-work");
    const { result } = renderHook(() => useWorkPerspective(identity(role)));
    expect(result.current.perspective.id).toBe(perspective);
    expect(result.current).not.toHaveProperty("setPerspective");
  });

  it.each(["supplier", "customer", "unknown", "product_designer"])("does not invent internal access for %s", role => {
    expect(getAvailablePerspectives(role)).toEqual([]);
    expect(getWorkHomeHref(role)).toBe("/projects");
  });

  it("never reads remembered browser views, even if storage is unavailable", () => {
    const read = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("unavailable"); });
    const { result } = renderHook(() => useWorkPerspective(identity("engineer")));
    expect(result.current.perspective.id).toBe("engineering");
    expect(read).not.toHaveBeenCalled();
  });

  it("immediately follows identity changes and role removal without retaining another person's layout", () => {
    const { result, rerender } = renderHook(({ current }) => useWorkPerspective(current), { initialProps: { current: identity("admin") } });
    expect(result.current.perspective.id).toBe("administration");
    rerender({ current: identity("quality", "other", "other-tenant") });
    expect(result.current.perspective.id).toBe("quality");
    rerender({ current: identity("engineer") });
    expect(result.current.available.map(item => item.id)).toEqual(["engineering"]);
    rerender({ current: identity("customer") });
    expect(result.current.available).toEqual([]);
  });

  it("uses the same account experience during server rendering and hydration", () => {
    const person = identity("project_manager");
    function ReadPerspective() { return useWorkPerspective(person).perspective.label; }
    expect(renderToString(createElement(ReadPerspective))).toBe(getPerspective("project").label);
    const { result } = renderHook(() => useWorkPerspective(person));
    expect(result.current.perspective.label).toBe(getPerspective("project").label);
  });
});
