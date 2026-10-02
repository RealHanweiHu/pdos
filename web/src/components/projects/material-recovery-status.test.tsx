import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MaterialRecoveryStatus, type MaterialClosureState } from "./material-recovery-status";

afterEach(cleanup);
const ready: MaterialClosureState = { ready: true, review_current: true, supply_ready: true,
  reasons: [], reference: { exception_id: "original-exception", review_id: "review-v3",
    source_digest: "a".repeat(64) } };

describe("original material Issue recovery handoff", () => {
  it("binds the original Issue link to the current immutable named review", () => {
    render(<MaterialRecoveryStatus projectId="p" issueId="original-issue" closure={ready} current/>);
    const link = screen.getByRole("link", { name: "到原问题进行具名验证" });
    const url = new URL(link.getAttribute("href")!, "http://localhost");
    expect(url.searchParams.get("entity_id")).toBe("original-issue");
    expect(url.searchParams.get("material_exception_id")).toBe("original-exception");
    expect(url.searchParams.get("material_review_id")).toBe("review-v3");
    expect(url.searchParams.get("material_source_digest")).toBe(ready.reference?.source_digest);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it.each([false, true])("does not expose closure handoff for stale or unreviewed supply (%s)", current => {
    const closure = current ? { ...ready, ready: false, reference: null,
      reasons: ["当前供给尚未复核"] } : ready;
    render(<MaterialRecoveryStatus projectId="p" issueId="original-issue" closure={closure} current={current}/>);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
});
