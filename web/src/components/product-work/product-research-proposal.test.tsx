import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ProductResearchProposal } from "./product-research-proposal";

const plan = { question: "研究问题", user_groups: ["骑行者"], regions: ["华东"], time_scope: "本周", method: "访谈", expected_decision: "安排实验", stop_conditions: ["完成三次访谈"] };
const finding = { id: "finding-one", run_id: "run-one", status: "pending_review", proposed_digest: "a".repeat(64), accepted_digest: null, proposed_payload: { assessment: { research_plan: plan } }, accepted_payload: null, review_comment: null, applied_entity_id: null };
const record = { finding, sources_current: true, owner_user_id: "owner", product_line_id: null };
const props = { base: "spaces/space-one", runId: "run-one", disabled: false };
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
async function read() { fireEvent.click(screen.getByRole("button", { name: "读取 / 刷新研究候选" })); await screen.findByText("待核对"); }

describe("research candidate human boundary", () => {
  it("requires a second action to apply and sends the reviewed edits with no authority fields", async () => {
    const accepted = { ...finding, status: "accepted", accepted_digest: "b".repeat(64), accepted_payload: { proposal: { ...plan, question: "核对后的问题" } }, review_comment: "核对完成" };
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(record)).mockResolvedValueOnce(Response.json({ finding: accepted })).mockResolvedValueOnce(Response.json({ finding: { ...accepted, status: "applied", applied_entity_id: "research-one" } }));
    vi.stubGlobal("fetch", fetcher); render(<ProductResearchProposal {...props}/>); await read();
    expect(screen.queryByRole("button", { name: "独立应用：创建研究草稿" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "接受核对后的计划" })).toBeDisabled();
    expect(screen.queryByLabelText("研究问题")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "修订这份计划" }));
    fireEvent.change(screen.getByLabelText("研究问题"), { target: { value: "核对后的问题" } });
    fireEvent.change(screen.getByLabelText("办理说明"), { target: { value: "核对完成" } });
    fireEvent.click(screen.getByRole("button", { name: "接受核对后的计划" }));
    await screen.findByText("已接受，尚未创建任务");
    expect(fetcher).toHaveBeenCalledTimes(2);
    const review = JSON.parse(String(fetcher.mock.calls[1][1]?.body));
    expect(review.proposal.question).toBe("核对后的问题");
    expect(review.proposal).not.toHaveProperty("owner_user_id");
    expect(screen.getByLabelText("研究问题")).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "独立应用：创建研究草稿" }));
    expect(await screen.findByRole("link", { name: "打开研究任务" })).toHaveAttribute("href", "/product-work?space=space-one&tab=research&line=#research-research-one");
    expect(JSON.parse(String(fetcher.mock.calls[2][1]?.body))).toEqual({ run_id: "run-one", finding_id: "finding-one", accepted_digest: accepted.accepted_digest });
  });
  it("blocks acceptance for changed sources and still allows rejection", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(Response.json({ ...record, sources_current: false }));
    vi.stubGlobal("fetch", fetcher); render(<ProductResearchProposal {...props}/>); await read();
    fireEvent.change(screen.getByLabelText("办理说明"), { target: { value: "需重新分析" } });
    expect(screen.getByRole("button", { name: "接受核对后的计划" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "拒绝此候选" })).toBeEnabled();
  });
  it("clears candidate after uncertain response and recovers actual state by reading", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(record)).mockRejectedValueOnce(new Error("网络中断"))
      .mockResolvedValueOnce(Response.json({ ...record, finding: { ...finding, status: "accepted", accepted_digest: "b".repeat(64), accepted_payload: { proposal: plan }, review_comment: "核对完成" } }));
    vi.stubGlobal("fetch", fetcher); render(<ProductResearchProposal {...props}/>); await read();
    fireEvent.change(screen.getByLabelText("办理说明"), { target: { value: "核对完成" } });
    fireEvent.click(screen.getByRole("button", { name: "接受核对后的计划" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("请重新读取候选状态后继续");
    expect(screen.queryByLabelText("研究问题")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "读取 / 刷新研究候选" }));
    await screen.findByText("已接受，尚未创建任务");
    expect(fetcher).toHaveBeenCalledTimes(3);
  });
});
