import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { CompetitorWorkspace } from "./competitors";
import { MarketSegments } from "./market-segments";
import type { ProductCatalog, Workspace } from "./product-work-api";

const id = "11111111-1111-4111-8111-111111111111";
const fact = { text: "历史原始依据", fact_kind: "hypothesis", sources: [] };
const common = { id, is_latest: false, version: 1, product_line_id: null, source_warnings: [], revision_reason: "历史核对", created_at: "2026-09-01T00:00:00Z" };
const competitor = { ...common, brand: "合成历史品牌", model: "旧型号", variant: "A", metrics: [], price_quote: null, identity_sources: [], certifications: [], observed_on: "2026-09-01" };
const segment = { ...common, title: "历史细分", job_to_be_done: fact, target_users: [], customer_problems: [], use_environments: [], buying_criteria: [], unmet_needs: [], outcome: { statement: "历史目标", sources: [] }, sizing_result: { estimates: {}, unknown_parameters: [], hypothesis_parameters: [] }, sizing_inputs: Object.fromEntries(["potential_customers", "annual_units_per_customer", "unit_price", "serviceable_share", "obtainable_share"].map(key => [key, { lower: null, upper: null, basis: fact }])) };
const props = { base: "spaces/space", workspace: { can_contribute: false } as Workspace, catalog: { nodes: [], line_access: {} } as unknown as ProductCatalog, evidence: [] };
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); window.history.replaceState(null, "", "/"); });

it("shows the server's later-revision warning while retaining selected comparison values", async () => {
  const a = { ...competitor, is_latest: true };
  const b = { ...a, id: "22222222-2222-4222-8222-222222222222", model: "B型号" };
  const warning = "旧型号的 v1 观察已有后续修订，请重核参数；本次仍使用所选历史版本";
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json({ items: [a, b] })).mockResolvedValueOnce(Response.json({
    observations: [{ ...a, is_latest: false }, b], note: "不自动排名", as_of: "2026-09-30T00:00:00Z",
    rows: [{ key: "pressure", label: "压力", kind: "metric", status: "review_needed", reasons: [warning], cells: [{ key: "pressure", number: "100", unit: "kPa", nature: "claimed", conditions: "25℃", method: "同一声明口径", source_refs: [] }, null] }],
  }));
  vi.stubGlobal("fetch", fetcher);
  render(<CompetitorWorkspace {...props}/>);
  fireEvent.click(await screen.findByLabelText(/合成历史品牌 · 旧型号/));
  fireEvent.click(screen.getByLabelText(/合成历史品牌 · B型号/));
  fireEvent.click(screen.getByRole("button", { name: "比较所选 2 条观察" }));
  expect(await screen.findByText(warning)).toBeVisible();
  expect(screen.getByText("需复核来源或范围")).toBeVisible();
  expect(screen.getByText("100 kPa")).toBeVisible();
  expect(screen.queryByText("录入条件一致")).not.toBeInTheDocument();
  expect(JSON.parse(String(fetcher.mock.calls[1][1]?.body))).toEqual({ observation_ids: [a.id, b.id] });
});

it.each(["competitor", "segment"])("opens a linked historical %s outside the recent list", async kind => {
  window.history.replaceState(null, "", `/product-work?space=space#${kind}-${id}`);
  const scroll = vi.fn();
  vi.stubGlobal("HTMLElement", window.HTMLElement);
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", { configurable: true, value: scroll });
  const row = kind === "competitor" ? competitor : segment;
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json({ items: [] })).mockResolvedValueOnce(Response.json(row));
  vi.stubGlobal("fetch", fetcher);
  render(kind === "competitor" ? <CompetitorWorkspace {...props}/> : <MarketSegments {...props}/>);
  await waitFor(() => expect(document.getElementById(`${kind}-${id}`)).toBeInTheDocument());
  expect(screen.getByLabelText(kind === "competitor" ? "显示历史修订" : "显示历史版本")).toBeChecked();
  expect(fetcher.mock.calls[1][0]).toBe(`/api/product-work/spaces/space/${kind === "competitor" ? "competitors" : "market-segments"}/${id}`);
  expect(scroll).toHaveBeenCalledWith({ block: "start" });
  expect(screen.queryByRole("button", { name: "追加修订" })).not.toBeInTheDocument();
});

it.each(["competitor", "segment"])("shows a denied %s link without claiming it was opened", async kind => {
  window.history.replaceState(null, "", `/product-work?space=space#${kind}-${id}`);
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json({ items: [] })).mockResolvedValueOnce(Response.json({ detail: { message: "记录不存在或不可访问" } }, { status: 403 }));
  vi.stubGlobal("fetch", fetcher);
  render(kind === "competitor" ? <CompetitorWorkspace {...props}/> : <MarketSegments {...props}/>);
  expect(await screen.findByRole("alert")).toHaveTextContent("记录不存在或不可访问");
  expect(document.getElementById(`${kind}-${id}`)).not.toBeInTheDocument();
});
