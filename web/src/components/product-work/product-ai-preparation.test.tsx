import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ProductAiPreparation } from "./product-ai-preparation";
import type { ProductCatalog } from "./product-work-api";

const catalog: ProductCatalog = { nodes: [], members: [], can_create_line: true, line_access: {} };
const source = { id: "source", kind: "research", label: "原研究任务", as_of: "2026-09-29T00:00:00Z" };
const options = { items: [source], next_offset: null, generation_message: "待接入生成" };
const prepared = { digest: "a".repeat(64), warnings: ["尚无外部证据"], coverage_limits: [], references: [
  { reference_id: "research:source", label: "原研究依据", href: "/product-work?space=one", fields: { question: "私有原始问题" } },
] };
function open() { fireEvent.click(screen.getByText("小Pai · 核对本次产品工作资料")); }
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("product work source preparation", () => {
  it("binds selected sources and question, then invalidates the preview on edits", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(options)).mockResolvedValueOnce(Response.json(prepared));
    vi.stubGlobal("fetch", fetcher);
    render(<ProductAiPreparation base="spaces/one" capability="research_planning" catalog={catalog}/>);
    expect(fetcher).not.toHaveBeenCalled(); open();
    fireEvent.click(screen.getByRole("button", { name: "读取可用来源" }));
    fireEvent.click(await screen.findByRole("checkbox"));
    fireEvent.change(screen.getByLabelText("本次需要解决的问题"), { target: { value: "下一步研究什么？" } });
    fireEvent.click(screen.getByRole("button", { name: "核对资料与缺项" }));
    await screen.findByText("原研究依据");
    expect(JSON.parse(String(fetcher.mock.calls[1][1]?.body))).toEqual({
      capability: "research_planning", product_line_id: null, question: "下一步研究什么？",
      sources: [{ kind: "research", id: "source" }],
    });
    fireEvent.change(screen.getByLabelText("本次需要解决的问题"), { target: { value: "改为分析竞品" } });
    expect(screen.queryByText("原研究依据")).not.toBeInTheDocument();
  });

  it("clears previous source content when refreshed authorization fails", async () => {
    vi.stubGlobal("fetch", vi.fn<typeof fetch>()
      .mockResolvedValueOnce(Response.json(prepared))
      .mockResolvedValueOnce(Response.json({ detail: { message: "来源访问已撤销" } }, { status: 403 })));
    render(<ProductAiPreparation base="spaces/one" capability="research_planning" catalog={catalog}/>); open();
    fireEvent.change(screen.getByLabelText("本次需要解决的问题"), { target: { value: "规划研究" } });
    fireEvent.click(screen.getByRole("button", { name: "核对资料与缺项" }));
    await screen.findByText("原研究依据");
    fireEvent.click(screen.getByRole("button", { name: "核对资料与缺项" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("来源访问已撤销");
    expect(screen.queryByText("原研究依据")).not.toBeInTheDocument();
    expect(screen.queryByText(/私有原始问题/)).not.toBeInTheDocument();
  });

  it("discards late results after switching workspaces and requires a line for strategy", async () => {
    let resolve!: (response: Response) => void;
    vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockImplementation(() => new Promise(r => { resolve = r; })));
    const view = render(<ProductAiPreparation key="one" base="spaces/one" capability="research_planning" catalog={catalog}/>); open();
    fireEvent.change(screen.getByLabelText("本次需要解决的问题"), { target: { value: "规划研究" } });
    fireEvent.click(screen.getByRole("button", { name: "核对资料与缺项" }));
    view.rerender(<ProductAiPreparation key="two" base="spaces/two" capability="product_strategy" catalog={catalog}/>); open();
    await act(async () => resolve(Response.json(prepared)));
    expect(screen.queryByText("原研究依据")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("本次需要解决的问题"), { target: { value: "策略比较" } });
    expect(screen.getByRole("button", { name: "核对资料与缺项" })).toBeDisabled();
  });
});
