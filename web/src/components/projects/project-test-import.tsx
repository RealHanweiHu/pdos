"use client";

import { useEffect, useId, useRef, useState } from "react";
import { TestImportPreview } from "./test-import-preview";
import { Button } from "@/components/ui/button";
import { NpiRequestError, readTestImport, uploadTestReport, type TestImportBatch } from "./project-npi-api";

type Props = { projectId: string; planId: string; onImported?: () => Promise<void> };
const storageKey = (projectId: string, planId: string) => `pdos:report-import:${projectId}:${planId}`;

export function ProjectTestImport(props: Props) {
  return <ImportSession key={`${props.projectId}:${props.planId}`} {...props} />;
}

function ImportSession({ projectId, planId, onImported }: Props) {
  const inputId = useId();
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [batch, setBatch] = useState<TestImportBatch | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pendingRun, setPendingRun] = useState<string | null>(null);
  const [pollPaused, setPollPaused] = useState(false);
  const [pollRevision, setPollRevision] = useState(0);
  const active = useRef(true);
  const imported = useRef(onImported);
  useEffect(() => { imported.current = onImported; }, [onImported]);
  const processing = busy || pendingRun !== null;
  function rememberRun(id: string | null) {
    setPendingRun(id);
    try {
      if (id) sessionStorage.setItem(storageKey(projectId, planId), id);
      else sessionStorage.removeItem(storageKey(projectId, planId));
    } catch { /* The open page retains the receipt. */ }
  }
  useEffect(() => {
    let mounted = true;
    queueMicrotask(() => {
      try {
        const saved = sessionStorage.getItem(storageKey(projectId, planId));
        if (mounted && saved) setPendingRun(saved);
      } catch { /* Browser storage is optional. */ }
    });
    return () => { mounted = false; };
  }, [projectId, planId]);
  useEffect(() => {
    if (!pendingRun || pollPaused) return;
    let mounted = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    async function poll() {
      try {
        const result = await readTestImport(projectId, pendingRun!);
        if (!mounted) return;
        if (["queued", "running"].includes(result.status)) {
          timer = setTimeout(() => void poll(), 2000); return;
        }
        rememberRun(null);
        if (result.batch) {
          setBatch(result.batch); await imported.current?.();
        } else {
          setError(result.status === "cancelled" ? "导入任务已取消。" : "报告处理未完成，请核对文件或使用已确认模板重试。");
        }
      } catch {
        if (mounted) { setError("暂时无法查询导入状态，请重试。"); setPollPaused(true); }
      }
    }
    timer = setTimeout(() => void poll(), 0);
    return () => { mounted = false; clearTimeout(timer); };
    // This component is keyed by the project and plan; the callback is held in a ref.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingRun, pollPaused, pollRevision, projectId, planId]);

  async function cancelPending() {
    if (!pendingRun || inFlight.current) return;
    inFlight.current = true; setBusy(true); setError(null);
    try {
      const response = await fetch(`/api/ai/runs/${encodeURIComponent(pendingRun)}/cancel`, { method: "POST" });
      if (!response.ok) throw new Error();
      if (active.current) { setPollPaused(false); setPollRevision((n) => n + 1); }
    } catch { if (active.current) setError("暂时无法取消，请重试。"); }
    finally { inFlight.current = false; if (active.current) setBusy(false); }
  }
  const inFlight = useRef(false);
  useEffect(() => {
    active.current = true;
    return () => { active.current = false; };
  }, []);

  async function upload() {
    if (!file || inFlight.current || pendingRun) return;
    inFlight.current = true;
    setBusy(true);
    setError(null);
    setBatch(null);
    try {
      const result = await uploadTestReport(projectId, planId, file);
      if (active.current) {
        if ("run_id" in result) {
          if (result.batch) { setBatch(result.batch); await imported.current?.(); }
          else if (result.run_id && ["queued", "running"].includes(result.status)) {
            rememberRun(result.run_id); setPollPaused(false);
          } else setError(result.status === "cancelled" ? "导入任务已取消。" : "该报告请求不可继续，请使用已确认模板或核对文件。");
        } else { setBatch(result); await imported.current?.(); }
      }
    } catch (failure) {
      if (active.current) setError(failure instanceof NpiRequestError ? failure.message : "报告上传失败，请重试");
    } finally {
      inFlight.current = false;
      if (active.current) setBusy(false);
    }
  }

  return (
    <div className="mt-3 space-y-2 border-t pt-3">
      <label htmlFor={inputId} className="text-sm font-medium">导入 Excel 测试报告</label>
      <div className="flex flex-wrap items-center gap-2">
        <input id={inputId} type="file" accept=".xlsx" disabled={processing}
          className="min-w-0 max-w-full text-sm"
          onChange={(event) => { setFile(event.target.files?.[0] ?? null); setBatch(null); setError(null); }} />
        <Button type="button" variant="outline" size="sm" disabled={processing || !file} onClick={() => void upload()}>
          {busy ? "正在识别报告…" : "上传并检查"}
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">同一计划下，相同文件内容会复用已有批次；改文件名也不会重复导入。</p>
      {pendingRun && <div role="status" className="flex flex-wrap items-center gap-2 text-sm">
        <span>{pollPaused ? "导入状态待查询" : "报告正在后台处理，可稍后回来查看。"}</span>
        {pollPaused && <Button type="button" variant="outline" size="sm" onClick={() => { setError(null); setPollPaused(false); setPollRevision((n) => n + 1); }}>重新查询状态</Button>}
        <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => void cancelPending()}>取消导入</Button>
      </div>}
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      {batch && (
        <div role="status" className="space-y-1 rounded-md border p-3 text-sm">
          <p className="font-medium">{batch.reused_existing
            ? batch.status === "confirmed" ? "相同报告已确认，已复用原批次" : "相同报告已上传，已复用待确认批次"
            : "报告已解析，等待核对"}</p>
          <p>{batch.reused_existing ? "未新增文件、批次或测试记录。" : batch.created_run_ids.length > 0 ? "已生成草稿，尚未计入正式测试结果。" : "文件已保存，尚未生成测试记录。"}</p>
          <p>批次状态：{batch.status === "confirmed" ? "已确认，无需再次确认" : "待确认"} · 记录 {batch.created_run_ids.length} 条</p>
          {batch.created_run_ids.length === 0 && <p>暂无可确认记录，请先核对原报告缺项。</p>}
          {batch.skipped_rows.length > 0 && <p>保留 {batch.skipped_rows.length} 处跳过说明（含非测试工作表）。</p>}
          <TestImportPreview key={batch.id} projectId={projectId} batchId={batch.id} onConfirmed={onImported} />
          <details>
            <summary className="cursor-pointer text-muted-foreground">查看批次编号</summary>
            <p className="break-all font-mono text-xs">{batch.id}</p>
          </details>
        </div>
      )}
    </div>
  );
}
