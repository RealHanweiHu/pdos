"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { obj, text, type Row } from "@/components/quality/fmea-sources";
import { ChangeDiscussionRuns } from "@/components/projects/change-discussion-runs";

export function MyWorkDiscussion({ projectId, runId }: { projectId: string; runId: string }) {
  const [data, setData] = useState<Row | null>(null), [error, setError] = useState(""), [busy, setBusy] = useState(true);
  const load = useCallback(async (signal?: AbortSignal): Promise<Row> => {
    const response = await fetch(`/api/projects/${projectId}/changes/discussion-runs/${runId}`, { cache: "no-store", signal });
    const value: unknown = await response.json();
    if (!response.ok) throw new Error(text(obj(obj(value).detail).message) || "当前无法读取原讨论，请核对项目权限或重试");
    return obj(value);
  }, [projectId, runId]);
  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal).then(value => { if (!controller.signal.aborted) setData(value); })
      .catch((e: unknown) => { if (!controller.signal.aborted) { setData(null); setError(e instanceof Error ? e.message : "读取失败"); } })
      .finally(() => { if (!controller.signal.aborted) setBusy(false); });
    return () => controller.abort();
  }, [load]);
  async function refresh() {
    setBusy(true); setError("");
    try { setData(await load()); }
    catch (e) { setData(null); setError(e instanceof Error ? e.message : "读取失败"); }
    finally { setBusy(false); }
  }
  const run = obj(data?.run);
  return <div className="space-y-3 text-sm">
    <p>通知记录反映当时的状态；下方读取原运行当前进度。标为已读不会停止运行、通过摘要核对或批准变更。</p>
    <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void refresh()}>重新读取当前资料与讨论</Button>
    {busy && <p role="status">正在读取原讨论…</p>}{error && <p role="alert" className="text-destructive">{error}</p>}
    {data && !busy && <>
      {data.source_error != null && <p className="text-primary">当前资料暂不可核对：{text(data.source_error)}。原发言与核对历史仍可回看。</p>}
      <Link className="text-primary underline" href={run.ecr_id ? `/projects?project=${projectId}&tab=engineering&change_ecr_id=${run.ecr_id}#ecr-${run.ecr_id}` : `/projects?project=${projectId}&tab=engineering`}>{run.ecr_id ? "打开原变更、影响分析与 ECN 办理" : "打开项目中的主题讨论"}</Link>
      <ChangeDiscussionRuns key={`${runId}:${text(obj(data.source).digest)}`} projectId={projectId} ecrId={run.ecr_id ? text(run.ecr_id) : undefined} source={obj(data.source)} focusedRunId={runId} requestedOpen/>
    </>}
  </div>;
}
