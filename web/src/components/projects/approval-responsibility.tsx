"use client";

import { useEffect, useState, useSyncExternalStore } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";
import { obj, rows, text, type Row } from "@/components/quality/fmea-sources";

type Kind = "execution" | "baseline" | "commitment";
const labels = { execution: "项目执行", baseline: "基线变更", commitment: "节点承诺" };
const suffixes = { execution: "/policies", baseline: "/baseline-changes/policies", commitment: "/commitments/policies" };
type Draft = { request_id: string; expected_version: number; approver_user_id: string; authority_basis: string; four_eyes?: boolean };
function subscribe(callback: () => void) { window.addEventListener("popstate", callback); return () => window.removeEventListener("popstate", callback); }
function location() { const p = new URLSearchParams(window.location.search); return `${p.get("approval_policy_kind") ?? ""}:${p.get("approval_policy_id") ?? ""}`; }
export function ApprovalResponsibilityLanding({ projectId }: { projectId: string }) {
  const target = useSyncExternalStore(subscribe, location, () => ""), [kind, id] = target.split(":");
  if (!(kind === "execution" || kind === "baseline" || kind === "commitment") || !id || !/^[0-9a-f-]{36}$/.test(id)) return null;
  return <ApprovalResponsibility key={`${projectId}:${kind}:${id}`} projectId={projectId} kind={kind} policyId={id} />;
}

async function readPolicy(base: string, before?: number) {
    const response = await fetch(`${base}${before ? `?before_version=${before}` : ""}`, { cache: "no-store" });
    const value: unknown = await responseBody(response);
    if (!response.ok || !isRecord(value) || !isRecord(value.selected) || !isRecord(value.current) || !Array.isArray(value.history) || !Array.isArray(value.members)) throw new Error(isRecord(value) && isRecord(value.detail) ? text(value.detail.message) : "批准责任读取失败");
    return value;
  }

function ApprovalResponsibility({ projectId, kind, policyId }: { projectId: string; kind: Kind; policyId: string }) {
  const base = `/api/projects/${projectId}/execution/approval-responsibilities/${kind}/${policyId}`;
  const [data, setData] = useState<Row | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [user, setUser] = useState(""), [basis, setBasis] = useState("");
  const [preview, setPreview] = useState<Draft | null>(null), [pending, setPending] = useState<Draft | null>(null);
  const [result, setResult] = useState<Row | null>(null);

  useEffect(() => { let active = true; void readPolicy(base).then(value => { if (active) setData(value); }, e => { if (active) setError(e instanceof Error ? e.message : "读取失败"); }); return () => { active = false; };
  }, [base]);
  async function refresh(before?: number) {
    setBusy(true); setError("");
    try { const value = await readPolicy(base,before); setData(old => before && old ? { ...old, people: {...obj(old.people),...obj(value.people)}, history: [...rows(old.history), ...rows(value.history)], next_before_version: value.next_before_version } : value); }
    catch (e) { setError(e instanceof Error ? e.message : "读取失败"); } finally { setBusy(false); }
  }
  async function publish(body: Draft) {
    setBusy(true); setPending(body); setError("");
    try {
      const response = await fetch(`/api/projects/${projectId}/execution${suffixes[kind]}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const value: unknown = await responseBody(response);
      if (!response.ok) {
        if ([400, 401, 403, 404, 409, 422].includes(response.status)) { setPreview(null); setPending(null); }
        throw new Error(isRecord(value) && isRecord(value.detail) ? text(value.detail.message) : "发布结果未确认，请按原请求重试");
      }
      if (!isRecord(value) || typeof value.id !== "string" || value.request_id !== body.request_id) throw new Error("回执不完整，请按原请求重试");
      setResult(value); setPreview(null); setPending(null); await refresh();
    } catch (e) { setError(e instanceof Error ? e.message : "发布失败"); } finally { setBusy(false); }
  }
  const selected = obj(data?.selected), current = obj(data?.current), people = obj(data?.people);
  const name = (id: unknown) => text(people[text(id)]) || `历史成员 ${text(id).slice(0, 8)}`;
  const href = (id: unknown) => `/projects?project=${projectId}&tab=overview&approval_policy_kind=${kind}&approval_policy_id=${text(id)}`;
  const locked = busy || !!preview || !!pending;
  return <section className="space-y-3 rounded-lg border p-4" aria-label="批准责任接续">
    <h3 className="font-semibold">{labels[kind]}批准责任接续</h3>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {!data && !error && <p className="text-sm">正在读取原授权…</p>}
    {data && <>
      <p className="text-sm">移交记录：政策 v{text(selected.version)} · {name(selected.approver_user_id)}</p>
      <p className="whitespace-pre-wrap text-sm">原授权依据：{text(selected.authority_basis)}</p>
      <p className="text-xs">发布人：{name(selected.created_by_user_id)} · {text(selected.created_at)}</p>
      <p className="text-sm">当前政策 v{text(current.version)} · {name(current.approver_user_id)}</p>
      {current.id !== policyId && <a className="text-sm text-primary underline" href={href(current.id)}>此记录已有后续政策，打开当前政策办理</a>}
      <p className="text-sm text-muted-foreground">{kind === "commitment" ? "新政策用于后续承诺确认，已有节点期限和原具名确认继续保留。" : "新政策用于后续申请，原申请、批准签名和正式应用保留。待办需沿原流程撤回或按新政策续提，重新批准后独立应用。"}{kind !== "commitment" && ` 本次保留原分工要求：${selected.four_eyes ? "申请与批准分人办理" : "允许同人申请批准"}。`}</p>
      {!!rows(data.pending).length && <div className="rounded-md border p-3 text-xs"><p>原政策有 {data.pending_has_more ? "超过100" : rows(data.pending).length} 项未应用或尚无裁决的申请（仍须核对当前依据）：</p>{rows(data.pending).map(item => <p className="mt-2 break-all" key={text(item.id)}>{text(item.reason)} · <a className="text-primary underline" href={`/projects?project=${projectId}&tab=overview&approval_request_kind=${kind}&approval_request_id=${text(item.id)}`}>打开原申请办理</a></p>)}</div>}
      {data.can_configure === true && <form className="space-y-3" onSubmit={e => { e.preventDefault(); setPreview({ request_id: crypto.randomUUID(), expected_version: Number(selected.version), approver_user_id: user, authority_basis: basis.trim(), ...(kind !== "commitment" ? { four_eyes: selected.four_eyes === true } : {}) }); }}>
        <fieldset disabled={locked} className="space-y-3"><label className="block text-sm">接手批准人<select required className="mt-1 w-full rounded-md border bg-background p-2" value={user} onChange={e => setUser(e.target.value)}><option value="">选择已有项目办理权限的人员</option>{rows(data.members).filter(m => m.id !== selected.approver_user_id).map(m => <option key={text(m.id)} value={text(m.id)}>{text(m.display_name)}</option>)}</select></label>
          <label className="block text-sm">本次组织授权依据<textarea required maxLength={2048} className="mt-1 w-full rounded-md border bg-background p-2" value={basis} onChange={e => setBasis(e.target.value)} /></label>
          <Button size="sm" disabled={!user || !basis.trim()}>预览新授权</Button>
        </fieldset>
      </form>}
      {(preview || pending) && <div className="space-y-2 rounded-md border p-3 text-sm"><p>发布政策 v{(preview ?? pending)!.expected_version + 1} · 接手人：{rows(data.members).find(m => m.id === (preview ?? pending)!.approver_user_id)?.display_name as string}</p><p className="whitespace-pre-wrap">{(preview ?? pending)!.authority_basis}</p><Button size="sm" disabled={busy} onClick={() => void publish((pending ?? preview)!)}>{pending ? "按原请求重试" : "确认发布授权版本"}</Button>{!pending && <Button size="sm" variant="ghost" disabled={busy} onClick={() => setPreview(null)}>返回修改</Button>}</div>}
      {result && <p role="status" className="text-sm">新政策 v{text(result.version)} 已发布，原审批记录保留。<a className="ml-2 text-primary underline" href={href(result.id)}>查看接手人的政策</a></p>}
      <details><summary className="cursor-pointer text-sm">授权版本历史</summary>{rows(data.history).map(h => <article key={text(h.id)} className="mt-2 rounded border p-2 text-xs"><p>v{text(h.version)} · {name(h.approver_user_id)} · 发布人 {name(h.created_by_user_id)}</p><p className="whitespace-pre-wrap">{text(h.authority_basis)}</p><a className="text-primary underline" href={href(h.id)}>查看此版本与待办</a></article>)}{typeof data.next_before_version === "number" && <Button size="sm" variant="outline" disabled={locked} onClick={() => void refresh(data.next_before_version as number)}>更早授权</Button>}</details>
    </>}
    <Button size="sm" variant="outline" disabled={locked} onClick={() => void refresh()}>刷新政策与待办</Button>
  </section>;
}
