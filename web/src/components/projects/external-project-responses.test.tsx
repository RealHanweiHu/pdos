import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ExternalProjectResponses } from "./external-project-responses";

const projectId = "88888888-8888-4888-8888-888888888888";
const signoffId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const sampleId = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const updatedAt = "2026-10-01T09:00:00Z";

function signoff(overrides: Record<string, unknown> = {}) {
  return {
    id: signoffId, project_id: projectId, audience: "customer", title: "外观样机确认",
    status: "pending", sample_ids: [sampleId], updated_at: updatedAt,
    due_date: "2026-10-09", responded_at: null, response_note: null,
    ...overrides,
  };
}

function snapshot(rows: Record<string, unknown>[], extras: Record<string, unknown> = {}) {
  return Response.json({ sample_signoffs: rows, ...extras });
}

function answer(status = "approved", note: string | null = "已按约定核对实物") {
  return signoff({ status, response_note: note, responded_at: "2026-10-01T10:00:00Z", updated_at: "2026-10-01T10:00:00Z" });
}

function choose(status: "approved" | "rejected" = "approved", note?: string) {
  fireEvent.change(screen.getByLabelText("回应结果"), { target: { value: status } });
  if (note !== undefined) fireEvent.change(screen.getByLabelText("回应说明（选填）"), { target: { value: note } });
}

describe("ExternalProjectResponses", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => { fetchMock.mockReset(); vi.stubGlobal("fetch", fetchMock); });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

  it.each(["owner", "admin", "project_manager", "engineer", "quality", "unknown"])("does not fetch or offer external actions to %s", role => {
    render(<ExternalProjectResponses projectId={projectId} role={role} />);
    expect(screen.getByText("此入口仅供项目客户或供应商回应请求。")).toBeTruthy();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("shows only the actor's requests and their projected evidence references", async () => {
    fetchMock.mockResolvedValue(snapshot([
      signoff(),
      signoff({ id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc", audience: "supplier", title: "供应商私有请求" }),
      signoff({ id: "dddddddd-dddd-4ddd-8ddd-dddddddddddd", audience: "internal", title: "内部质量签核" }),
      answer("rejected", "外观需重新核对"),
    ].map((row, index) => index === 3 ? { ...row, id: "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee", title: "上轮外观确认" } : row), {
      builds: [{ code: "内部批次机密" }], samples: [{ serial_number: "内部样机序列" }],
      test_cases: [{ title: "内部测试机密" }], test_reports: [{ title: "内部报告机密" }],
    }));
    render(<ExternalProjectResponses projectId={projectId} role="customer" />);

    expect(await screen.findByText("外观样机确认")).toBeTruthy();
    expect(screen.getByText("已回应 · 退回核对")).toBeTruthy();
    expect(screen.getByText("外观需重新核对")).toBeTruthy();
    expect(screen.getAllByText("关联样机 1 台")).toHaveLength(2);
    for (const summary of screen.getAllByText("查看本次回应对象与证据范围")) fireEvent.click(summary);
    const references = screen.getAllByRole("list", { name: "本次请求关联的样机引用" });
    expect(within(references[0]).getByText(sampleId)).toBeTruthy();
    for (const title of ["供应商私有请求", "内部质量签核", "内部批次机密", "内部样机序列", "内部测试机密", "内部报告机密"]) {
      expect(screen.queryByText(title)).toBeNull();
    }
    expect(fetchMock).toHaveBeenCalledWith(`/api/projects/${projectId}/npi`, { cache: "no-store" });
  });

  it("submits exact legal status/note to the original object and rereads the saved result", async () => {
    fetchMock.mockResolvedValueOnce(snapshot([signoff()]))
      .mockResolvedValueOnce(Response.json(answer()))
      .mockResolvedValueOnce(snapshot([answer()]));
    render(<ExternalProjectResponses projectId={projectId} role="customer" />);
    await screen.findByText("外观样机确认");
    expect(screen.getByRole("button", { name: "提交本次回应" })).toBeDisabled();
    choose("approved", "  已按约定核对实物  ");
    fireEvent.click(screen.getByRole("button", { name: "提交本次回应" }));

    expect(await screen.findByText("已记录「外观样机确认」的回应：确认符合。")).toBeTruthy();
    expect(screen.getByText("已回应 · 确认符合")).toBeTruthy();
    expect(screen.getByText("已按约定核对实物")).toBeTruthy();
    expect(fetchMock.mock.calls[1]).toEqual([
      `/api/projects/${projectId}/npi/sample-signoffs/${signoffId}/respond`,
      { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status: "approved", note: "已按约定核对实物" }) },
    ]);
    expect(fetchMock.mock.calls[2][0]).toBe(`/api/projects/${projectId}/npi`);
    expect(screen.queryByRole("button", { name: "提交本次回应" })).toBeNull();
  });

  it("supports the supplier's rejected response with a nullable note", async () => {
    const requested = signoff({ audience: "supplier" });
    const saved = answer("rejected", null);
    saved.audience = "supplier";
    fetchMock.mockResolvedValueOnce(snapshot([requested]))
      .mockResolvedValueOnce(Response.json(saved))
      .mockResolvedValueOnce(snapshot([saved]));
    render(<ExternalProjectResponses projectId={projectId} role="supplier" />);
    await screen.findByText("外观样机确认");
    choose("rejected");
    fireEvent.click(screen.getByRole("button", { name: "提交本次回应" }));
    expect(await screen.findByText("已记录「外观样机确认」的回应：退回核对。")).toBeTruthy();
    expect(JSON.parse(String(fetchMock.mock.calls[1][1]?.body))).toEqual({ status: "rejected", note: null });
  });

  it("locks all write controls synchronously until the write and refresh complete", async () => {
    let finishWrite!: (value: Response) => void;
    const writing = new Promise<Response>(resolve => { finishWrite = resolve; });
    fetchMock.mockResolvedValueOnce(snapshot([signoff()]))
      .mockReturnValueOnce(writing)
      .mockResolvedValueOnce(snapshot([answer()]));
    render(<ExternalProjectResponses projectId={projectId} role="customer" />);
    await screen.findByText("外观样机确认");
    choose("approved", "已按约定核对实物");
    const form = screen.getByRole("form", { name: "回应 外观样机确认" });
    fireEvent.submit(form);
    fireEvent.submit(form);
    expect(screen.getByLabelText("回应结果")).toBeDisabled();
    expect(screen.getByRole("button", { name: "刷新请求" })).toBeDisabled();
    expect(fetchMock.mock.calls.filter(call => call[1]?.method === "POST")).toHaveLength(1);
    await act(async () => { finishWrite(Response.json(answer())); });
    expect(await screen.findByText("已回应 · 确认符合")).toBeTruthy();
  });

  it("never offers or sends waived, even if a select option is injected", async () => {
    fetchMock.mockResolvedValue(snapshot([signoff()]));
    render(<ExternalProjectResponses projectId={projectId} role="customer" />);
    await screen.findByText("外观样机确认");
    expect(screen.queryByRole("option", { name: "豁免" })).toBeNull();
    const select = screen.getByLabelText("回应结果");
    const invalid = document.createElement("option");
    invalid.value = "waived"; invalid.textContent = "注入的豁免选项";
    select.appendChild(invalid);
    fireEvent.change(select, { target: { value: "waived" } });
    fireEvent.submit(screen.getByRole("form", { name: "回应 外观样机确认" }));
    expect(screen.getByRole("button", { name: "提交本次回应" })).toBeDisabled();
    expect(fetchMock.mock.calls.filter(call => call[1]?.method === "POST")).toHaveLength(0);
  });

  it("treats an existing waived disposition as finished and never supplies a response form", async () => {
    fetchMock.mockResolvedValue(snapshot([answer("waived", "已由项目团队结束此请求")]));
    render(<ExternalProjectResponses projectId={projectId} role="customer" />);
    expect(await screen.findByText("已结束 · 无须回应")).toBeTruthy();
    expect(screen.queryByRole("form")).toBeNull();
    expect(screen.getByText("当前没有待回应请求。")).toBeTruthy();
  });

  it("hides stale requests on audience/waiver denial and keeps the draft for an authorized reread", async () => {
    fetchMock.mockResolvedValueOnce(snapshot([signoff()]))
      .mockResolvedValueOnce(Response.json({ detail: { code: "NPI_AUDIENCE_DENIED", message: "Signoff audience does not match actor" } }, { status: 403 }))
      .mockResolvedValueOnce(snapshot([signoff()]));
    render(<ExternalProjectResponses projectId={projectId} role="customer" />);
    await screen.findByText("外观样机确认");
    choose("rejected", "尺寸需要核对");
    fireEvent.click(screen.getByRole("button", { name: "提交本次回应" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("当前身份无权读取或回应这条请求");
    expect(screen.queryByText("外观样机确认")).toBeNull();
    expect(screen.queryByRole("form")).toBeNull();
    expect(screen.queryByText(/已记录「/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "重新读取请求" }));
    await screen.findByText("外观样机确认");
    expect(screen.getByLabelText("回应说明（选填）")).toHaveValue("尺寸需要核对");
    expect(screen.getByLabelText("回应结果")).toHaveValue("rejected");
  });

  it("recovers a conflict by showing the actual completed record rather than resubmitting", async () => {
    fetchMock.mockResolvedValueOnce(snapshot([signoff()]))
      .mockResolvedValueOnce(Response.json({ detail: { code: "NPI_CONFLICT" } }, { status: 409 }))
      .mockResolvedValueOnce(snapshot([answer("rejected", "另一位协作者已回复")]));
    render(<ExternalProjectResponses projectId={projectId} role="customer" />);
    await screen.findByText("外观样机确认");
    choose();
    fireEvent.click(screen.getByRole("button", { name: "提交本次回应" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("请求已变化或已被回应");
    fireEvent.click(screen.getByRole("button", { name: "重新读取请求" }));
    expect(await screen.findByText("另一位协作者已回复")).toBeTruthy();
    expect(screen.queryByRole("form")).toBeNull();
  });

  it("blocks an incomplete object/update timestamp and permits a fresh valid read", async () => {
    fetchMock.mockResolvedValueOnce(snapshot([signoff({ updated_at: undefined })]))
      .mockResolvedValueOnce(snapshot([signoff()]));
    render(<ExternalProjectResponses projectId={projectId} role="customer" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("请求资料不完整");
    expect(screen.queryByRole("form")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "重新读取请求" }));
    expect(await screen.findByText("外观样机确认")).toBeTruthy();
    expect(screen.getByRole("form", { name: "回应 外观样机确认" })).toBeTruthy();
  });

  it("does not declare success or allow another write when the post-write read fails", async () => {
    fetchMock.mockResolvedValueOnce(snapshot([signoff()]))
      .mockResolvedValueOnce(Response.json(answer()))
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce(snapshot([answer()]));
    render(<ExternalProjectResponses projectId={projectId} role="customer" />);
    await screen.findByText("外观样机确认");
    choose("approved", "已按约定核对实物");
    fireEvent.click(screen.getByRole("button", { name: "提交本次回应" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("未能确认本次回应结果");
    expect(screen.queryByText(/已记录「/)).toBeNull();
    expect(screen.queryByRole("form")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "重新读取请求" }));
    expect(await screen.findByText("已回应 · 确认符合")).toBeTruthy();
    expect(fetchMock.mock.calls.filter(call => call[1]?.method === "POST")).toHaveLength(1);
  });

  it("does not show an old role's in-flight requests after the role changes", async () => {
    let finishOld!: (value: Response) => void;
    fetchMock.mockReturnValueOnce(new Promise<Response>(resolve => { finishOld = resolve; }))
      .mockResolvedValueOnce(snapshot([signoff({ audience: "supplier", title: "供应商尺寸核对" })]));
    const view = render(<ExternalProjectResponses projectId={projectId} role="customer" />);
    view.rerender(<ExternalProjectResponses projectId={projectId} role="supplier" />);
    expect(await screen.findByText("供应商尺寸核对")).toBeTruthy();
    await act(async () => { finishOld(snapshot([signoff({ title: "旧客户请求" })])); });
    await waitFor(() => expect(screen.queryByText("旧客户请求")).toBeNull());
  });

  it("distinguishes an empty authorized list from an access error", async () => {
    fetchMock.mockResolvedValue(snapshot([]));
    render(<ExternalProjectResponses projectId={projectId} role="supplier" />);
    expect(await screen.findByText("暂无发给您的回应请求")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByRole("form")).toBeNull();
  });

  it("offers a recoverable read error without a response form when project access is refused", async () => {
    fetchMock.mockResolvedValueOnce(Response.json({ detail: { code: "PROJECT_ACCESS_DENIED" } }, { status: 403 }))
      .mockResolvedValueOnce(snapshot([]));
    render(<ExternalProjectResponses projectId={projectId} role="supplier" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("当前身份无权读取或回应这条请求");
    expect(screen.queryByRole("form")).toBeNull();
    expect(screen.queryByText("暂无发给您的回应请求")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "重新读取请求" }));
    expect(await screen.findByText("暂无发给您的回应请求")).toBeTruthy();
  });
});
