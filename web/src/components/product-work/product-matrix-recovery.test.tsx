import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ProductMatrixDispositions } from "./product-matrix-dispositions";
import { ProductMatrixOutcomes } from "./product-matrix-outcomes";
import { ProductMatrixHistory } from "./product-matrix-history";

const product = { id: "product", code: "P", name: "合成受限产品", product_line_id: "line" };
const kinds = ["disposition", "outcome"] as const;
type Kind = typeof kinds[number];
const labels = { disposition: { summary: "人工处置与实际跟进", refresh: "刷新来源与处置历史", retry: "按原请求重试核对处置", save: "保存具名处置" }, outcome: { summary: "实际落实、发布版本与核对结果", refresh: "刷新实际版本与结果", retry: "按原请求重试核对结果", save: "保存新的结果版本" } };
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

function setup(kind: Kind) {
  const state = { denied: false, failSave: false, failReadAfterSave: false, saved: false, digest: "old-digest", bodies: [] as Record<string, unknown>[] };
  const fetcher = vi.fn<typeof fetch>(async (url, init) => {
    const path = String(url);
    if (path.endsWith("-save")) {
      state.bodies.push(JSON.parse(String(init?.body)));
      if (state.failSave) { state.failSave = false; throw new TypeError("response lost"); }
      state.saved = true; return Response.json({ id: "receipt-id" });
    }
    if (state.denied) return Response.json({ detail: { message: "当前范围已撤权" } }, { status: 403 });
    if (state.saved && state.failReadAfterSave) throw new TypeError("history unreachable");
    if (path.endsWith("/evidence")) return Response.json({ items: [] });
    if (path.endsWith("/products")) return Response.json({ nodes: [], members: [] });
    if (path.endsWith("/matrix-dispositions")) return Response.json({ source: { digest: state.digest }, can_manage: true, items: [], products: [product], criteria: [{ key: "criterion", interpretation: "合成判据" }] });
    if (path.endsWith("/matrix-outcomes")) return Response.json({ source: { digest: state.digest, products: [product], options: [], work: null }, version: 0, can_record: true, items: [] });
    return Response.json({ members: [] });
  });
  vi.stubGlobal("fetch", fetcher);
  const view = render(kind === "disposition" ? <ProductMatrixDispositions base="spaces/s" recordId="record"/> : <ProductMatrixOutcomes base="spaces/s" dispositionId="disposition"/>);
  fireEvent.click(screen.getByText(labels[kind].summary));
  return { state, fetcher, view };
}

async function fill(kind: Kind) {
  fireEvent.click(await screen.findByLabelText("P · 合成受限产品"));
  if (kind === "disposition") {
    fireEvent.click(screen.getByLabelText("合成判据"));
    fireEvent.change(screen.getByLabelText("主题名称"), { target: { value: "合成处置" } });
    fireEvent.change(screen.getByLabelText("本次处置"), { target: { value: "retain" } });
    fireEvent.change(screen.getByLabelText("判断依据、取舍和保留限制"), { target: { value: "合成保留依据" } });
  } else {
    fireEvent.change(screen.getByLabelText("核对范围、落实说明及限制"), { target: { value: "合成进展" } });
    fireEvent.change(screen.getByLabelText("实际验证依据与原文位置说明"), { target: { value: "待补真实依据" } });
  }
}
function submit(kind: Kind) { fireEvent.submit(screen.getByRole("button", { name: labels[kind].save }).closest("form")!); }

it.each(kinds)("clears private %s records and drafts after explicit access denial", async kind => {
  const { state } = setup(kind); await fill(kind);
  state.denied = true;
  fireEvent.click(screen.getByRole("button", { name: labels[kind].refresh }));
  expect(await screen.findByRole("alert")).toHaveTextContent("当前范围已撤权");
  expect(screen.queryByLabelText("P · 合成受限产品")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: labels[kind].save })).not.toBeInTheDocument();
  state.denied = false;
  fireEvent.click(screen.getByRole("button", { name: labels[kind].refresh }));
  await screen.findByLabelText("P · 合成受限产品");
  expect(screen.getByLabelText(kind === "disposition" ? "主题名称" : "核对范围、落实说明及限制")).toHaveValue("");
});

it.each(kinds)("retries an uncertain %s with the exact original payload even after refreshing", async kind => {
  const { state } = setup(kind); await fill(kind); state.failSave = true;
  submit(kind); submit(kind);
  await screen.findByRole("button", { name: labels[kind].retry });
  expect(state.bodies).toHaveLength(1);
  expect(screen.getByRole("button", { name: labels[kind].save })).toBeDisabled();
  state.digest = "new-digest";
  fireEvent.click(screen.getByRole("button", { name: labels[kind].refresh }));
  await waitFor(() => expect(screen.getByRole("button", { name: labels[kind].retry })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: labels[kind].retry }));
  expect(await screen.findByRole("status")).toHaveTextContent("receipt-id");
  expect(state.bodies).toHaveLength(2);
  expect(state.bodies[1]).toEqual(state.bodies[0]);
  expect(state.bodies[1].expected_source_digest).toBe("old-digest");
});

it.each(kinds)("keeps a confirmed %s receipt when only history refresh fails", async kind => {
  const { state } = setup(kind); await fill(kind); state.failReadAfterSave = true; submit(kind);
  expect(await screen.findByRole("status")).toHaveTextContent("receipt-id");
  expect(screen.getByRole("alert")).toHaveTextContent("已保存，历史暂未刷新");
  expect(screen.queryByRole("button", { name: labels[kind].retry })).not.toBeInTheDocument();
  expect(state.bodies).toHaveLength(1);
});

it.each(kinds)("does not expose a previous scope after %s props change", async kind => {
  const { view } = setup(kind); await fill(kind);
  view.rerender(kind === "disposition" ? <ProductMatrixDispositions base="spaces/other" recordId="other"/> : <ProductMatrixOutcomes base="spaces/other" dispositionId="other"/>);
  expect(screen.queryByLabelText("P · 合成受限产品")).not.toBeInTheDocument();
});

it("clears saved matrix history on access denial", async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json({ items: [{ id: "r", series_id: "s", version: 1, title: "受限历史名称", reason: "私有原因", actor_name: "合成人", created_at: "2026-09-30T00:00:00Z" }], next_before_id: null })).mockResolvedValueOnce(Response.json({ detail: { message: "已撤权" } }, { status: 403 }));
  vi.stubGlobal("fetch", fetcher);
  render(<ProductMatrixHistory base="spaces/s" onRead={vi.fn()} onResume={vi.fn()}/>);
  fireEvent.click(screen.getByRole("button", { name: "查询 / 刷新历史" }));
  await screen.findByText("受限历史名称 · v1");
  fireEvent.click(screen.getByRole("button", { name: "查询 / 刷新历史" }));
  await screen.findByText("已撤权");
  expect(screen.queryByText("受限历史名称 · v1")).not.toBeInTheDocument();
});
