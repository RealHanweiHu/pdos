import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ResourceReallocations } from "./resource-reallocations";

const projectId = "project-a";
const allocation = {
  id: "adjustment", title: "台架改期", created_at: "2026-10-01T09:00:00Z", payload_digest: "reviewed",
  project_count: 2, approved_count: 0, status: "pending", can_decide: true, can_withdraw: false, can_apply: false,
  parts: [{ project_id: projectId, body: { project: { id: projectId, name: "项目 A", owner_name: "负责人 A" },
    items: [], conflicts: [], unknown: [], capacity_clear: true, reason: "试验延期" } }],
  decisions: [], application: null,
};
const current = { allocation_id: allocation.id, payload_digest: allocation.payload_digest, sources_current: true, capacity_clear: true, blockers: [] };
const page = (items = [allocation], can_propose = false) => ({ items, next: null, can_propose });
const responseError = (message: string, status = 409) => Response.json({ detail: { message } }, { status });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

async function open() {
  fireEvent.click(screen.getByRole("button", { name: "跨项目资源改期与接续" }));
  await screen.findByText(/台架改期/);
  fireEvent.change(screen.getByLabelText("本次确认／处置说明"), { target: { value: "已核对项目影响" } });
  fireEvent.click(screen.getByLabelText("已核对所示版本、原预约、调整后窗口及影响"));
}

describe("current resource adjustment review", () => {
  it("keeps approval disabled for stale policies while rejection remains available", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(page()))
      .mockResolvedValueOnce(Response.json({ ...current, sources_current: false, capacity_clear: false, blockers: ["优先级政策已变化，请重新提出"] }));
    vi.stubGlobal("fetch", fetcher);
    render(<ResourceReallocations projectId={projectId} onChanged={async () => {}} />);
    await open();
    expect(screen.getByRole("button", { name: "同意本项目调整" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "拒绝本项目调整" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "核对当前政策与占用" }));
    await screen.findByText("优先级政策已变化，请重新提出");
    fireEvent.click(screen.getByLabelText("已核对所示版本、原预约、调整后窗口及影响"));
    expect(screen.getByRole("button", { name: "同意本项目调整" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "拒绝本项目调整" })).toBeEnabled();
    expect(JSON.parse(String(fetcher.mock.calls[1][1]?.body))).toEqual({ allocation_id: allocation.id, expected_digest: allocation.payload_digest });
  });

  it("rechecks after a failed mutation and retries the same request without changing the reviewed input", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(page()))
      .mockResolvedValueOnce(Response.json(current)).mockResolvedValueOnce(responseError("响应未确认", 503))
      .mockResolvedValueOnce(Response.json(current)).mockResolvedValueOnce(Response.json({ id: "receipt" }))
      .mockResolvedValueOnce(responseError("回执刷新暂不可用", 503));
    vi.stubGlobal("fetch", fetcher);
    render(<ResourceReallocations projectId={projectId} onChanged={async () => {}} />);
    await open();
    for (let attempt = 0; attempt < 2; attempt++) {
      fireEvent.click(screen.getByRole("button", { name: "核对当前政策与占用" }));
      await screen.findByText("当前来源与容量通过核对；提交时再次复核。");
      fireEvent.click(screen.getByLabelText("已核对所示版本、原预约、调整后窗口及影响"));
      fireEvent.click(screen.getByRole("button", { name: "同意本项目调整" }));
      await screen.findByText(attempt === 0 ? "响应未确认" : "回执刷新暂不可用");
    }
    expect(JSON.parse(String(fetcher.mock.calls[2][1]?.body))).toEqual(JSON.parse(String(fetcher.mock.calls[4][1]?.body)));
    expect(screen.getByRole("status")).toHaveTextContent("本次处置已记录");
    expect(screen.queryByRole("button", { name: "同意本项目调整" })).not.toBeInTheDocument();
  });

  it("refuses a malformed or different-version review and clears records after access is revoked", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(page()))
      .mockResolvedValueOnce(Response.json({ ...current, payload_digest: "different" }))
      .mockResolvedValueOnce(responseError("当前无权读取", 403));
    vi.stubGlobal("fetch", fetcher);
    render(<ResourceReallocations projectId={projectId} onChanged={async () => {}} />);
    await open();
    fireEvent.click(screen.getByRole("button", { name: "核对当前政策与占用" }));
    await screen.findByText("当前核对结果不完整，请重新读取");
    expect(screen.getByRole("button", { name: "同意本项目调整" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "刷新调整记录" }));
    await screen.findByText("当前无权读取");
    expect(screen.queryByText(/台架改期/)).not.toBeInTheDocument();
  });

  it("resets the prior project's choices when moving to another project", async () => {
    vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockResolvedValue(Response.json(page())));
    const rendered = render(<ResourceReallocations projectId={projectId} onChanged={async () => {}} />);
    await open();
    rendered.rerender(<ResourceReallocations projectId="project-b" onChanged={async () => {}} />);
    expect(screen.queryByText(/台架改期/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "跨项目资源改期与接续" })).toBeEnabled();
  });

  it("applies only a currently checked version and then opens the actual reservation receipt", async () => {
    const ready = { ...allocation, can_decide: false, can_apply: true, status: "ready", approved_count: 2 };
    const applied = { ...ready, can_apply: false, status: "applied", application: { items: [
      { project_id: projectId, previous_reservation_id: "before", reservation_id: "after" },
    ] } };
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json({ ...page(), items: [ready] }))
      .mockResolvedValueOnce(Response.json(current)).mockResolvedValueOnce(Response.json({ id: "applied" }))
      .mockResolvedValueOnce(Response.json({ ...page(), items: [applied] }));
    vi.stubGlobal("fetch", fetcher);
    const onChanged = vi.fn(async () => {});
    render(<ResourceReallocations projectId={projectId} onChanged={onChanged} />);
    await open();
    expect(screen.getByRole("button", { name: "独立应用整批预约调整" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "核对当前政策与占用" }));
    await screen.findByText("当前来源与容量通过核对；提交时再次复核。");
    fireEvent.click(screen.getByLabelText("已核对所示版本、原预约、调整后窗口及影响"));
    fireEvent.click(screen.getByRole("button", { name: "独立应用整批预约调整" }));
    expect(await screen.findByRole("link", { name: "查看应用后的实际预约" })).toHaveAttribute("href", `/projects?project=${projectId}&tab=overview&resource_reservation_id=after#resource-reservations`);
    expect(screen.queryByRole("button", { name: "独立应用整批预约调整" })).not.toBeInTheDocument();
    expect(JSON.parse(String(fetcher.mock.calls[2][1]?.body))).toMatchObject({ allocation_id: allocation.id, expected_digest: allocation.payload_digest });
    expect(onChanged).toHaveBeenCalledOnce();
  });
});

describe("adjustment proposal recovery", () => {
  it("keeps request identity for retries, renews it for edits, and preserves the successful save if refresh fails", async () => {
    const options = [projectId, "project-b"].map((id, index) => ({
      id: `reservation-${index}`, project_id: id, project_name: index === 0 ? "项目 A" : "项目 B",
      node_id: `node-${index}`, state: "proposed", capacity_version_id: "capacity",
      window_start: "2026-11-01T01:00:00-08:00", window_end: "2026-11-01T02:00:00-08:00",
      parallel_units: "1", occupancy_policy: "through_waiting", basis: "原申请依据", payload_digest: `original-${index}`,
    }));
    const previews: Record<string, unknown>[] = [], submissions: Record<string, unknown>[] = [];
    let reads = 0;
    const fetcher = vi.fn<typeof fetch>().mockImplementation(async (url, init) => {
      const path = String(url);
      if (path === "/api/planning/resources") return Response.json({ items: [{ id: "resource", name: "台架", capacity: { id: "capacity", version: 1 } }] });
      if (path.includes("resource-reallocation-options")) return Response.json({ items: options, next: null });
      if (path.includes("resource-reallocation-preview")) {
        previews.push(JSON.parse(String(init?.body)));
        return Response.json({ preview_digest: previews.length > 2 ? "policy-recalculated" : "preview", snapshot: { projects: [], items: [], conflicts: [], unknown: [], capacity_clear: true } });
      }
      if (init?.method === "POST") {
        submissions.push(JSON.parse(String(init.body)));
        return submissions.length < 4 ? responseError("结果未确认", 503) : Response.json({ id: "saved-adjustment" });
      }
      return ++reads === 1 ? Response.json(page([], true)) : responseError("历史刷新失败", 503);
    });
    vi.stubGlobal("fetch", fetcher);
    render(<ResourceReallocations projectId={projectId} onChanged={async () => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "跨项目资源改期与接续" }));
    await screen.findByText("提出跨项目改期／接续方案");
    fireEvent.change(screen.getByLabelText("查找原资源"), { target: { value: "resource" } });
    fireEvent.click(screen.getByRole("button", { name: "查找实际预约" }));
    await screen.findByLabelText(/项目 A.*待确认/);
    fireEvent.click(screen.getByLabelText(/项目 A.*待确认/));
    fireEvent.click(screen.getByLabelText(/项目 B.*待确认/));
    fireEvent.change(screen.getByLabelText("方案标题"), { target: { value: "初次方案" } });
    fireEvent.change(screen.getByLabelText("调整目的与共同处置说明"), { target: { value: "继续试验" } });
    for (const field of screen.getAllByLabelText("本项目的时间、质量、费用影响及后续处置")) fireEvent.change(field, { target: { value: "影响已说明" } });
    fireEvent.click(screen.getByRole("button", { name: "预览整批调整后的容量" }));
    await screen.findByLabelText("已核对此版本，提交各受影响项目具名确认");
    for (let attempt = 0; attempt < 2; attempt++) {
      fireEvent.click(screen.getByLabelText("已核对此版本，提交各受影响项目具名确认"));
      fireEvent.click(screen.getByRole("button", { name: "保存调整方案" }));
      await screen.findByText("结果未确认");
      // Confirmation remains checked after an unknown response; toggle it back below.
      if (attempt === 0) fireEvent.click(screen.getByLabelText("已核对此版本，提交各受影响项目具名确认"));
    }
    expect(submissions[0]).toEqual(submissions[1]);
    fireEvent.change(screen.getByLabelText("方案标题"), { target: { value: "修订方案" } });
    fireEvent.click(screen.getByRole("button", { name: "预览整批调整后的容量" }));
    await screen.findByLabelText("已核对此版本，提交各受影响项目具名确认");
    fireEvent.click(screen.getByLabelText("已核对此版本，提交各受影响项目具名确认"));
    fireEvent.click(screen.getByRole("button", { name: "保存调整方案" }));
    await waitFor(() => expect(submissions).toHaveLength(3));
    await screen.findByText("结果未确认");
    expect(submissions[0].request_id).not.toEqual(submissions[2].request_id);
    fireEvent.click(screen.getByRole("button", { name: "预览整批调整后的容量" }));
    await screen.findByLabelText("已核对此版本，提交各受影响项目具名确认");
    fireEvent.click(screen.getByLabelText("已核对此版本，提交各受影响项目具名确认"));
    fireEvent.click(screen.getByRole("button", { name: "保存调整方案" }));
    await waitFor(() => expect(submissions).toHaveLength(4));
    expect(submissions[2].title).toEqual(submissions[3].title);
    expect(submissions[2].request_id).not.toEqual(submissions[3].request_id);
    expect(submissions[3].expected_preview_digest).toBe("policy-recalculated");
    const firstItems = previews[0].items as { target: { window_start: string; window_end: string } }[];
    expect(firstItems[0].target.window_start).toBe(options[0].window_start);
    expect(firstItems[0].target.window_end).toBe(options[0].window_end);
    await screen.findByText("历史刷新失败");
    expect(screen.getByRole("status")).toHaveTextContent("调整方案已保存，回执 saved-adjustment");
    expect(screen.getByRole("button", { name: "刷新调整记录" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "保存调整方案" })).not.toBeInTheDocument();
  });
});
