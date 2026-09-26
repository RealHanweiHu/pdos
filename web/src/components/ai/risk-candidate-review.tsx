"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { IssueRiskWorkCard } from "@/components/my-work/issue-risk-work-card";
import { isRecord } from "@/components/workspace-api";
import { dismissRiskCandidate, unconfirmRiskCandidate } from "./ai-api";
import type { RiskCandidate } from "./ai-types";
import { riskBatch, RiskBatchError, rescanRiskCandidates, type RiskBatchReceipt, type RiskBatchRequest } from "./risk-candidate-batch-api";

type Group = {
  projectId: string; requestId: string; request?: RiskBatchRequest;
  receipt?: RiskBatchReceipt; state: "pending" | "done" | "failed"; error?: string;
};
const button = "min-h-11 rounded-lg border px-3 text-xs disabled:opacity-50 sm:min-h-8";
const message = (error: unknown) => error instanceof Error ? error.message : "操作失败，请稍后重试";
// Normalize UTC rendering without discarding PostgreSQL microseconds.
const normalizedTime = (value: string) => value.replace(/(?:\.(\d+))?(?:Z|\+00:00)$/, (_match, fraction: string | undefined) => `.${(fraction ?? "").padEnd(6, "0")}Z`);
const sameTime = (a: string, b: string) => normalizedTime(a) === normalizedTime(b);
function undoable(receipt: RiskBatchReceipt) {
  return receipt.results.filter((item) => receipt.current.some((current) =>
    current.id === item.risk_id && current.draft_state === "confirmed" && current.status === "open" && sameTime(current.updated_at, item.updated_at)));
}
function remember(groups: Group[]) {
  const url = new URL(window.location.href);
  const refs = [...new Set([...url.searchParams.getAll("risk_batch"), ...groups.map((group) => `${group.projectId}:${group.requestId}`)])];
  url.searchParams.delete("risk_batch");
  for (const ref of refs.slice(-20)) url.searchParams.append("risk_batch", ref);
  window.history.replaceState(window.history.state, "", url);
}

export function RiskCandidateReview({ actorKey, candidatesByProject, projectNames, refreshing = false, onNotice, onRefresh }: {
  actorKey?: string;
  candidatesByProject: Record<string, RiskCandidate[]>; projectNames: Record<string, string>; refreshing?: boolean;
  onNotice: (notice: { status?: string; error?: string }) => void; onRefresh: () => Promise<void>;
}) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [preview, setPreview] = useState<RiskCandidate[] | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [groups, setGroups] = useState<Group[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const busy = submitting || refreshing;
  const candidates = Object.values(candidatesByProject).flat();
  const pendingProjects = new Set(groups.filter((group) => group.state === "pending").map((group) => group.projectId));
  const pending = candidates.some((item) => selected.has(item.id) && pendingProjects.has(item.project_id));
  const validIds = new Set(candidates.map((item) => item.id));
  const selectedCount = [...selected].filter((id) => validIds.has(id)).length;

  function saveRequest(group: Group) {
    if (!actorKey || !group.request) return;
    try { sessionStorage.setItem(`risk-batch:${actorKey}:${group.requestId}`, JSON.stringify({ projectId: group.projectId, request: group.request })); }
    catch { onNotice({ error: "本页仍可用原请求重试；浏览器无法保存恢复资料，离开页面后只能凭编号回查" }); }
  }
  function update(id: string, patch: Partial<Group>) {
    setGroups((current) => current.map((group) => group.requestId === id ? { ...group, ...patch } : group));
  }
  useEffect(() => {
    let active = true;
    const refs = [...new Set(new URL(window.location.href).searchParams.getAll("risk_batch"))].slice(-20)
      .filter((value) => /^[a-f0-9-]{36}:[a-f0-9-]{36}$/i.test(value));
    if (!refs.length) return;
    void Promise.all(refs.map(async (value): Promise<Group> => {
      const [projectId, requestId] = value.split(":");
      let request: RiskBatchRequest | undefined;
      try {
        const saved: unknown = JSON.parse(actorKey ? sessionStorage.getItem(`risk-batch:${actorKey}:${requestId}`) ?? "null" : "null");
        if (isRecord(saved) && saved.projectId === projectId && isRecord(saved.request) && saved.request.request_id === requestId &&
          Array.isArray(saved.request.items) && saved.request.items.length > 0 && saved.request.items.length <= 200 &&
          saved.request.items.every((item) => isRecord(item) && typeof item.risk_id === "string" && typeof item.expected_updated_at === "string")) {
          request = { request_id: requestId, items: saved.request.items as RiskBatchRequest["items"] };
        }
      } catch { /* The server receipt remains available without browser recovery data. */ }
      try { return { projectId, requestId, request, state: "done", receipt: await riskBatch(projectId, requestId) }; }
      catch (error) { return { projectId, requestId, request, state: "pending", error: message(error) }; }
    })).then((restored) => { if (active) setGroups((current) => [...restored.filter((r) => !current.some((g) => g.requestId === r.requestId)), ...current]); });
    return () => { active = false; };
  }, [actorKey]);

  async function refresh() {
    try { await onRefresh(); }
    catch (error) { onNotice({ error: `办理结果已保留；待办刷新失败：${message(error)}` }); }
  }
  async function send(group: Group, replay = false) {
    if (!group.request) return;
    try {
      const receipt = await riskBatch(group.projectId, group.request);
      update(group.requestId, { state: "done", receipt, error: undefined });
      setSelected((current) => new Set([...current].filter((id) => !receipt.results.some((item) => item.risk_id === id))));
    } catch (error) {
      const rejected = error instanceof RiskBatchError && (replay ? [409, 422] : [400, 401, 403, 404, 409, 422]).includes(error.status);
      update(group.requestId, { state: rejected ? "failed" : "pending", error: message(error) });
    }
  }
  async function confirm() {
    if (!preview?.length || preview.some((item) => !item.updated_at)) return;
    if (preview.some((item) => pendingProjects.has(item.project_id))) return;
    const byProject = new Map<string, RiskCandidate[]>();
    for (const item of preview) byProject.set(item.project_id, [...(byProject.get(item.project_id) ?? []), item]);
    const next = [...byProject].map(([projectId, items]): Group => {
      const requestId = crypto.randomUUID();
      return { projectId, requestId, state: "pending", request: {
        request_id: requestId, items: items.map((item) => ({ risk_id: item.id, expected_updated_at: item.updated_at! })),
      } };
    });
    setSubmitting(true); onNotice({});
    for (const group of next) saveRequest(group);
    setGroups((current) => [...current, ...next]); remember([...groups, ...next]);
    setPreview(null);
    try { for (const group of next) await send(group); await refresh(); }
    finally { setSubmitting(false); }
  }
  async function recover(group: Group, retry: boolean) {
    setSubmitting(true);
    try {
      if (retry) await send(group, true);
      else {
        const receipt = await riskBatch(group.projectId, group.requestId);
        update(group.requestId, { state: "done", receipt, error: undefined });
      }
      await refresh();
    } catch (error) { update(group.requestId, { error: `${message(error)}；未查到不代表请求未提交，可继续回查` }); }
    finally { setSubmitting(false); }
  }
  async function undo(group: Group) {
    if (!group.receipt) return;
    setSubmitting(true); onNotice({});
    const failures: string[] = [];
    let count = 0;
    try {
      for (const item of undoable(group.receipt)) {
        try {
          await unconfirmRiskCandidate(group.projectId, item.risk_id, item.updated_at);
          count++;
          setGroups((current) => current.map((g) => g.requestId !== group.requestId || !g.receipt ? g : {
            ...g, receipt: { ...g.receipt, current: g.receipt.current.map((r) => r.id === item.risk_id ? { ...r, draft_state: "draft" } : r) },
          }));
        } catch (error) { failures.push(`${item.title}：${message(error)}`); }
      }
      try { update(group.requestId, { receipt: await riskBatch(group.projectId, group.requestId), error: failures.join("；") || undefined }); }
      catch (error) { update(group.requestId, { error: [...failures, `请回查最新结果：${message(error)}`].join("；") }); }
      onNotice({ status: `本次已撤销 ${count} 条确认；各项当前状态见回执` });
      await refresh();
    } finally { setSubmitting(false); }
  }
  async function rescan(projectId: string) {
    setSubmitting(true); onNotice({});
    try { await rescanRiskCandidates(projectId); setPreview(null); await onRefresh(); onNotice({ status: "已按当前来源更新草稿，请重新核对确认" }); }
    catch (error) { onNotice({ error: message(error) }); }
    finally { setSubmitting(false); }
  }
  return <section aria-label="规则风险候选" className="rounded-lg border bg-card p-4">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <div><h2 className="text-sm font-semibold">规则风险候选（自由区草稿）</h2>
        <p className="mt-1 text-xs text-muted-foreground">未确认前不进入风险列表。同项目一起提交，各项目分别保存确认结果。</p></div>
      <div className="flex gap-2">
        <button className={button} aria-expanded={expanded} onClick={() => setExpanded(!expanded)} type="button">{expanded ? "收起候选" : `展开候选（${candidates.length}）`}</button>
        <button className={button} disabled={busy || pending || !selectedCount} onClick={() => setPreview(candidates.filter((item) => selected.has(item.id)))} type="button">批量确认（{selectedCount}）</button>
      </div>
    </div>
    {groups.some((group) => group.state === "pending") ? <p className="mt-2 text-xs text-muted-foreground">有项目结果待回查，请先处理原请求；其他项目可继续办理。当前链接保留最近20组回查编号。</p> : null}
    {expanded ? <div className="mt-3 max-h-96 space-y-3 overflow-y-auto">
      {Object.entries(candidatesByProject).map(([projectId, items]) => <div key={projectId}>
        <div className="mb-2 flex items-center justify-between"><span className="text-xs font-medium">{projectNames[projectId] ?? "项目"}</span><button className={button} disabled={busy} onClick={() => void rescan(projectId)} type="button">重新扫描</button></div>
        <ul className="space-y-2">{items.map((item) => <li className="flex items-center gap-3 rounded-lg border p-2" key={item.id}>
          <input aria-label={`选择候选 ${item.title}`} type="checkbox" disabled={busy} checked={selected.has(item.id)} onChange={() => setSelected((current) => { const next = new Set(current); if (next.has(item.id)) next.delete(item.id); else next.add(item.id); return next; })} />
          <div className="min-w-0 flex-1"><p className="text-sm">{item.title}</p><p className="text-xs text-muted-foreground">可能性 {item.likelihood} × 影响 {item.impact} = 分值 {item.score}</p></div>
          <button className={button} disabled={busy} type="button" onClick={() => {
            setSubmitting(true); onNotice({});
            void dismissRiskCandidate(projectId, item.id).then(async () => { onNotice({ status: "候选已忽略" }); await refresh(); }).catch((error) => onNotice({ error: message(error) })).finally(() => setSubmitting(false));
          }}>忽略</button>
        </li>)}</ul>
      </div>)}
    </div> : null}
    {preview ? <div role="dialog" aria-label="批量确认预览" className="mt-3 rounded-lg border border-primary/40 bg-primary/5 p-3">
      <h3 className="text-sm font-semibold">确认前预览（{preview.length} 条将写入风险列表）</h3>
      <ul className="my-3 space-y-2 text-xs">{preview.map((item) => <li key={item.id}><strong>{projectNames[item.project_id] ?? "项目"} · {item.title}</strong><p>草稿 → 已确认；L{item.likelihood}×I{item.impact}={item.score}；{item.description}</p></li>)}</ul>
      {preview.some((item) => !item.updated_at) ? <p role="alert" className="text-xs text-destructive">候选缺少读取版本，请刷新后重新核对。</p> : null}
      <p className="mb-3 text-xs text-muted-foreground">提交时复核当前来源及所读版本；项目内任一项变化，该项目整组不提交。每项目最多200条。</p>
      <div className="flex gap-2"><button className={button} disabled={busy || pending || preview.some((item) => !item.updated_at)} onClick={() => void confirm()} type="button">确认写入</button><button className={button} disabled={busy} onClick={() => setPreview(null)} type="button">取消</button></div>
    </div> : null}
    {groups.length ? <div aria-label="风险批量确认回执" className="mt-4 space-y-3">
      {groups.map((group) => <div key={group.requestId} className="rounded-lg border p-3 text-xs">
        <p className="font-semibold">{projectNames[group.projectId] ?? "项目"} · {group.state === "done" ? `已确认 ${group.receipt?.results.length ?? 0} 条` : group.state === "failed" ? "本组未提交，请核对后重新选择" : "结果待回查"}</p>
        <p className="mt-1 break-all text-muted-foreground">请求编号：{group.requestId}</p>
        {group.receipt ? <><p className="mt-1 text-muted-foreground">原确认时间：{new Date(group.receipt.created_at).toLocaleString("zh-CN")} · 原确认记录保留</p>
          <ul className="my-2 space-y-1">{group.receipt.results.map((item) => {
            const current = group.receipt!.current.find((value) => value.id === item.risk_id);
            const label = !current ? "当前对象不可用" : current.draft_state === "draft" ? "当前已退回草稿" : current.draft_state === "cleared" ? "当前候选已清除" : sameTime(current.updated_at, item.updated_at) ? "确认后未修改" : "确认后已有新办理";
            return <li key={item.risk_id}><Link className="underline" href={`/projects?project=${group.projectId}&tab=work-items&entity_id=${item.risk_id}`}>{item.title}</Link> · 原分值 {item.score} · {label}<IssueRiskWorkCard projectId={group.projectId} itemId={item.risk_id} kind="risks" onNotice={(status) => onNotice({ status })} onChanged={async () => { update(group.requestId, { receipt: await riskBatch(group.projectId, group.requestId) }); await refresh(); }} /></li>;
          })}</ul></> : null}
        {group.error ? <p role="alert" className="my-2 text-destructive">{group.error}</p> : null}
        <div className="mt-2 flex flex-wrap gap-2">
          <button className={button} disabled={busy} onClick={() => void recover(group, false)} type="button">回查结果</button>
          {group.state === "pending" && group.request ? <button className={button} disabled={busy} onClick={() => void recover(group, true)} type="button">用原请求重试</button> : null}
          {group.state === "failed" ? <button className={button} disabled={busy} onClick={() => void rescan(group.projectId)} type="button">重新扫描候选</button> : null}
          {group.receipt && undoable(group.receipt).length ? <button className={button} disabled={busy} onClick={() => void undo(group)} type="button">撤销本组未变更的确认（{undoable(group.receipt).length}）</button> : null}
        </div>
      </div>)}
    </div> : null}
  </section>;
}
