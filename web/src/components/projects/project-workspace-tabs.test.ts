import { describe, expect, it } from "vitest";

import { LEGACY_TAB_ALIASES, resolveTab } from "./project-workspace-view";

/**
 * D9/D31 regrouped ten table-shaped tabs into nine business domains. Links
 * minted before that — bookmarks, DingTalk cards, stored evidence hrefs — must
 * keep landing somewhere sensible.
 */
describe("project workspace tab compatibility", () => {
  it("resolves every current domain key to itself", () => {
    for (const key of [
      "overview",
      "plan",
      "work-items",
      "materials",
      "engineering",
      "decisions",
      "gates",
      "quality",
      "documents",
    ] as const) {
      expect(resolveTab(key)).toBe(key);
    }
  });

  it("redirects each pre-regrouping tab onto the domain that absorbed it", () => {
    expect(resolveTab("timeline")).toBe("overview");
    expect(resolveTab("ai-chat")).toBe("overview");
    expect(resolveTab("tasks")).toBe("work-items");
    expect(resolveTab("issues")).toBe("work-items");
    expect(resolveTab("risks")).toBe("work-items");
    expect(resolveTab("product-engineering")).toBe("engineering");
  });

  it("covers every retired tab key so no old deep link dead-ends", () => {
    const retired = ["timeline", "tasks", "issues", "risks", "product-engineering", "ai-chat"];
    expect(Object.keys(LEGACY_TAB_ALIASES).sort()).toEqual([...retired].sort());
  });

  it("refuses unknown tabs rather than guessing", () => {
    expect(resolveTab("not-a-tab")).toBeNull();
    expect(resolveTab(null)).toBeNull();
    expect(resolveTab("")).toBeNull();
  });
});
