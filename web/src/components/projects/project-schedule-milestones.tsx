"use client";

import { useRef, useState } from "react";
import { MilestoneDesignationForm } from "@/components/projects/milestone-designation";
import type { Row } from "@/components/quality/fmea-sources";
import { Button } from "@/components/ui/button";
import { caseLinkRequest } from "@/components/cases/case-requirements";

type Milestone = {
  node_id: string; title: string; completion_criteria: string; can_complete: boolean;
  owner_name: string; receiver_name: string;
  designation: Row | null; designation_source_current: boolean | null; can_designate: boolean;
  completion: { completed_at: string; evidence: string; completion_criteria: string; actor_name: string; event_row_id: number } | null;
};
type State = { baseline_id: string | null; items: Milestone[] };

export function ProjectScheduleMilestones({ projectId, onCompleted }: { projectId: string; onCompleted: () => void }) {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<State | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [evidence, setEvidence] = useState<Record<string, string>>({});
  const requests = useRef(new Map<string, string>());
  const path = `projects/${projectId}/execution/milestones`;
  async function refresh() {
    setBusy(true); setError(null);
    try { setData(await caseLinkRequest<State>(path)); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "里程碑读取失败"); }
    finally { setBusy(false); }
  }
  async function complete(item: Milestone) {
    if (!data?.baseline_id || busy) return;
    const body = { expected_baseline_id: data.baseline_id, evidence: evidence[item.node_id] };
    const key = JSON.stringify({ projectId, nodeId: item.node_id, body });
    let requestId = requests.current.get(key);
    if (!requestId) { requestId = crypto.randomUUID(); requests.current.set(key, requestId); }
    setBusy(true); setError(null); setNotice(null);
    try {
      await caseLinkRequest(`${path}/${item.node_id}`, { ...body, request_id: requestId });
      setData(await caseLinkRequest<State>(path));
      setNotice("完成依据已保存，实际时间和后续预测已更新。");
      onCompleted();
    } catch (failure) { setError(failure instanceof Error ? failure.message : "里程碑办理未完成"); }
    finally { setBusy(false); }
  }
  return <section className="space-y-3 rounded-md border p-3">
    <Button size="sm" type="button" variant="outline" disabled={busy} onClick={() => { setOpen(!open); if (!open) void refresh(); }}>{open ? "收起里程碑办理" : "办理里程碑与业务重要性"}</Button>
    {open && <>
      {error && <p className="text-sm text-destructive" role="alert">{error}</p>}
      {notice && <p className="text-sm" role="status">{notice}</p>}
      <p className="text-xs text-muted-foreground">按当前获批计划核对完成判据。确认后记录此刻的完成时间，并检查所有前置条件。</p>
      {data && !data.items.length && <p className="text-sm">当前正式计划中还没有独立里程碑。登记检查点后，可通过计划情景和基线变更纳入。</p>}
      {data?.items.map((item) => <article className="space-y-2 border-t pt-3 text-sm" key={item.node_id}>
        <p className="font-medium">{item.title}</p>
        <p className="text-xs">负责人：{item.owner_name} · 接收人：{item.receiver_name}</p>
        <p>完成判据：{item.completion_criteria}</p>
        {item.completion ? <div className="space-y-1 text-xs">
          <p>完成确认记录 · {new Date(item.completion.completed_at).toLocaleString()} · {item.completion.actor_name}</p>
          <p className="whitespace-pre-wrap">完成依据：{item.completion.evidence}</p>
          {item.completion.completion_criteria !== item.completion_criteria && <p>办理时判据：{item.completion.completion_criteria}</p>}
          <a className="text-primary underline" href={`/projects?project=${projectId}&tab=timeline&event_id=${item.completion.event_row_id}`}>查看完成事件</a>
        </div> : item.can_complete ? <form className="space-y-2" onSubmit={(event) => { event.preventDefault(); void complete(item); }}>
          <label className="block">完成依据<textarea required maxLength={2048} className="mt-1 w-full rounded-md border bg-background p-2" disabled={busy} value={evidence[item.node_id] ?? ""} onChange={(event) => setEvidence({ ...evidence, [item.node_id]: event.target.value })} placeholder="说明哪些交付或证据满足了上方判据" /></label>
          <Button size="sm" disabled={busy || !evidence[item.node_id]?.trim()}>确认完成并记录时间</Button>
        </form> : <p className="text-xs text-muted-foreground">项目激活后，由计划负责人、接收人或项目管理人员办理。</p>}
        {data.baseline_id&&<MilestoneDesignationForm key={`${item.node_id}:${item.designation?.id??"new"}`} projectId={projectId} nodeId={item.node_id} baselineId={data.baseline_id} current={item.designation} sourceCurrent={item.designation_source_current} canManage={item.can_designate} onSaved={refresh}/>}
      </article>)}
      <Button size="sm" type="button" variant="ghost" disabled={busy} onClick={() => void refresh()}>刷新里程碑</Button>
    </>}
  </section>;
}
