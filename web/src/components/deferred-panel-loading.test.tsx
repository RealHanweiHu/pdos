import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { withDeferredPanelBoundary } from "./deferred-panel-loading";

describe("deferred business panels", () => {
  it("keeps other work and unsaved input available when one panel fails", () => {
    const log = vi.spyOn(console, "error").mockImplementation(() => {});
    const Broken = withDeferredPanelBoundary(() => { throw new Error("chunk unavailable"); });
    try {
      render(<><label>未提交说明<input defaultValue="保留我的内容"/></label><Broken/><button>其他业务操作</button></>);
      expect(screen.getByRole("alert")).toHaveTextContent("重新载入页面会清除未提交内容");
      expect(screen.getByLabelText("未提交说明")).toHaveValue("保留我的内容");
      expect(screen.getByRole("button", { name: "其他业务操作" })).toBeEnabled();
      expect(screen.getByRole("button", { name: "重新载入页面" })).toBeEnabled();
    } finally { log.mockRestore(); }
  });
});
