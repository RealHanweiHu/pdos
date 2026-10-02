import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { DefinitionInheritance } from "./definition-inheritance";
import type { Definition } from "./definitions";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const row = { id: "local", version: 3, payload_digest: "a".repeat(64), base_definition_id: "original", parent_updates: [{ source: { ref_id: "old-parent" }, accepted_paths: ["field/scenarios"], reason: "私有原接受理由" }] } as unknown as Definition;
const comparison = { base_definition_id: "original", target_definition_id: "new-parent", target_release_id: "release-2", target_revision: 2, comparison_digest: "b".repeat(64), changes: [{ path: "field/scenarios", base: "私有原父版", local: "私有本地内容", incoming: "私有新父版", conflict: true }] };
const show = (value: unknown) => <p>{String(value)}</p>;
function setup() {
  const state = { denied: "", loseResponse: false, calls: [] as { path: string; body: Record<string, unknown> }[] };
  const fetcher = vi.fn<typeof fetch>(async (url, init) => {
    const path = String(url);
    if (state.denied && path.endsWith(state.denied)) return Response.json({ detail: { message: "父版读取范围已撤权" } }, { status: 403 });
    if (path.endsWith("parent-comparison")) return Response.json(comparison);
    if (path.endsWith("parent-merge") || path.endsWith("derive")) {
      state.calls.push({ path, body: JSON.parse(String(init?.body)) });
      if (state.loseResponse) { state.loseResponse = false; throw new TypeError("response lost"); }
      return Response.json({ id: "child", product_name: "合成派生产品" });
    }
    return Response.json(row);
  });
  vi.stubGlobal("fetch", fetcher);
  const changed = vi.fn(), denied = vi.fn();
  const props = { item: row, base: "spaces/s", canDerive: true, canMerge: true, renderValue: show, onChanged: changed, onAccessDenied: denied };
  const view = render(<DefinitionInheritance {...props}/>);
  return { state, fetcher, changed, denied, props, view };
}
async function read() {
  fireEvent.click(screen.getByRole("button", { name: "比较父产品最新发布版" }));
  await screen.findByText("私有新父版");
}
async function select() {
  await read(); fireEvent.click(screen.getByRole("checkbox", { name: /使用场景/ }));
  fireEvent.change(screen.getByLabelText("接受变更的原因"), { target: { value: "合成人工选择" } });
}
function fill() {
  fireEvent.click(screen.getByRole("button", { name: "派生为新产品" }));
  fireEvent.change(screen.getByLabelText("新产品编号"), { target: { value: "CHILD" } });
  fireEvent.change(screen.getByLabelText("新产品名称"), { target: { value: "合成派生产品" } });
  fireEvent.change(screen.getByLabelText("派生原因"), { target: { value: "合成地区差异" } });
}

it.each(["parent-comparison", "parent-merge", "derive"])("clears private inherited fields and notifies the owning workspace on %s denial", async path => {
  const { state, denied } = setup(); await select();
  if (path === "derive") fill();
  state.denied = path;
  fireEvent.click(screen.getByRole("button", { name: path === "derive" ? "创建派生产品与定义草稿" : path === "parent-merge" ? "接受所选父版变更" : "比较父产品最新发布版" }));
  await screen.findByRole("alert");
  expect(screen.queryByText("私有新父版")).not.toBeInTheDocument();
  expect(screen.queryByText(/私有原接受理由/)).not.toBeInTheDocument();
  expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("新产品名称")).not.toBeInTheDocument();
  expect(denied).toHaveBeenCalledOnce();
});

it("retries an uncertain merge with its exact original selected paths, source and key after a newer comparison", async () => {
  const { state, fetcher, changed } = setup(); await select(); state.loseResponse = true;
  fireEvent.click(screen.getByRole("button", { name: "接受所选父版变更" }));
  await screen.findByRole("button", { name: "按原请求重试核对父版变更" });
  expect(screen.getByLabelText("接受变更的原因")).toBeDisabled();
  fetcher.mockResolvedValueOnce(Response.json({ ...comparison, target_release_id: "release-3", comparison_digest: "c".repeat(64) }));
  fireEvent.click(screen.getByRole("button", { name: "比较父产品最新发布版" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "按原请求重试核对父版变更" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "按原请求重试核对父版变更" }));
  await waitFor(() => expect(changed).toHaveBeenCalledOnce());
  expect(state.calls).toHaveLength(2); expect(state.calls[1].body).toEqual(state.calls[0].body);
  expect(state.calls[1].body).toMatchObject({ target_release_id: "release-2", accept_paths: ["field/scenarios"], expected_version: 3, comparison_digest: "b".repeat(64) });
});

it("locks a lost derivation request and retries its original product input exactly once", async () => {
  const { state } = setup(); fill(); state.loseResponse = true;
  fireEvent.click(screen.getByRole("button", { name: "创建派生产品与定义草稿" }));
  fireEvent.click(screen.getByRole("button", { name: "创建派生产品与定义草稿" }));
  await screen.findByRole("button", { name: "按原请求重试核对派生" });
  expect(state.calls).toHaveLength(1); expect(screen.getByLabelText("新产品编号")).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "按原请求重试核对派生" }));
  await screen.findByRole("status");
  expect(state.calls).toHaveLength(2); expect(state.calls[1].body).toEqual(state.calls[0].body);
});

it("keeps a confirmed merge receipt when only the parent refresh callback fails", async () => {
  const { state, props, view } = setup();
  view.rerender(<DefinitionInheritance {...props} onChanged={() => { throw new Error("refresh failed"); }}/>);
  await select(); fireEvent.click(screen.getByRole("button", { name: "接受所选父版变更" }));
  expect(await screen.findByRole("status")).toHaveTextContent("已接受到定义草稿");
  expect(screen.getByRole("alert")).toHaveTextContent("已保存，页面暂未刷新");
  expect(screen.queryByRole("button", { name: "按原请求重试核对父版变更" })).not.toBeInTheDocument();
  expect(state.calls).toHaveLength(1);
});

it("clears old private fields and drafts immediately after the record scope changes", async () => {
  const { props, view } = setup(); await read(); fill();
  view.rerender(<DefinitionInheritance {...props} base="spaces/other" item={{ ...row, id: "other" }}/>);
  expect(screen.queryByText("私有新父版")).not.toBeInTheDocument();
  expect(screen.queryByDisplayValue("合成派生产品")).not.toBeInTheDocument();
});

it("ignores a late merge receipt when the owning workspace invalidates its access", async () => {
  const { props, view, fetcher, changed } = setup(); let allowed = true;
  view.rerender(<DefinitionInheritance {...props} captureAccess={() => () => allowed}/>);
  await select(); let resolve!: (value: Response) => void;
  fetcher.mockImplementationOnce(() => new Promise<Response>(done => { resolve = done; }));
  fireEvent.click(screen.getByRole("button", { name: "接受所选父版变更" }));
  allowed = false; resolve(Response.json({}));
  await new Promise(done => setTimeout(done, 20));
  expect(changed).not.toHaveBeenCalled();
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});

it("rechecks source permission before restoring the panel with cleared private inputs", async () => {
  const { state } = setup(); await read(); state.denied = "parent-comparison";
  fireEvent.click(screen.getByRole("button", { name: "比较父产品最新发布版" }));
  await screen.findByRole("alert"); state.denied = "";
  fireEvent.click(screen.getByRole("button", { name: "重新核对读取范围" }));
  await screen.findByRole("button", { name: "比较父产品最新发布版" });
  expect(screen.queryByText("私有新父版")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("接受变更的原因")).not.toBeInTheDocument();
});
