import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MaterialReconciliationReview } from "./material-reconciliation-review";

const props = { projectId: "p", sourceId: "s", movementId: "m", evidenceId: "d", hasReview: true };
const preview = { digest: "a".repeat(64), eligible: true, reasons: [],
  basis: { previous_version: 2, evidence: { filename: "余额核对.pdf" } } };
const fetchMock = vi.fn<typeof fetch>();
const onSaved = vi.fn<() => Promise<void>>();
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
beforeEach(() => { fetchMock.mockReset(); onSaved.mockReset(); onSaved.mockResolvedValue();
  vi.stubGlobal("fetch", fetchMock); });
async function prepare() {
  fireEvent.change(screen.getByLabelText("ERP原交易与余额包含关系／撤回理由"), {
    target: { value: "原领料行已反映在本版ERP余额" },
  });
  fireEvent.click(screen.getByRole("button", { name: "预览余额包含关系" }));
  await screen.findByText("当前具名预览 · 余额核对.pdf");
  fireEvent.click(screen.getByRole("checkbox"));
}

describe("bound material reconciliation confirmation", () => {
  it("requires a dedicated preview and sends its version and digest", async () => {
    fetchMock.mockResolvedValueOnce(Response.json(preview)).mockResolvedValueOnce(Response.json({ id: "saved" }));
    render(<MaterialReconciliationReview {...props} onSaved={onSaved}/>);
    expect(screen.queryByRole("button", { name: "确认本版余额已反映" })).not.toBeInTheDocument();
    await prepare();
    fireEvent.click(screen.getByRole("button", { name: "确认本版余额已反映" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledOnce());
    expect(fetchMock.mock.calls.map(call => call[0])).toEqual([
      "/api/projects/p/npi/material-movements/m/reconcile/preview",
      "/api/projects/p/npi/material-movements/m/reconcile",
    ]);
    expect(JSON.parse(String(fetchMock.mock.calls[1][1]?.body))).toMatchObject({
      supply_snapshot_id: "s", evidence_id: "d", outcome: "confirmed",
      expected_version: 2, expected_digest: preview.digest,
    });
  });

  it("blocks saved preview after the selected evidence changes", async () => {
    fetchMock.mockResolvedValueOnce(Response.json(preview));
    const view = render(<MaterialReconciliationReview {...props} onSaved={onSaved}/>);
    await prepare();
    view.rerender(<MaterialReconciliationReview {...props} evidenceId="another-document" onSaved={onSaved}/>);
    expect(screen.getByRole("button", { name: "确认本版余额已反映" })).toBeDisabled();
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("keeps original inputs and request id after an uncertain network result", async () => {
    fetchMock.mockResolvedValueOnce(Response.json(preview)).mockRejectedValueOnce(new Error("网络中断"))
      .mockResolvedValueOnce(Response.json({ id: "saved" }));
    render(<MaterialReconciliationReview {...props} onSaved={onSaved}/>);
    await prepare(); fireEvent.click(screen.getByRole("button", { name: "确认本版余额已反映" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("网络中断");
    expect(screen.getByLabelText("ERP原交易与余额包含关系／撤回理由")).toHaveValue("原领料行已反映在本版ERP余额");
    fireEvent.click(screen.getByRole("button", { name: "确认本版余额已反映" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledOnce());
    expect(JSON.parse(String(fetchMock.mock.calls[1][1]?.body)).request_id)
      .toEqual(JSON.parse(String(fetchMock.mock.calls[2][1]?.body)).request_id);
  });

  it("blocks current confirmation when the source drift preview is ineligible", async () => {
    fetchMock.mockResolvedValueOnce(Response.json({ ...preview, eligible: false, reasons: ["原快照已变化"] }));
    render(<MaterialReconciliationReview {...props} onSaved={onSaved}/>);
    await prepare();
    expect(screen.getByRole("button", { name: "确认本版余额已反映" })).toBeDisabled();
    expect(screen.getByText("原快照已变化")).toBeInTheDocument();
  });
});
