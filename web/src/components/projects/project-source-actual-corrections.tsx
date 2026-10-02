"use client";

import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { caseLinkRequest } from "@/components/cases/case-requirements";

type Window = { started_at: string | null; finished_at: string | null };
type Item = { node_id: string; node_kind: string; title: string; expected_digest: string; can_correct: boolean; actual: Window & { id: string; version: number; raw_observation?: Window; actual_correction?: { version: number }; correction_conflict?: string } };
type History = Window & { id: string; node_id: string; version: number; previous_snapshot: Window; original_snapshot: Window; actor_name: string; reason: string; evidence: string; created_at: string; event_row_id: number };
type State = { items: Item[]; history: History[]; has_more: boolean };
const when = (value: string | null) => value ? new Date(value).toLocaleString() : "未知";
const local = (value: string | null) => { if (!value) return ""; const date = new Date(value); return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 23); };
const submitted = (value: FormDataEntryValue | null, original: string | null) => { const text = String(value ?? ""); return text === local(original) ? original : text ? new Date(text).toISOString() : null; };
const field = "mt-1 w-full rounded-md border bg-background p-2 text-sm";

export function ProjectSourceActualCorrections({ projectId, onChanged }: { projectId: string; onChanged: () => void }) {
  return <SourceCorrections key={projectId} projectId={projectId} onChanged={onChanged} />;
}

function SourceCorrections({ projectId, onChanged }: { projectId: string; onChanged: () => void }) {
  const [open, setOpen] = useState(false); const [data, setData] = useState<State | null>(null);
  const [busy, setBusy] = useState(false); const [error, setError] = useState<string | null>(null); const [notice, setNotice] = useState<string | null>(null);
  const requests = useRef(new Map<string, string>());
  const path = `projects/${projectId}/execution/source-actual-corrections`;
  async function load() { setData(await caseLinkRequest<State>(path)); }
  async function refresh() { setBusy(true); setError(null); try { await load(); } catch (failure) { setData(null); setError(failure instanceof Error ? failure.message : "实际时间读取失败"); } finally { setBusy(false); } }
  async function correct(item: Item, form: HTMLFormElement) {
    const values = new FormData(form);
    const start = submitted(values.get("started_at"), item.actual.started_at);
    const finish = item.node_kind === "milestone" ? start : submitted(values.get("finished_at"), item.actual.finished_at);
    const body = { observation_id: item.actual.id, expected_digest: item.expected_digest, started_at: start, finished_at: finish, reason: values.get("reason"), evidence: values.get("evidence") };
    const key = JSON.stringify({ projectId, nodeId: item.node_id, body }); let requestId = requests.current.get(key);
    if (!requestId) { requestId = crypto.randomUUID(); requests.current.set(key, requestId); }
    setBusy(true); setError(null); setNotice(null);
    let saved = false;
    try { await caseLinkRequest(`${path}/${item.node_id}`, { ...body, request_id: requestId }); saved = true; setNotice("更正及依据已追加，当前实际时间和后续预测已更新。"); window.dispatchEvent(new Event("pdos:forecast-updated")); onChanged(); await load(); }
    catch (failure) { if (saved) setData(null); setError(failure instanceof Error ? failure.message : "实际时间更正未完成"); }
    finally { setBusy(false); }
  }
  return <section className="space-y-3 rounded-md border p-3">
    <Button size="sm" type="button" variant="outline" disabled={busy} onClick={() => { setOpen(!open); if (!open) void refresh(); }}>{open ? "收起业务实际时间纠错" : "更正业务实际时间"}</Button>
    {open && <>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}{notice && <p role="status" className="text-sm">{notice}</p>}
      <p className="text-xs text-muted-foreground">适用于评审、试制、测试、认证和里程碑。原始业务记录继续保留；时间更正不改变业务结论。无可靠时间依据可留空为未知。</p>
      {data && !data.items.length && <p className="text-sm">暂无可更正的业务实际观察。</p>}
      {data?.items.map((item) => <article key={item.node_id} className="space-y-2 border-t pt-3 text-sm">
        <p className="font-medium">{item.title} · 观察 v{item.actual.version}{item.actual.actual_correction && ` · 更正 v${item.actual.actual_correction.version}`}</p>
        <p className="text-xs">当前实际：{when(item.actual.started_at)} → {when(item.actual.finished_at)}</p>
        {item.actual.raw_observation && <p className="text-xs text-muted-foreground">原始记录：{when(item.actual.raw_observation.started_at)} → {when(item.actual.raw_observation.finished_at)}</p>}
        {item.actual.correction_conflict && <p className="text-xs text-destructive">{item.actual.correction_conflict}</p>}
        {item.can_correct && <details><summary className="cursor-pointer text-xs">提交时间更正</summary><form key={item.expected_digest} className="space-y-2 pt-2" onSubmit={(event) => { event.preventDefault(); void correct(item, event.currentTarget); }}>
          <label className="block">{item.node_kind === "milestone" ? "实际完成时刻" : "实际开始"}（本地时间）<input type="datetime-local" step="0.001" name="started_at" required={item.node_kind === "milestone"} defaultValue={local(item.actual.started_at)} className={field} disabled={busy} /></label>
          {item.node_kind !== "milestone" && <label className="block">实际结束（本地时间）<input type="datetime-local" step="0.001" name="finished_at" defaultValue={local(item.actual.finished_at)} className={field} disabled={busy} /></label>}
          <label className="block">更正原因<textarea required name="reason" maxLength={2048} className={field} disabled={busy} /></label>
          <label className="block">实际时间依据<textarea required name="evidence" maxLength={2048} className={field} disabled={busy} /></label>
          <Button size="sm" disabled={busy}>保存更正与依据</Button>
        </form></details>}
        {data.history.some((row) => row.node_id === item.node_id) && <details><summary className="cursor-pointer text-xs">更正历史</summary>{data.history.filter((row) => row.node_id === item.node_id).map((row) => <div className="my-2 space-y-1 border-l pl-2 text-xs" key={row.id}><p>更正 v{row.version} · {row.actor_name} · {when(row.created_at)}</p><p>更正前 {when(row.previous_snapshot.started_at)} → {when(row.previous_snapshot.finished_at)}</p><p>更正后 {when(row.started_at)} → {when(row.finished_at)}</p><p className="whitespace-pre-wrap">{row.reason} · {row.evidence}</p><a className="text-primary underline" href={`/projects?project=${projectId}&tab=timeline&event_id=${row.event_row_id}`}>查看更正事件</a></div>)}</details>}
      </article>)}
      {data?.has_more && <p className="text-xs">显示最近 500 条更正，更早依据继续保留。</p>}
      <Button size="sm" type="button" variant="ghost" disabled={busy} onClick={() => void refresh()}>刷新实际时间与更正</Button>
    </>}
  </section>;
}
