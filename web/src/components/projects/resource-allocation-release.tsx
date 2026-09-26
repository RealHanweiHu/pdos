"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";

type Source = { id: string; code: string; name: string; resource_type: string; status: string; assigned_user_id: string | null; start_date: string | null; end_date: string | null; allocation_percent: string; details: Record<string, unknown> };
type Mapping = { id: string; sequence: number; disposition: string; basis: string; window_start: string | null; window_end: string | null; parallel_units: string | null; source_snapshot: Source };
type History = { id: number; created_at: string; actor_user_id: string; before_snapshot: { source: Source; reconciliation: Mapping | null }; after_snapshot: Mapping; context: { reason: string; people: Record<string, string> } };
type Data = { source: Source; source_digest: string; assigned_name: string | null; sequence: number; reconciliation: Mapping | null; can_release: boolean; history: History[]; next_before_id: number | null };
type Command = { request_id: string; source_digest: string; expected_sequence: number; reason: string };
const statuses: Record<string, string> = { planned: "计划中", active: "有效占用", released: "已释放" };
const types: Record<string, string> = { person: "人员", equipment: "设备", facility: "设施", capability: "能力" };
function errorMessage(value: unknown) { return isRecord(value) && isRecord(value.detail) && typeof value.detail.message === "string" ? value.detail.message : "原分配暂不可读取，请稍后重试"; }
function SourceSummary({ source }: { source: Source }) {
  return <div className="space-y-1"><p>{source.code} · {source.name} · {types[source.resource_type]} · {statuses[source.status]}</p><p>原分配比例 {source.allocation_percent}% · {source.start_date ?? "开始日期未知"} 至 {source.end_date ?? "结束日期未知"}</p><details><summary className="cursor-pointer text-xs">原分配详细说明</summary><pre className="whitespace-pre-wrap break-words text-xs">{JSON.stringify(source.details, null, 2)}</pre></details></div>;
}
export function ResourceAllocationLanding({ projectId }: { projectId: string }) {
  const id = useSearchParams().get("resource_allocation_id");
  if (!id || !/^[0-9a-f-]{36}$/i.test(id)) return null;
  return <ResourceAllocationRelease key={`${projectId}:${id}`} projectId={projectId} resourceId={id}/>;
}
function ResourceAllocationRelease({ projectId, resourceId }: { projectId: string; resourceId: string }) {
  const base = `/api/projects/${projectId}/resource-inventory/${resourceId}/release`;
  const [data, setData] = useState<Data | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [reason, setReason] = useState(""), [preview, setPreview] = useState<Command | null>(null), [pending, setPending] = useState<Command | null>(null), [receipt, setReceipt] = useState("");
  async function read(before?: number): Promise<Data> {
    const response = await fetch(`${base}${before ? `?before_id=${before}` : ""}`, { cache: "no-store" });
    const value = await responseBody(response);
    if (!response.ok) throw new Error(errorMessage(value));
    if (!isRecord(value) || !isRecord(value.source) || value.source.id !== resourceId || typeof value.source_digest !== "string" || !Array.isArray(value.history)) throw new Error("返回的原分配与本次办理对象不一致");
    return value as Data;
  }
  useEffect(() => {
    let active = true;
    void fetch(base, { cache: "no-store" }).then(async response => {
      const value = await responseBody(response);
      if (!response.ok) throw new Error(errorMessage(value));
      if (!isRecord(value) || !isRecord(value.source) || value.source.id !== resourceId || typeof value.source_digest !== "string" || !Array.isArray(value.history)) throw new Error("原分配回执不完整");
      if (active) setData(value as Data);
    }).catch(e => { if (active) setError(e instanceof Error ? e.message : "读取失败"); });
    return () => { active = false; };
  }, [base, resourceId]);
  async function refresh(before?: number) {
    setBusy(true); setError("");
    try { const value = await read(before); setData(old => before && old ? { ...old, history: [...old.history, ...value.history.filter(row => !old.history.some(prior => prior.id === row.id))], next_before_id: value.next_before_id } : value); }
    catch (e) { setError(e instanceof Error ? e.message : "读取失败"); }
    finally { setBusy(false); }
  }
  async function save(command: Command) {
    setBusy(true); setError(""); setPending(command);
    try {
      const response = await fetch(base, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(command) });
      const value = await responseBody(response);
      if (!response.ok) {
        if ([400, 401, 403, 404, 409, 422].includes(response.status)) { setPending(null); setPreview(null); }
        throw new Error(errorMessage(value));
      }
      if (!isRecord(value) || value.request_id !== command.request_id || typeof value.audit_id !== "number" || !isRecord(value.reconciliation) || value.reconciliation.legacy_resource_id !== resourceId || value.reconciliation.disposition !== "retained_released") throw new Error("释放结果待确认，请按原请求重试");
      setReceipt(`原分配已释放，盘点回执 ${value.audit_id}。原人员和分配依据保留。`);
      setPending(null); setPreview(null); setReason(""); setData(await read());
    } catch (e) { setError(e instanceof Error ? e.message : "释放结果待确认"); }
    finally { setBusy(false); }
  }
  const locked = busy || !!preview || !!pending;
  return <section className="mb-4 space-y-3 rounded-md border p-4 text-sm"><h3 className="font-medium">原资源分配与释放</h3>
    {error && <p role="alert" className="text-destructive">{error}</p>}{receipt && <p role="status">{receipt}</p>}
    {!data && !error && <p role="status">正在读取原分配和盘点依据…</p>}
    <Button size="sm" variant="outline" disabled={locked || !!reason} onClick={() => void refresh()}>刷新原分配</Button>
    {data && <><SourceSummary source={data.source}/><p>原分配人员：{data.assigned_name ?? "未指定"} · 盘点版本 {data.sequence}</p>
      {data.reconciliation && <div className="space-y-1 rounded-md bg-muted p-2"><p>{data.reconciliation.disposition === "mapped" ? "原盘点已计入共享资源容量" : "原盘点保留释放历史"}</p>{data.reconciliation.window_start && <p>{data.reconciliation.window_start} — {data.reconciliation.window_end} · {data.reconciliation.parallel_units} 单位</p>}<p className="whitespace-pre-wrap">盘点依据：{data.reconciliation.basis}</p></div>}
      <p>结束此条分配后，该记录退出当前容量占用；原人员、日期、比例和盘点历史保留。其他预约、任务及承诺分别办理。接手人的新占用请在本页资源预约中按实际资源、时间及容量建立。</p>
      {data.can_release && <fieldset disabled={locked} className="space-y-2"><label className="block">结束原分配的实际依据<textarea maxLength={2048} className="mt-1 w-full rounded-md border bg-background p-2" value={reason} onChange={e => setReason(e.target.value)} /></label><Button size="sm" disabled={!reason.trim()} onClick={() => setPreview({ request_id: crypto.randomUUID(), source_digest: data.source_digest, expected_sequence: data.sequence, reason: reason.trim() })}>预览释放原分配</Button><Button size="sm" variant="ghost" onClick={() => setReason("")}>清除输入</Button></fieldset>}
      {preview && !pending && <div className="space-y-2 rounded-md border p-3"><p>将结束“{data.source.name}”这条{statuses[data.source.status]}记录，并保存盘点 v{preview.expected_sequence + 1} 的释放回执。</p><p className="whitespace-pre-wrap">{preview.reason}</p><Button size="sm" disabled={busy} onClick={() => void save(preview)}>确认释放并保留历史</Button><Button size="sm" variant="ghost" disabled={busy} onClick={() => setPreview(null)}>返回修改</Button></div>}
      {pending && <div className="space-y-2"><p className="break-all">请求 {pending.request_id} 的结果待确认。</p><Button size="sm" disabled={busy} onClick={() => void save(pending)}>按原请求重试</Button></div>}
      <details><summary className="cursor-pointer">释放办理历史</summary><div className="mt-2 space-y-3">{data.history.map(row => <article className="space-y-2 rounded-md border p-2" key={row.id}><p>{new Date(row.created_at).toLocaleString()} · 办理人 {row.context.people[row.actor_user_id] ?? row.actor_user_id}</p><p>原分配人员：{row.context.people[row.before_snapshot.source.assigned_user_id ?? ""] ?? "未指定"}</p><SourceSummary source={row.before_snapshot.source}/><p className="whitespace-pre-wrap">{row.context.reason}</p><p>释放盘点 v{row.after_snapshot.sequence}</p></article>)}{!data.history.length && <p>暂无释放记录。</p>}{data.next_before_id && <Button size="sm" variant="outline" disabled={locked} onClick={() => void refresh(data.next_before_id ?? undefined)}>加载更早记录</Button>}</div></details>
    </>}
  </section>;
}
