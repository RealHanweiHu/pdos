import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SupplierReplies } from "./supplier-replies";

const projectId = "55555555-5555-4555-8555-555555555555";
const supplierId = "66666666-6666-4666-8666-666666666666";
const recordId = "77777777-7777-4777-8777-777777777777";
const documentId = "88888888-8888-4888-8888-888888888888";
const fact = { at: "2020-01-05T00:00:00Z", evidence_id: documentId, location: "原承诺" };
const record = { record_id: recordId, version: 1, payload: { kind: "sample_delivery", title: "P送样", status: "active", responded: null, received: null, promised: fact } };
const preview = { digest: "a".repeat(64), basis: { previous_version: 1, proposed: { ...record.payload, responded: { ...fact, at: "2020-01-03T00:00:00Z" } }, notice: "实际记录，不改具名承诺" } };

describe("supplier reply one-confirmation update", () => {
  const fetchMock = vi.fn<typeof fetch>();
  const onSaved = vi.fn(async () => {});
  beforeEach(() => { vi.clearAllMocks(); vi.stubGlobal("fetch", fetchMock); });
  afterEach(cleanup);
  function show(value = record) { render(<SupplierReplies projectId={projectId} supplierId={supplierId} record={value} documents={[{ id: documentId, filename: "内部转发回复.pdf" }]} onSaved={onSaved}/>); }
  async function prepare() {
    fireEvent.change(screen.getByLabelText("实际发生时间（本机时区）"), { target: { value: "2020-01-03T12:00" } });
    fireEvent.change(screen.getByLabelText("回复或收样证据"), { target: { value: documentId } });
    fireEvent.change(screen.getByLabelText("原件位置与时间依据"), { target: { value: "回复第2页" } });
    fireEvent.change(screen.getByLabelText("回复与该供方、原事项的关系及更新理由"), { target: { value: "原供方同事项" } });
    fireEvent.click(screen.getByRole("button", { name: "预览原事项更新" }));
    await screen.findByRole("button", { name: "确认并更新原事项" });
  }
  it("previews and confirms once against original record without a separate acceptance action", async () => {
    fetchMock.mockResolvedValueOnce(Response.json(preview)).mockResolvedValueOnce(Response.json({ version: 2 }));
    show(); await prepare();
    fireEvent.click(screen.getByRole("button", { name: "确认并更新原事项" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledOnce());
    expect(fetchMock.mock.calls.map(call => String(call[0]))).toEqual([
      `/api/projects/${projectId}/npi/supplier-replies/${supplierId}/${recordId}/preview`,
      `/api/projects/${projectId}/npi/supplier-replies/${supplierId}/${recordId}/confirm`,
    ]);
    const body = JSON.parse(String(fetchMock.mock.calls[1][1]?.body));
    expect(body).toMatchObject({ update: "first_response", evidence_id: documentId, expected_version: 1, expected_digest: preview.digest, evidence_checked: true });
    expect(body).not.toHaveProperty("promised");
    expect(body).not.toHaveProperty("supply_quantity");
    expect(body).not.toHaveProperty("tenant_id");
  });
  it("requires a new preview after reply evidence changes", async () => {
    fetchMock.mockResolvedValueOnce(Response.json(preview));
    show(); await prepare();
    fireEvent.change(screen.getByLabelText("原件位置与时间依据"), { target: { value: "不同证据位置" } });
    expect(screen.getByRole("button", { name: "确认并更新原事项" })).toBeDisabled();
    expect(fetchMock).toHaveBeenCalledOnce();
  });
  it("retains the request id and entered facts after uncertain confirmation failure", async () => {
    fetchMock.mockResolvedValueOnce(Response.json(preview))
      .mockRejectedValueOnce(new Error("连接中断"))
      .mockResolvedValueOnce(Response.json({ version: 2 }));
    show(); await prepare();
    fireEvent.click(screen.getByRole("button", { name: "确认并更新原事项" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("连接中断");
    expect(screen.getByLabelText("原件位置与时间依据")).toHaveValue("回复第2页");
    fireEvent.click(screen.getByRole("button", { name: "确认并更新原事项" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledOnce());
    expect(JSON.parse(String(fetchMock.mock.calls[1][1]?.body)).request_id).toEqual(JSON.parse(String(fetchMock.mock.calls[2][1]?.body)).request_id);
  });
  it("does not expose an update for withdrawn or failure records", () => {
    show({ ...record, payload: { ...record.payload, status: "withdrawn" } });
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
