import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { XiaopaiAnswer } from "./xiaopai-answer";

afterEach(cleanup);

describe("研究对比答复", () => {
  it("renders source-backed rows as a table and preserves surrounding findings", () => {
    render(<XiaopaiAnswer researchDraft answer={"公开研究结果\n| 型号 | 压力 | 来源 |\n|---|---|---|\n| Pump A | 20 PSI | brand.example |\n| Pump B | 未知 | review.example |\n价格待核实"}/>);
    const table = screen.getByRole("table", { name: "研究资料对比" });
    expect(within(table).getAllByRole("row")).toHaveLength(3);
    expect(within(table).getByRole("columnheader", { name: "压力" })).toBeInTheDocument();
    expect(within(table).getByRole("cell", { name: "20 PSI" })).toBeInTheDocument();
    expect(screen.getByText("价格待核实")).toBeInTheDocument();
    expect(screen.getByText(/AI 研究草稿/)).toBeInTheDocument();
  });

  it("keeps escaped pipes and external HTML literal without executing it", () => {
    const { container } = render(<XiaopaiAnswer answer={"| 型号 | 说明 |\n|---|---|\n| A\\|B | <script>alert(1)</script> |"}/>);
    expect(screen.getByRole("cell", { name: "A|B" })).toBeInTheDocument();
    expect(screen.getByText("<script>alert(1)</script>")).toBeInTheDocument();
    expect(container.querySelector("script")).toBeNull();
  });

  it("retains malformed table text and ordinary prose", () => {
    const answer = "普通答复\n| 型号 | 压力 |\n|---|---|\n| 值不完整 |\n所有未知保留";
    render(<XiaopaiAnswer answer={answer}/>);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.getByText(/所有未知保留/)).toHaveTextContent("值不完整");
    expect(screen.queryByText(/AI 研究草稿/)).not.toBeInTheDocument();
  });
});
