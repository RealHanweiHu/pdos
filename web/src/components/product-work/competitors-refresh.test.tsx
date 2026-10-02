import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { CompetitorWorkspace, type Observation } from "./competitors";
import type { ProductCatalog, Workspace } from "./product-work-api";
const kinds = ["direct", "indirect", "emerging", "substitute"];
const rows: Observation[] = kinds.map((competitor_kind, index) => ({ id: `record-${index}`, series_id: `series-${index}`, version: 1, product_line_id: null, brand: "品牌", model: String.fromCharCode(65 + index), variant: "基本型", competitor_kind, region: "同地区", channel: "同渠道", configuration: "同配置", lifecycle: "available", observed_on: "2026-09-30", identity_sources: [], metrics: [{ key: "pressure", label: "压力", number: "100", text: null, unit: "kPa", nature: "measured", conditions: "25℃", method: "同方法", source_refs: [], missing_reason: null }], price_quote: null, certifications: [], notes: "", revision_reason: "首次观察", source_warnings: [], is_latest: true }));
const props = { base: "spaces/space", workspace: { can_contribute: false } as Workspace, catalog: { nodes: [], line_access: {} } as unknown as ProductCatalog, evidence: [] };
function matrix(status = "comparable") { return { observations: rows.slice(0, 2), rows: [{ key: "pressure", label: "压力", kind: "metric", status, reasons: status === "review_needed" ? ["A v1已有后续修订，请重核参数"] : [], cells: rows.slice(0, 2).map(row => row.metrics[0]) }], note: "不自动排名", as_of: "2026-09-30T00:00:00Z" }; }
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done; }); return { promise, resolve }; }
async function compare() { await screen.findByText("直接竞品 · 配置：同配置"); const boxes = screen.getAllByRole("checkbox"); fireEvent.click(boxes[1]); fireEvent.click(boxes[2]); fireEvent.click(screen.getByRole("button", { name: "比较所选 2 条观察" })); await screen.findByText("录入条件一致"); }
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
it("refreshes the original historical matrix after an external parameter revision and preserves its values", async () => {
  const newer = { ...rows[0], id: "record-new", version: 2, metrics: [{ ...rows[0].metrics[0], number: "110" }] };
  const revised = matrix("review_needed"); revised.observations = [{ ...rows[0], is_latest: false }, rows[1]];
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json({ items: rows })).mockResolvedValueOnce(Response.json(matrix())).mockResolvedValueOnce(Response.json({ items: [newer, { ...rows[0], is_latest: false }, ...rows.slice(1)] })).mockResolvedValueOnce(Response.json(revised));
  vi.stubGlobal("fetch", fetcher); render(<CompetitorWorkspace {...props}/>); await compare(); fireEvent.click(screen.getByRole("button", { name: "刷新" }));
  await screen.findByText("A v1已有后续修订，请重核参数"); const comparison = within(screen.getByRole("region", { name: "竞品比较矩阵" })); expect(comparison.getAllByText("100 kPa")).toHaveLength(2); expect(comparison.queryByText("110 kPa")).not.toBeInTheDocument(); expect(comparison.getByText("需复核来源或范围")).toBeInTheDocument(); expect(JSON.parse(String(fetcher.mock.calls[3][1]?.body))).toEqual({ observation_ids: ["record-0", "record-1"] });
});
it.each(["list", "comparison"])("preserves a visibly unverified matrix after an uncertain %s refresh and recovers on the next refresh", async stage => {
  let refreshFailed = false;
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async (url, init) => {
    if (fetcher.mock.calls.length > 2 && !refreshFailed && (stage === "list" ? init?.method === "GET" : String(url).endsWith("/competitor-comparison"))) { refreshFailed = true; return Response.json({ detail: { message: "刷新暂不可用" } }, { status: 503 }); }
    return Response.json(init?.method === "GET" ? { items: rows } : matrix());
  });
  vi.stubGlobal("fetch", fetcher); render(<CompetitorWorkspace {...props}/>); await compare(); fireEvent.click(screen.getByRole("button", { name: "刷新" })); await screen.findByText("刷新暂不可用");
  const comparison = within(screen.getByRole("region", { name: "竞品比较矩阵" })); expect(comparison.getByText(/当前矩阵待重新核对/)).toBeInTheDocument(); expect(comparison.getAllByText("100 kPa")).toHaveLength(2); expect(comparison.queryByText("录入条件一致")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "刷新" })); await screen.findByText("录入条件一致"); expect(screen.queryByText(/当前矩阵待重新核对/)).not.toBeInTheDocument();
});
it("keeps the matrix's original IDs when the next comparison selection has changed", async () => {
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async (_, init) => Response.json(init?.method === "GET" ? { items: rows } : matrix("comparable")));
  vi.stubGlobal("fetch", fetcher); render(<CompetitorWorkspace {...props}/>); await compare();
  const boxes = screen.getAllByRole("checkbox"); fireEvent.click(boxes[1]); fireEvent.click(boxes[3]); expect(screen.getByRole("region", { name: "竞品比较矩阵" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "刷新" })); await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(4)); expect(JSON.parse(String(fetcher.mock.calls[3][1]?.body))).toEqual({ observation_ids: ["record-0", "record-1"] });
});
it("shows all four competitor roles to a read-only member in cards and the matrix", async () => {
  const result = matrix(); result.observations = rows;
  result.rows = [{ ...result.rows[0], cells: rows.map(row => row.metrics[0]) }];
  vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json({ items: rows })).mockResolvedValueOnce(Response.json(result)));
  render(<CompetitorWorkspace {...props}/>); await compare();
  for (const label of ["直接竞品", "间接竞品", "新兴竞品", "替代方案"]) { expect(screen.getByText(`${label} · 配置：同配置`)).toBeInTheDocument(); expect(within(screen.getByRole("region", { name: "竞品比较矩阵" })).getByText(label)).toBeInTheDocument(); }
  expect(screen.queryByRole("button", { name: "记录竞品观察" })).not.toBeInTheDocument();
});
it.each([401, 403])("clears the private matrix and observations after refresh denial %s", async status => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json({ items: rows })).mockResolvedValueOnce(Response.json(matrix())).mockResolvedValueOnce(Response.json({ items: rows })).mockResolvedValueOnce(Response.json({ detail: { message: "无权读取这些来源" } }, { status }));
  vi.stubGlobal("fetch", fetcher); render(<CompetitorWorkspace {...props}/>); await compare(); fireEvent.click(screen.getByRole("button", { name: "刷新" })); await screen.findByText("无权读取这些来源"); expect(screen.queryByRole("region", { name: "竞品比较矩阵" })).not.toBeInTheDocument(); expect(screen.queryByText("直接竞品 · 配置：同配置")).not.toBeInTheDocument();
});
it("drops a late rechecked matrix when the visible scope changes", async () => {
  const pending = deferred<Response>(); const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json({ items: rows })).mockResolvedValueOnce(Response.json(matrix())).mockResolvedValueOnce(Response.json({ items: rows })).mockReturnValueOnce(pending.promise);
  vi.stubGlobal("fetch", fetcher); render(<CompetitorWorkspace {...props}/>); await compare(); fireEvent.click(screen.getByRole("button", { name: "刷新" })); await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(4)); fireEvent.change(screen.getByLabelText("范围"), { target: { value: "" } }); await act(async () => pending.resolve(Response.json(matrix("review_needed")))); expect(screen.queryByRole("region", { name: "竞品比较矩阵" })).not.toBeInTheDocument(); expect(screen.getByRole("button", { name: "刷新" })).toBeEnabled();
});
