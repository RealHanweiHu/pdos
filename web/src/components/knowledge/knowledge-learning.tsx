"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";

const states = { pending: "待整理", created: "已生成待审草稿", duplicate: "已有经验候选", skipped: "未生成候选", failed: "整理失败" };
const kinds = { issue: "问题关闭", decision: "业务决策", test_review: "测试报告审核", project_retrospective: "项目复盘", root_cause: "已批准根因", effectiveness_review: "整改有效性复核" };
const reasons: Record<string, string> = {
  quality_source_unavailable: "原质量结论不可用或尚未具名确认",
  quality_source_changed: "原根因已替代或有效性已有后续复核，请查看当前版本",
  quality_evidence_changed: "依据在原质量结论之后已被修改，需重新核对原版本，不能用当前值替代当时依据",
  quality_evidence_unavailable: "原结果证据缺失、未确认或已失效，请沿质量记录补证",
  nothing_learned: "未记录可提炼的根因或解决方案",
  decision_has_no_learning_basis: "缺少决策选择或理由",
  test_review_has_no_approved_summary: "尚无已审核的测试结论",
  retrospective_version_superseded: "复盘结论已修订，旧版记录停止整理，请查看新版候选",
  retrospective_has_no_confirmed_conclusion: "复盘尚无已确认结论，会议排程和议题不能直接作为经验",
  source_requires_manual_curation: "原记录较长，请人工整理并保留出处",
  awaiting_knowledge_review: "草稿等待另一位有权限的成员审核后才能用于检索",
  already_captured: "此业务记录已有候选，沿用原记录",
};
function id(value: unknown): string {
  if (typeof value !== "string" || !/^[0-9a-f-]{36}$/.test(value)) throw new Error("经验整理记录不完整");
  return value;
}
function job(value: unknown) {
  if (!isRecord(value) || typeof value.state !== "string" || !Object.hasOwn(states, value.state)
    || typeof value.source_kind !== "string" || !Object.hasOwn(kinds, value.source_kind)
    || typeof value.source_version !== "number" || !Number.isSafeInteger(value.source_version) || value.source_version < 0
    || !Number.isInteger(value.attempts) || typeof value.attempts !== "number"
    || (value.reason !== null && typeof value.reason !== "string")) throw new Error("经验整理记录不完整");
  return { id: id(value.id), kind: value.source_kind as keyof typeof kinds, state: value.state as keyof typeof states,
    sourceVersion: value.source_version, memoryId: value.memory_id === null ? null : id(value.memory_id), attempts: value.attempts,
    title: typeof value.title === "string" && value.title ? value.title : "业务记录", reason: value.reason as string | null };
}
type Job = ReturnType<typeof job>;
async function request(path: string, post = false): Promise<unknown> {
  const response = await fetch(path, { method: post ? "POST" : "GET", cache: "no-store" });
  const value: unknown = await responseBody(response).catch(() => null);
  if (!response.ok) throw new Error(isRecord(value) && isRecord(value.detail) && typeof value.detail.message === "string"
    ? value.detail.message : "经验整理暂不可用，请刷新核对结果");
  return value;
}
function explain(item: Job): string {
  if (item.reason?.startsWith("capture_failed:")) return item.reason.endsWith("KnowledgeAccessError")
    ? "原记录办理人的项目资格或知识权限已变化，请先处理资格后再重试"
    : item.state === "pending" ? "本次整理失败，已保留记录等待重试" : "多次整理未完成，修复原因后可重试";
  return item.reason ? reasons[item.reason] ?? "需要人工核对来源记录" : "等待从原业务记录整理经验，不会自动发布";
}

export function KnowledgeLearning({ projectId, onChanged }: { projectId: string; onChanged: () => void }) {
  const [items, setItems] = useState<Job[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  const path = `/api/projects/${encodeURIComponent(projectId)}/knowledge-learning`;
  useEffect(() => {
    let active = true;
    request(path).then(value => {
      if (!isRecord(value) || !Array.isArray(value.items)) throw new Error("经验整理清单不完整");
      const parsed = value.items.map(job);
      if (active) setItems(parsed);
    }).catch(error => { if (active) setError(error instanceof Error ? error.message : "经验整理清单暂不可用"); });
    return () => { active = false; };
  }, [path, revision]);
  function refresh() { setItems(null); setError(null); setRevision(value => value + 1); }
  async function collect(item: Job) {
    setBusy(true); setError(null); setNotice(null);
    try {
      const result = await request(`${path}/${encodeURIComponent(item.id)}/collect`, true);
      if (!isRecord(result) || typeof result.state !== "string") throw new Error("处理结果不完整，请刷新核对");
      if (result.state === "idle") setNotice("记录正在由其他办理处理，或已不可用；请刷新核对。");
      else if (Object.hasOwn(states, result.state)) setNotice(states[result.state as keyof typeof states]);
      else throw new Error("处理结果不完整，请刷新核对");
      refresh();
      if (result.state === "created" || result.state === "duplicate") onChanged();
    } catch (error) { setError(error instanceof Error ? error.message : "本次整理未完成，请刷新核对结果"); }
    finally { setBusy(false); }
  }
  return <section className="mt-5 space-y-3 rounded-lg border bg-card p-4" aria-label="业务经验整理">
    <div className="flex flex-wrap items-center justify-between gap-2"><h2 className="font-semibold">从业务记录整理经验</h2><Button size="sm" variant="outline" disabled={busy} onClick={refresh}>刷新整理记录</Button></div>
    <p className="text-xs text-muted-foreground">展示最近 200 条。问题关闭、决策、已审核测试报告、已批准根因和有效性复核可生成待审草稿；无效整改同样保留。复盘须先确认结论，所有草稿仍须另一位成员审核。</p>
    {notice && <p role="status" className="text-sm">{notice}</p>}
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {!items && !error && <p className="text-sm text-muted-foreground">正在读取整理记录…</p>}
    {items?.length === 0 && <p className="text-sm text-muted-foreground">当前没有待整理的业务记录。</p>}
    {items && <ul className="space-y-2">{items.map(item => <li key={item.id} className="space-y-2 rounded-lg border p-3">
      <div className="flex flex-wrap justify-between gap-2"><h3 className="text-sm font-medium">{item.title}</h3><span className="text-xs">{states[item.state]}</span></div>
      <p className="text-xs text-muted-foreground">{kinds[item.kind]}{item.sourceVersion > 0 ? ` · 结论第 ${item.sourceVersion} 版` : ""} · 已尝试 {item.attempts} 次</p><p className="text-sm">{explain(item)}</p>
      {item.memoryId && <a className="text-sm text-primary underline" href={`/knowledge?project=${projectId}&memory=${item.memoryId}`}>查看候选与原始出处</a>}
      {(item.state === "pending" || item.state === "failed") && <Button size="sm" variant="outline" disabled={busy} onClick={() => void collect(item)}>{item.attempts ? "重新整理" : "整理为待审草稿"}</Button>}
    </li>)}</ul>}
  </section>;
}
