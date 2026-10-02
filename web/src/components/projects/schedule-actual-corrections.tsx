"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { caseLinkRequest } from "@/components/cases/case-requirements";

type Point = { id: string; task_id: string; point: "start" | "finish"; title: string; observed_at: string; original_observed_at: string; original_event_row_id: number; event_row_id: number; correction_version: number; digest: string; can_correct: boolean };
type Correction = { id: string; task_id: string; point: string; version: number; previous_observed_at: string; observed_at: string; reason: string; evidence: string; actor_user_id: string; actor_name: string; created_at: string; event_row_id: number };
type State = { points: Point[]; items: Correction[]; has_more: boolean };
const when = (value: string) => new Date(value).toLocaleString();
const localTime = (value: string) => { const date = new Date(value); return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 19); };

type CorrectionsProps = { projectId: string; onCorrected: () => void };
export function ScheduleActualCorrections(props: CorrectionsProps) {
  return <ScheduleActualCorrectionsContent key={props.projectId} {...props} />;
}
function ScheduleActualCorrectionsContent({ projectId, onCorrected }: CorrectionsProps) {
  const [data, setData] = useState<State | null>(null);
  const [selected, setSelected] = useState("");
  const [time, setTime] = useState("");
  const [reason, setReason] = useState("");
  const [evidence, setEvidence] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const requests = useRef(new Map<string, string>());
  const point = data?.points.find((item) => item.id === selected);
  const path = `projects/${projectId}/execution/actual-corrections`;
  async function refresh() {
    setBusy(true); setError(null);
    try { setData(await caseLinkRequest<State>(path)); setSelected(""); }
    catch (failure) { setData(null); setError(failure instanceof Error ? failure.message : "纠错历史读取失败"); }
    finally { setBusy(false); }
  }
  useEffect(() => { let alive = true;
    caseLinkRequest<State>(`projects/${projectId}/execution/actual-corrections`).then((value) => { if (alive) setData(value); }).catch((failure) => { if (alive) setError(failure instanceof Error ? failure.message : "纠错历史读取失败"); });
    return () => { alive = false; };
  }, [projectId]);
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!point || busy) return;
    setBusy(true); setError(null); setNotice(null);
    let saved = false;
    try {
      const body = { task_id: point.task_id, point: point.point, expected_digest: point.digest, observed_at: time === localTime(point.observed_at) ? point.observed_at : new Date(time).toISOString(), reason, evidence };
      const key = JSON.stringify(body); let id = requests.current.get(key); if (!id) { id = crypto.randomUUID(); requests.current.set(key, id); }
      await caseLinkRequest(path, { ...body, request_id: id });
      saved = true;
      setReason(""); setEvidence(""); setSelected("");
      setNotice("纠错已保存，实际时间与预测已更新，可回查原记录和误差修订。");
      window.dispatchEvent(new Event("pdos:forecast-updated"));
      onCorrected();
      setData(await caseLinkRequest<State>(path));
    } catch (failure) { if (saved) setData(null); setError(failure instanceof Error ? failure.message : "实际时间纠错失败"); }
    finally { setBusy(false); }
  }
  return <details className="space-y-3 rounded-md border p-3">
    <summary className="cursor-pointer text-sm font-medium">实际时间纠错与历史</summary>
    <p className="text-xs text-muted-foreground">任务负责人或项目编辑成员可更正已有记录。填写本地时间及依据；原始记录保留，任务状态不随纠错改变。</p>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {notice && <p role="status" className="text-sm">{notice}</p>}
    {!!data?.points.some((item) => item.can_correct) && <form className="space-y-3" onSubmit={save}>
      <label className="block text-xs">更正哪项记录<select required disabled={busy} className="mt-1 w-full rounded-md border bg-background p-2" value={selected} onChange={(event) => { const next = data.points.find((item) => item.id === event.target.value); setSelected(event.target.value); setTime(next ? localTime(next.observed_at) : ""); setReason(""); setEvidence(""); setNotice(null); }}>
        <option value="">选择实际开工或完成</option>{data.points.filter((item) => item.can_correct).map((item) => <option key={item.id} value={item.id}>{item.title} · {item.point === "start" ? "开工" : "完成"}</option>)}
      </select></label>
      {point && <><p className="text-xs">当前：{when(point.observed_at)} · {point.correction_version ? `已纠错 ${point.correction_version} 次` : "原始记录"} · <a className="text-primary underline" href={`/projects?project=${projectId}&tab=timeline&event_id=${point.original_event_row_id}`}>原始事件：{when(point.original_observed_at)}</a></p>
        <label className="block text-xs">更正后的时间<input required disabled={busy} type="datetime-local" step="1" className="mt-1 w-full rounded-md border bg-background p-2" value={time} onChange={(event) => setTime(event.target.value)} /></label>
        <label className="block text-xs">纠错原因<input required disabled={busy} maxLength={4000} className="mt-1 w-full rounded-md border bg-background p-2" value={reason} onChange={(event) => setReason(event.target.value)} /></label>
        <label className="block text-xs">核对依据<textarea required disabled={busy} maxLength={4000} className="mt-1 w-full rounded-md border bg-background p-2" placeholder="填写实际记录、交接或现场核对依据" value={evidence} onChange={(event) => setEvidence(event.target.value)} /></label>
        <Button size="sm" disabled={busy || !time || !reason.trim() || !evidence.trim()}>{busy ? "保存中…" : "保存纠错并更新预测"}</Button>
      </>}
    </form>}
    {data?.items.map((item) => <article key={item.id} className="space-y-1 border-t pt-2 text-xs"><p className="font-medium">{data.points.find((entry) => entry.task_id === item.task_id)?.title ?? item.task_id} · {item.point === "start" ? "开工" : "完成"}纠错 {item.version}</p><p>{when(item.previous_observed_at)} → {when(item.observed_at)}</p><p>原因：{item.reason}</p><p>依据：{item.evidence}</p><p className="text-muted-foreground">办理人：{item.actor_name} · {when(item.created_at)} · <a className="text-primary underline" href={`/projects?project=${projectId}&tab=timeline&event_id=${item.event_row_id}`}>纠错事件</a></p></article>)}
    {data && !data.items.length && <p className="text-xs text-muted-foreground">暂无纠错记录。</p>}
    {data?.has_more && <p className="text-xs text-muted-foreground">显示最近 200 条，更早记录保留在项目事件中。</p>}
    <Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => void refresh()}>刷新实际记录</Button>
  </details>;
}
