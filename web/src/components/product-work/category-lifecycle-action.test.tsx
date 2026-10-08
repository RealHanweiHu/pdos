import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { CategoryLifecycleAction } from "./category-lifecycle-action";
import type { Space } from "./product-work-api";

const space = { id: "category-one", title: "汽车充气泵", lifecycle: "draft", version: 3, payload_digest: "snapshot-3" } as Space;
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("requires confirmation and cancellation makes no write", () => {
  const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
  render(<CategoryLifecycleAction space={space} disabled={false} onChanged={vi.fn()} onPendingChange={vi.fn()}/>);
  fireEvent.click(screen.getByRole("button", { name: "删除品类 汽车充气泵" }));
  expect(screen.getByRole("dialog")).toHaveTextContent("资料、提案及版本历史会保留");
  expect(fetcher).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "取消" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(fetcher).not.toHaveBeenCalled();
});

it("keeps the original removal request after an uncertain result and notifies only on success", async () => {
  const changed = vi.fn(), pending = vi.fn();
  const fetcher = vi.fn().mockRejectedValueOnce(new Error("连接中断，结果暂未确认"))
    .mockResolvedValueOnce(Response.json({ ...space, lifecycle: "archived", version: 4 }));
  vi.stubGlobal("fetch", fetcher);
  render(<CategoryLifecycleAction space={space} disabled={false} onChanged={changed} onPendingChange={pending}/>);
  fireEvent.click(screen.getByRole("button", { name: "删除品类 汽车充气泵" }));
  fireEvent.click(screen.getByRole("button", { name: "确认删除" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("连接中断");
  expect(changed).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "取消" }));
  fireEvent.click(screen.getByRole("button", { name: "删除品类 汽车充气泵" }));
  fireEvent.click(screen.getByRole("button", { name: "确认删除" }));
  await waitFor(() => expect(changed).toHaveBeenCalledWith(expect.objectContaining({ lifecycle: "archived" })));
  expect(fetcher.mock.calls[1][1].body).toBe(fetcher.mock.calls[0][1].body);
  expect(JSON.parse(fetcher.mock.calls[0][1].body)).toMatchObject({ expected_version: 3, payload_digest: "snapshot-3", lifecycle: "archived" });
  expect(pending.mock.calls).toEqual([[true], [false], [true], [false]]);
});

it("shows the server's refusal without hiding the category", async () => {
  const changed = vi.fn();
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ detail: { message: "品类仍有未结束工作，请先完成或明确取消" } }, { status: 409 })));
  render(<CategoryLifecycleAction space={space} disabled={false} onChanged={changed} onPendingChange={vi.fn()}/>);
  fireEvent.click(screen.getByRole("button", { name: "删除品类 汽车充气泵" }));
  fireEvent.click(screen.getByRole("button", { name: "确认删除" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("未结束工作");
  expect(screen.getByRole("dialog")).toBeInTheDocument();
  expect(changed).not.toHaveBeenCalled();
});

it("restores an archived category and respects an existing pending operation", async () => {
  const changed = vi.fn();
  const fetcher = vi.fn().mockResolvedValue(Response.json({ ...space, lifecycle: "active", version: 5 }));
  vi.stubGlobal("fetch", fetcher);
  const view = render(<CategoryLifecycleAction space={{ ...space, lifecycle: "archived" }} disabled onChanged={changed} onPendingChange={vi.fn()}/>);
  expect(screen.getByRole("button", { name: "恢复品类 汽车充气泵" })).toBeDisabled();
  view.rerender(<CategoryLifecycleAction space={{ ...space, lifecycle: "archived" }} disabled={false} onChanged={changed} onPendingChange={vi.fn()}/>);
  fireEvent.click(screen.getByRole("button", { name: "恢复品类 汽车充气泵" }));
  fireEvent.click(screen.getByRole("button", { name: "确认恢复" }));
  await waitFor(() => expect(changed).toHaveBeenCalled());
  expect(JSON.parse(fetcher.mock.calls[0][1].body).lifecycle).toBe("active");
});
