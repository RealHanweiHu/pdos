import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ProjectTestSources } from "./project-test-sources";

const source = {kind: "document" as const, id:"fragment", reference_id:"document:fragment", label:"客户要求.xlsx", version:"b".repeat(64), digest:"a".repeat(64), locator:"要求页第 1 行", status:"内部资料，内容待人工核对", excerpt:"输入 A 显示 A", href:"/projects", available:true};
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
describe("selected test plan sources", () => {
  it("previews source text/version and selects a frozen source rather than trusting pasted IDs", async () => {
    const fetcher=vi.fn().mockResolvedValue(new Response(JSON.stringify({items:[source],total:1,next_offset:null})));
    vi.stubGlobal("fetch",fetcher); const change=vi.fn();
    render(<ProjectTestSources projectId="project" planId="plan" selected={[]} onChange={change} disabled={false} />);
    fireEvent.click(screen.getByRole("button",{name:"选择文件或规格"}));
    expect(await screen.findByText("输入 A 显示 A")).toBeInTheDocument();
    expect(screen.getByText(/文件版本 bbbbbbbbbbbb/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox"));
    expect(change).toHaveBeenCalledWith([source]);
    expect(fetcher.mock.calls[0][0]).toContain("suggestion-sources?kind=document&offset=0");
  });
  it("shows pagination and preserves selected sources when a refresh fails", async () => {
    const fetcher=vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({items:[source],total:2,next_offset:10}))).mockRejectedValueOnce(new Error("读取失败"));
    vi.stubGlobal("fetch",fetcher); const change=vi.fn();
    render(<ProjectTestSources projectId="project" planId="plan" selected={[source]} onChange={change} disabled={false} />);
    fireEvent.click(screen.getByRole("button",{name:"选择文件或规格"}));
    fireEvent.click(await screen.findByRole("button",{name:"加载更多依据"}));
    await waitFor(()=>expect(screen.getByRole("alert")).toHaveTextContent("读取失败"));
    expect(change).not.toHaveBeenCalled();
    expect(screen.getByRole("button",{name:"移除 客户要求.xlsx"})).toBeInTheDocument();
  });
});
