import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ProjectTestImport } from "./project-test-import";
import { readTestImport, uploadTestReport } from "./project-npi-api";

vi.mock("./project-npi-api", () => ({
  uploadTestReport: vi.fn(),
  readTestImport: vi.fn(),
  NpiRequestError: class extends Error {},
}));
const upload = vi.mocked(uploadTestReport);
const batch = { id: "original-batch", project_id: "project", plan_id: "plan", document_id: "document", status: "parsed" as const, created_run_ids: ["run"], skipped_rows: [], reused_existing: true };
function selectFile() {
  fireEvent.change(screen.getByLabelText("导入 Excel 测试报告"), { target: { files: [new File(["report"], "renamed.xlsx")] } });
  fireEvent.click(screen.getByRole("button", { name: "上传并检查" }));
}
beforeEach(() => { vi.clearAllMocks(); sessionStorage.clear(); });
afterEach(cleanup);
describe("test report reuse notice", () => {
  it.each(["parsed", "confirmed"] as const)("explains reuse for %s without claiming new records", async (status) => {
    upload.mockResolvedValue({ ...batch, status });
    const refresh = vi.fn().mockResolvedValue(undefined);
    render(<ProjectTestImport projectId="project" planId="plan" onImported={refresh} />);
    selectFile();
    expect(await screen.findByText(status === "confirmed" ? "相同报告已确认，已复用原批次" : "相同报告已上传，已复用待确认批次")).toBeInTheDocument();
    expect(screen.getByText("未新增文件、批次或测试记录。")).toBeInTheDocument();
    expect(screen.getByText("original-batch")).toBeInTheDocument();
    expect(upload).toHaveBeenCalledWith("project", "plan", expect.any(File));
    expect(refresh).toHaveBeenCalledOnce();
  });
  it("distinguishes a new empty batch from a reused one", async () => {
    upload.mockResolvedValue({ ...batch, reused_existing: false, created_run_ids: [] });
    render(<ProjectTestImport projectId="project" planId="plan" />);
    selectFile();
    expect(await screen.findByText("报告已解析，等待核对")).toBeInTheDocument();
    expect(screen.getByText("暂无可确认记录，请先核对原报告缺项。")).toBeInTheDocument();
  });
  it("blocks extra clicks in flight and permits retry on failure", async () => {
    let reject!: (reason: Error) => void;
    upload.mockReturnValue(new Promise((_, fail) => { reject = fail; }));
    render(<ProjectTestImport projectId="project" planId="plan" />);
    selectFile();
    fireEvent.click(screen.getByRole("button", { name: "正在识别报告…" }));
    expect(upload).toHaveBeenCalledTimes(1);
    reject(new Error("network"));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("报告上传失败，请重试"));
    expect(screen.getByRole("button", { name: "上传并检查" })).toBeEnabled();
  });
});


describe("background report import", () => {
  const pending = { run_id: "queue-run", status: "queued", batch: null, error_code: null };
  it("polls the saved request and displays its draft batch", async () => {
    upload.mockResolvedValue(pending);
    vi.mocked(readTestImport).mockResolvedValue({ ...pending, status: "completed", batch: { ...batch, reused_existing: false } });
    const refresh = vi.fn().mockResolvedValue(undefined);
    render(<ProjectTestImport projectId="project" planId="plan" onImported={refresh} />);
    selectFile();
    expect(await screen.findByText("报告已解析，等待核对")).toBeInTheDocument();
    expect(readTestImport).toHaveBeenCalledWith("project", "queue-run");
    expect(refresh).toHaveBeenCalledOnce();
    expect(sessionStorage.getItem("pdos:report-import:project:plan")).toBeNull();
  });
  it("restores the receipt after remount and allows retrying a paused query", async () => {
    sessionStorage.setItem("pdos:report-import:project:plan", "queue-run");
    vi.mocked(readTestImport).mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValue({ ...pending, status: "cancelled" });
    render(<ProjectTestImport projectId="project" planId="plan" />);
    fireEvent.click(await screen.findByRole("button", { name: "重新查询状态" }));
    expect(await screen.findByText("导入任务已取消。")).toBeInTheDocument();
    expect(upload).not.toHaveBeenCalled();
    expect(sessionStorage.getItem("pdos:report-import:project:plan")).toBeNull();
  });
  it("cancels a restored pending request through the public control endpoint", async () => {
    sessionStorage.setItem("pdos:report-import:project:plan", "queue-run");
    vi.mocked(readTestImport).mockResolvedValue(pending);
    const fetcher = vi.fn().mockResolvedValue(new Response("{}"));
    vi.stubGlobal("fetch", fetcher);
    try {
      render(<ProjectTestImport projectId="project" planId="plan" />);
      await screen.findByText("报告正在后台处理，可稍后回来查看。");
      await waitFor(() => expect(readTestImport).toHaveBeenCalled());
      vi.mocked(readTestImport).mockResolvedValue({ ...pending, status: "cancelled" });
      fireEvent.click(screen.getByRole("button", { name: "取消导入" }));
      expect(await screen.findByText("导入任务已取消。")).toBeInTheDocument();
      expect(fetcher).toHaveBeenCalledWith("/api/ai/runs/queue-run/cancel", { method: "POST" });
    } finally { vi.unstubAllGlobals(); }
  });
});
