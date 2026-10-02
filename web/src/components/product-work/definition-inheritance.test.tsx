import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { DefinitionInheritance } from "./definition-inheritance";
import type { Definition } from "./definitions";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const row = { id: "local", version: 3, payload_digest: "a".repeat(64), base_definition_id: "original", parent_updates: [] } as unknown as Definition;
const comparison = {
  base_definition_id: "original", target_definition_id: "new-parent", target_release_id: "release-2", target_revision: 2,
  comparison_digest: "b".repeat(64), changes: [
    { path: "items/pressure", base: "100 kPa", local: "110 kPa", incoming: "120 kPa", conflict: true },
    { path: "field/scenarios", base: "原场景", local: "本地场景", incoming: "父版新场景", conflict: true },
  ],
};
const show = (value: unknown) => <p>{String(value)}</p>;

it("compares three versions and accepts only selected changes with the displayed source digest", async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(comparison)).mockResolvedValueOnce(Response.json({}));
  vi.stubGlobal("fetch", fetcher); const changed = vi.fn();
  render(<DefinitionInheritance item={row} base="spaces/space" canDerive={false} canMerge renderValue={show} onChanged={changed}/>);
  fireEvent.click(screen.getByRole("button", { name: "比较父产品最新发布版" }));
  await screen.findByText("120 kPa");
  expect(screen.getByText("100 kPa")).toBeInTheDocument(); expect(screen.getByText("110 kPa")).toBeInTheDocument();
  expect(screen.getAllByRole("checkbox").every(input => !(input as HTMLInputElement).checked)).toBe(true);
  fireEvent.click(screen.getByRole("checkbox", { name: /规格 pressure/ }));
  fireEvent.change(screen.getByLabelText("接受变更的原因"), { target: { value: "只采用压力规格" } });
  fireEvent.click(screen.getByRole("button", { name: "接受所选父版变更" }));
  await waitFor(() => expect(changed).toHaveBeenCalledOnce());
  const body = JSON.parse(String(fetcher.mock.calls[1][1]?.body));
  expect(body.accept_paths).toEqual(["items/pressure"]);
  expect(body.target_definition_id).toBe("new-parent"); expect(body.target_release_id).toBe("release-2");
  expect(body.comparison_digest).toBe(comparison.comparison_digest); expect(body.payload_digest).toBe(row.payload_digest);
});

it("creates a separate product with one stable retry key and links to the new definition", async () => {
  const fetcher = vi.fn<typeof fetch>().mockRejectedValueOnce(new Error("网络响应中断"))
    .mockResolvedValueOnce(Response.json({ id: "child", product_name: "地区版" }));
  vi.stubGlobal("fetch", fetcher);
  render(<DefinitionInheritance item={{ ...row, base_definition_id: null }} base="spaces/space" canDerive canMerge={false} renderValue={show} onChanged={vi.fn()}/>);
  fireEvent.click(screen.getByRole("button", { name: "派生为新产品" }));
  fireEvent.change(screen.getByLabelText("新产品编号"), { target: { value: "REGION-1" } });
  fireEvent.change(screen.getByLabelText("新产品名称"), { target: { value: "地区版" } });
  fireEvent.change(screen.getByLabelText("派生原因"), { target: { value: "地区规格差异" } });
  fireEvent.click(screen.getByRole("button", { name: "创建派生产品与定义草稿" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("网络响应中断");
  fireEvent.click(screen.getByRole("button", { name: "按原请求重试核对派生" }));
  expect(await screen.findByRole("link", { name: "打开新产品定义，核对差异与规格" })).toHaveAttribute("href", "/product-work?space=space&tab=definitions#definition-child");
  expect(fetcher.mock.calls[0][1]?.body).toBe(fetcher.mock.calls[1][1]?.body);
});

it("shows parent comparison without enabling changes to a published definition", async () => {
  vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockResolvedValue(Response.json(comparison)));
  render(<DefinitionInheritance item={row} base="spaces/space" canDerive={false} canMerge={false} renderValue={show} onChanged={vi.fn()}/>);
  fireEvent.click(screen.getByRole("button", { name: "比较父产品最新发布版" }));
  await screen.findByText("120 kPa");
  for (const box of screen.getAllByRole("checkbox")) expect(box).toBeDisabled();
  expect(screen.queryByRole("button", { name: "接受所选父版变更" })).not.toBeInTheDocument();
});
