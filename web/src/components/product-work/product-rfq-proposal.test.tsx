import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ProductRfqProposal } from "./product-rfq-proposal";
const item = { title: "最大压力", description: "120 kPa", priority: "high", acceptance_criteria: [], missing: ["工况待澄清"], category_label: null, basis: { nature: "observed", text: "原文要求", citations: [{ reference_id: "file:original:1", digest: "a".repeat(64), field_path: ["text"], quoted_value: "Maximum pressure 120 kPa" }] } };
const detail = { finding: { id: "finding", status: "pending_review", proposed_digest: "b".repeat(64) }, items: [item], sources_current: true, references: [{ reference_id: "file:original:1", label: "RFQ.xlsx · cell:C1" }], records: [] };
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
it("confirms edited drafts with original citations and preserves unknown criteria", async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(detail)).mockResolvedValueOnce(Response.json({ finding: { ...detail.finding, status: "applied" }, records: [{ requirement_id: "requirement", accepted_item: item }] }));
  vi.stubGlobal("fetch", fetcher);
  render(<ProductRfqProposal base="spaces/space" runId="run" onFailure={vi.fn()}/>);
  await screen.findByText("Maximum pressure 120 kPa");
  fireEvent.change(screen.getByLabelText("名称"), { target: { value: "核对后的压力要求" } });
  fireEvent.change(screen.getByLabelText("核对说明"), { target: { value: "按原文登记" } });
  fireEvent.click(screen.getByRole("button", { name: "确认并登记需求草稿" }));
  await screen.findByText(/已登记1项需求草稿/);
  expect(JSON.parse(String(fetcher.mock.calls[1][1]?.body)).items[0]).toEqual({ ...item, title: "核对后的压力要求" });
  expect(fetcher).toHaveBeenCalledTimes(2);
});
it("retries an uncertain confirmation with identical content and blocks edits", async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(detail)).mockResolvedValueOnce(Response.json({ detail: { message: "响应暂未确认" } }, { status: 503 })).mockResolvedValueOnce(Response.json({ finding: { ...detail.finding, status: "applied" }, records: [{ requirement_id: "requirement", accepted_item: item }] }));
  vi.stubGlobal("fetch", fetcher);
  render(<ProductRfqProposal base="spaces/space" runId="run" onFailure={vi.fn()}/>);
  fireEvent.change(await screen.findByLabelText("核对说明"), { target: { value: "已核对" } });
  fireEvent.click(screen.getByRole("button", { name: "确认并登记需求草稿" }));
  await screen.findByRole("alert");
  expect(screen.getByLabelText("名称")).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "重试原确认" }));
  await screen.findByText(/已登记1项需求草稿/);
  expect(fetcher.mock.calls[1][1]?.body).toBe(fetcher.mock.calls[2][1]?.body);
});
it("blocks confirmation when sources have changed", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ ...detail, sources_current: false })));
  render(<ProductRfqProposal base="spaces/space" runId="run" onFailure={vi.fn()}/>);
  expect(await screen.findByRole("button", { name: "确认并登记需求草稿" })).toBeDisabled();
});
it("allows rejecting stale candidates without registering requirements", async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json({ ...detail, sources_current: false })).mockResolvedValueOnce(Response.json({ finding: { ...detail.finding, status: "rejected" }, records: [] }));
  vi.stubGlobal("fetch", fetcher);
  render(<ProductRfqProposal base="spaces/space" runId="run" onFailure={vi.fn()}/>);
  fireEvent.change(await screen.findByLabelText("核对说明"), { target: { value: "原资料已更新，拒绝旧候选" } });
  expect(screen.getByRole("button", { name: "确认并登记需求草稿" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "拒绝此批候选" }));
  await screen.findByText("已拒绝，未登记需求。");
  expect(JSON.parse(String(fetcher.mock.calls[1][1]?.body))).toMatchObject({ decision: "rejected", items: [] });
});
it("reads back a committed confirmation without sending a second write", async () => {
  const accepted = { ...item, title: "最终登记的压力" };
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(detail)).mockRejectedValueOnce(new TypeError("网络中断"))
    .mockResolvedValueOnce(Response.json({ ...detail, finding: { ...detail.finding, status: "applied" }, items: [accepted], records: [{ requirement_id: "requirement", accepted_item: accepted }] }));
  vi.stubGlobal("fetch", fetcher);
  render(<ProductRfqProposal base="spaces/space" runId="run" onFailure={vi.fn()}/>);
  fireEvent.change(await screen.findByLabelText("核对说明"), { target: { value: "已核对" } });
  fireEvent.click(screen.getByRole("button", { name: "确认并登记需求草稿" }));
  await screen.findByRole("alert");
  fireEvent.click(screen.getByRole("button", { name: "查询确认结果" }));
  await screen.findByText(/已登记1项需求草稿/);
  expect(screen.getByLabelText("名称")).toHaveValue(accepted.title);
  expect(screen.queryByRole("button", { name: "重试原确认" })).not.toBeInTheDocument();
  expect(fetcher.mock.calls.filter(([url]) => String(url).endsWith("/rfq-ai-confirm"))).toHaveLength(1);
  expect(fetcher.mock.calls[2][0]).toContain("/rfq-ai-finding");
});
it("preserves edited content and the original retry while read-back is still pending", async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(detail)).mockResolvedValueOnce(Response.json({}, { status: 503 }))
    .mockResolvedValueOnce(Response.json(detail)).mockResolvedValueOnce(Response.json({ finding: { ...detail.finding, status: "applied" }, records: [] }));
  vi.stubGlobal("fetch", fetcher);
  render(<ProductRfqProposal base="spaces/space" runId="run" onFailure={vi.fn()}/>);
  fireEvent.change(await screen.findByLabelText("名称"), { target: { value: "人工核对值" } });
  fireEvent.change(screen.getByLabelText("核对说明"), { target: { value: "已核对" } });
  fireEvent.click(screen.getByRole("button", { name: "确认并登记需求草稿" }));
  await screen.findByRole("alert");
  fireEvent.click(screen.getByRole("button", { name: "查询确认结果" }));
  await screen.findByText(/尚未查到办理完成记录/);
  expect(screen.getByLabelText("名称")).toHaveValue("人工核对值");
  expect(screen.getByLabelText("名称")).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "重试原确认" }));
  await screen.findByText(/已登记0项需求草稿/);
  expect(fetcher.mock.calls[1][1]?.body).toBe(fetcher.mock.calls[3][1]?.body);
});
it.each([401, 403])("clears private candidate content when recovery returns %s", async status => {
  const onFailure = vi.fn();
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(detail)).mockResolvedValueOnce(Response.json({}, { status: 503 }))
    .mockResolvedValueOnce(Response.json({ detail: { message: "当前无权访问" } }, { status }));
  vi.stubGlobal("fetch", fetcher);
  render(<ProductRfqProposal base="spaces/space" runId="run" onFailure={onFailure}/>);
  fireEvent.change(await screen.findByLabelText("核对说明"), { target: { value: "已核对" } });
  fireEvent.click(screen.getByRole("button", { name: "确认并登记需求草稿" }));
  await screen.findByRole("alert");
  fireEvent.click(screen.getByRole("button", { name: "查询确认结果" }));
  await screen.findByText("当前无权访问");
  expect(onFailure).toHaveBeenCalledWith("当前无权访问");
  expect(screen.queryByText("Maximum pressure 120 kPa")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("名称")).not.toBeInTheDocument();
});
it("recovers a lost rejection even after write capability becomes disabled", async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(detail)).mockRejectedValueOnce(new TypeError("响应丢失"))
    .mockResolvedValueOnce(Response.json({ ...detail, finding: { ...detail.finding, status: "rejected" } }));
  vi.stubGlobal("fetch", fetcher);
  const onFailure = vi.fn();
  const view = render(<ProductRfqProposal base="spaces/space" runId="run" onFailure={onFailure}/>);
  fireEvent.change(await screen.findByLabelText("核对说明"), { target: { value: "原文不支持该要求" } });
  fireEvent.click(screen.getByRole("button", { name: "拒绝此批候选" }));
  await screen.findByRole("alert");
  view.rerender(<ProductRfqProposal base="spaces/space" runId="run" onFailure={onFailure} disabled/>);
  expect(screen.getByRole("button", { name: "重试原确认" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "查询确认结果" }));
  await screen.findByText("已拒绝，未登记需求。");
  expect(screen.queryByRole("button", { name: "重试原确认" })).not.toBeInTheDocument();
  expect(fetcher).toHaveBeenCalledTimes(3);
});
it.each(["different-finding", "different-digest", "unavailable"])("does not discard the original confirmation after a %s read-back", async scenario => {
  const result = scenario === "unavailable" ? Response.json({ detail: { message: "查询暂不可用" } }, { status: 503 }) : Response.json({ ...detail, finding: { ...detail.finding, status: "applied", ...(scenario === "different-finding" ? { id: "other" } : { proposed_digest: "c".repeat(64) }) } });
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(detail)).mockRejectedValueOnce(new TypeError("响应丢失"))
    .mockResolvedValueOnce(result).mockResolvedValueOnce(Response.json({ finding: { ...detail.finding, status: "applied" }, records: [] }));
  vi.stubGlobal("fetch", fetcher);
  render(<ProductRfqProposal base="spaces/space" runId="run" onFailure={vi.fn()}/>);
  fireEvent.change(await screen.findByLabelText("核对说明"), { target: { value: "已核对" } });
  fireEvent.click(screen.getByRole("button", { name: "确认并登记需求草稿" }));
  await screen.findByText("响应丢失");
  fireEvent.click(screen.getByRole("button", { name: "查询确认结果" }));
  await screen.findByText(scenario === "unavailable" ? "查询暂不可用" : "未找到原确认对应的候选，请保留当前页面，稍后查询原确认结果。");
  expect(screen.queryByText(/已登记0项需求草稿/)).not.toBeInTheDocument();
  expect(screen.getByLabelText("名称")).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "重试原确认" }));
  await screen.findByText(/已登记0项需求草稿/);
  expect(fetcher.mock.calls[1][1]?.body).toBe(fetcher.mock.calls[3][1]?.body);
});
