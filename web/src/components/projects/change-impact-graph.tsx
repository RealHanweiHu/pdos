"use client";

import { CostAlternativeEcrSource } from "./cost-alternatives";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord } from "@/components/workspace-api";

type Node = { test_case_id?:string|null; key: string; kind: string; kind_label: string; id: string; label: string; digest: string; facts: Record<string, unknown> };
type Edge = { source: string; target: string; label: string; evidence: Record<string, unknown> };
type Graph = { scope_revision?:number|null;analyzed_scope_revision?:number|null;scope_comparisons?:{kind:string;id:string;changed:boolean;analysis_comparison:string}[];nodes: Node[]; edges: Edge[]; as_of: string; depth: number; limits: string[]; gaps: { node: string; message: string }[]; unresolved: { kind: string; count: number | null; message: string }[]; professional_comparisons: { route_id: string; kind: string; source_id: string; revision: number; ready: boolean; comparison: string; reference_changes: { kind: string; id: string; changed: boolean }[] }[]; semantics: string; analysis_state: string; approved_at: string | null };
const factLabels: Record<string, string> = { code: "编号", version: "版本", revision_number: "资料版本", status: "状态", draft_state: "记录状态", part_number: "料号", bom_type: "BOM类型", quantity: "数量", unit: "单位", currency: "币种", unit_cost: "单位成本", amount: "金额", run_number: "测试序次", execution_time_precision: "实际日期精度", executed_at: "实际测试时间", valid_until: "有效期至", updated_at: "最后更新" };
const statuses: Record<string, string> = { approved: "已批准", approval: "待批准", impact_analysis: "影响分析中", request: "已提出", rejected: "已驳回", cancelled: "已取消", passed: "通过", failed: "失败", blocked: "受阻", confirmed: "已确认", draft: "草稿", planned: "已计划", in_progress: "执行中", pending: "待办理", completed: "已完成", open: "待处理", closed: "已关闭", verified: "已验证", unknown: "未知", day: "日期", instant: "时刻" };
function href(node: Node, projectId: string): string | null {
  const base = `/projects?project=${projectId}`;
  if (node.kind === "ecr") return `${base}&tab=engineering#ecr-${node.id}`;
  if (node.kind === "bom") return `${base}&tab=engineering#bom-${node.id}`;
  if (node.kind === "specification") return `${base}&tab=engineering#spec-${node.id}`;
  if (node.kind === "test_case") return `${base}&tab=quality&test_case_id=${node.id}`;
  if (node.kind === "test_run" && node.test_case_id) return `${base}&tab=quality&test_case_id=${node.test_case_id}&test_run_id=${node.id}`;
  if (node.kind === "document") return `${base}&tab=documents&entity_id=${node.id}`;
  return null;
}
function pathTo(key: string, nodes: Node[], edges: Edge[], root: string): { node: Node; via?: string }[] {
  const byId = new Map(nodes.map(n => [n.key, n]));
  const parents = new Map<string, { key: string; label: string }>();
  const visited = new Set([root]), queue = [root];
  for (let i = 0; i < queue.length && !visited.has(key); i++) {
    for (const edge of edges) {
      const next = edge.source === queue[i] ? edge.target : edge.target === queue[i] ? edge.source : null;
      if (!next || visited.has(next)) continue;
      visited.add(next); parents.set(next, { key: queue[i], label: edge.label }); queue.push(next);
    }
  }
  if (!visited.has(key)) return [];
  const path: { node: Node; via?: string }[] = [];
  let cursor = key;
  while (byId.has(cursor)) { const parent = parents.get(cursor); path.push({ node: byId.get(cursor)!, via: parent?.label }); if (!parent) break; cursor = parent.key; }
  return path.reverse();
}
export function ChangeImpactGraph({ projectId, ecrId }: { projectId: string; ecrId: string }) {
  const [data, setData] = useState<Graph | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null);
  const [depth, setDepth] = useState(3), [filter, setFilter] = useState(""), [visible, setVisible] = useState(60), [selected, setSelected] = useState(`ecr:${ecrId}`);
  async function load(nextDepth = depth) {
    setBusy(true); setError(null);
    try {
      const response = await fetch(`/api/projects/${projectId}/changes/ecrs/${ecrId}/impact-graph?depth=${nextDepth}`, { cache: "no-store" });
      const value: unknown = await response.json();
      if (!response.ok || !isRecord(value) || !Array.isArray(value.nodes) || !Array.isArray(value.edges)) throw new Error(isRecord(value) && isRecord(value.detail) && typeof value.detail.message === "string" ? value.detail.message : "关系资料读取失败，请重试");
      setData(value as unknown as Graph); setDepth(nextDepth);
    } catch (e) { setError(e instanceof Error ? e.message : "读取失败"); } finally { setBusy(false); }
  }
  const nodeMap = new Map(data?.nodes.map(n => [n.key, n]) ?? []), current = nodeMap.get(selected);
  const matches = data?.nodes.filter(n => !filter || `${n.kind_label} ${n.label}`.toLowerCase().includes(filter.toLowerCase())) ?? [];
  const path = data && current ? pathTo(current.key, data.nodes, data.edges, `ecr:${ecrId}`) : [];
  const links = data?.edges.filter(e => e.source === selected || e.target === selected) ?? [];
  return <details className="my-3 rounded-md border p-3" onToggle={event => { if (event.currentTarget.open && !data && !busy) void load(); }}><summary className="cursor-pointer text-sm font-medium">追溯变更关联与待核对范围</summary><div className="mt-3 space-y-3 text-xs">
    <p className="text-muted-foreground">按实际资料关联查看潜在影响路径，结合原批准范围安排复验、复审和复认证。</p>
    {error && <p role="alert" className="text-destructive">{error}</p>}
    <div className="flex flex-wrap items-center gap-2"><Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void load()}>刷新当前关系</Button>{depth < 6 && <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void load(depth + 1)}>再展开一层关联</Button>}{busy && <span role="status">正在读取…</span>}</div>
    {data && <>
      <p>读取时间：{new Date(data.as_of).toLocaleString()} · 展开 {data.depth} 层 · {data.nodes.length} 个对象 / {data.edges.length} 条引用</p><p className="text-muted-foreground">{data.semantics}</p>
      {!!data.limits.length && <p className="text-primary">范围提示：{data.limits.join("；")}。当前展示不能当作全量影响范围。</p>}
      <div className="grid gap-3 lg:grid-cols-[minmax(12rem,1fr)_minmax(0,2fr)]"><div className="space-y-2"><label className="block">查找已读取对象<input className="mt-1 w-full rounded-md border bg-background p-2" value={filter} placeholder="名称、料号或对象类别" onChange={e => { setFilter(e.target.value); setVisible(60); }} /></label><ul className="max-h-80 space-y-1 overflow-y-auto">{matches.slice(0, visible).map(n => <li key={n.key}><button type="button" aria-pressed={selected === n.key} className={`w-full rounded-md p-2 text-left ${selected === n.key ? "bg-muted font-medium" : "hover:bg-muted"}`} onClick={() => setSelected(n.key)}>{n.kind_label} · {n.label}</button></li>)}</ul>{matches.length > visible && <Button type="button" size="sm" variant="outline" onClick={() => setVisible(visible + 60)}>更多对象</Button>}</div>
        <div className="space-y-3 rounded-md border p-3">{current ? <><h4 className="text-sm font-medium">{current.kind_label} · {current.label}</h4>{href(current, projectId) && <a className="text-primary underline" href={href(current, projectId)!}>打开原业务记录</a>}<dl className="grid grid-cols-2 gap-2">{Object.entries(current.facts).filter(([, value]) => value != null).map(([key, value]) => <div key={key}><dt className="text-muted-foreground">{factLabels[key] ?? key}</dt><dd>{statuses[String(value)] ?? String(value)}</dd></div>)}</dl>
          <div><h5 className="font-medium">从本变更到当前对象的引用路径</h5>{path.length ? <ol className="mt-2 space-y-2">{path.map((step, i) => <li key={step.node.key}>{i > 0 && <span className="mr-1 text-muted-foreground">↓ {step.via}：</span>}<button type="button" className="text-primary underline" onClick={() => setSelected(step.node.key)}>{step.node.kind_label} · {step.node.label}</button></li>)}</ol> : <p>当前范围内尚无完整路径。</p>}</div>
          <div><h5 className="font-medium">直接关联及依据</h5>{links.length ? links.map((edge, i) => { const other = nodeMap.get(edge.source === selected ? edge.target : edge.source); return <details className="mt-2" key={`${edge.source}:${edge.target}:${i}`}><summary className="cursor-pointer">{edge.label} · {other?.label ?? "原对象不可读"}</summary>{other && <button className="mt-1 text-primary underline" type="button" onClick={() => setSelected(other.key)}>查看关联对象</button>}<p className="mt-1 text-muted-foreground">依据取自实际对象引用，当前资料摘要已随本次读取固定。</p><p className="mt-1">关系依据：{edge.label}{typeof edge.evidence.source_revision === "number" && ` · 转入资料 v${edge.evidence.source_revision}`}</p>{typeof edge.evidence.basis === "string"&&<p className="mt-1 whitespace-pre-wrap">{edge.evidence.basis}</p>}{typeof edge.evidence.evidence_document_id === "string"&&<a className="mt-1 block text-primary underline" href={`/projects?project=${projectId}&tab=documents&entity_id=${edge.evidence.evidence_document_id}`}>打开关系依据原文件 · {String(edge.evidence.evidence_locator??"")}</a>}</details>; }) : <p className="mt-1">当前范围内未找到直接关系。</p>}</div>
          {data.gaps.filter(g => g.node === selected).map(g => <p className="text-primary" key={g.message}>{g.message}</p>)}
        </> : <p>请选择对象查看路径与原始依据。</p>}</div></div>
      <details><summary className="cursor-pointer font-medium">与已提交影响分析的来源版本比较</summary><p className="mt-2">原ECR状态：{statuses[data.analysis_state] ?? data.analysis_state}{data.approved_at && ` · 批准时间：${new Date(data.approved_at).toLocaleString()}`}</p>{data.professional_comparisons.length ? data.professional_comparisons.map(s => <div className="mt-2" key={s.route_id}>{s.kind==="cost_alternative"?<CostAlternativeEcrSource projectId={projectId} sourceId={s.source_id}/>:<a className="text-primary underline" href={s.kind === "engineering_review" ? `/projects?project=${projectId}&tab=engineering&engineering_review_id=${s.source_id}` : `/projects?project=${projectId}&tab=quality&firmware_package_id=${s.source_id}`}>{s.kind === "engineering_review" ? "专业评审" : "固件工作包"} · 资料 v{s.revision}</a>}<p>{{ not_analyzed: "尚未纳入已提交分析", unchanged: "与已提交分析一致", changed: "与已提交分析相比已有变化" }[s.comparison] ?? s.comparison} · {s.ready ? "原出处与版本仍有效" : "原出处或工作包版本已变化"}</p></div>) : <p className="mt-2">本变更尚无专业工作包来源；不能据此推断其他对象版本未变化。</p>}</details>
      {!!data.scope_revision&&<details><summary className="cursor-pointer font-medium">人工核对范围及对象版本比较</summary><p className="mt-2">当前范围 v{data.scope_revision} · {data.analyzed_scope_revision?`已提交分析绑定 v${data.analyzed_scope_revision}`:"尚未提交范围分析"}</p>{data.scope_comparisons?.map(ref=><p className="mt-2" key={`${ref.kind}:${ref.id}`}>{nodeMap.get(`${ref.kind}:${ref.id}`)?.label??"关系证据文件"}：{{not_analyzed:"尚未纳入已提交分析",unchanged:"与已提交分析读取版本一致",changed:"较已提交分析读取版本变化"}[ref.analysis_comparison]??ref.analysis_comparison} · {ref.changed?"与当前范围保存版本有差异":"与当前范围保存版本一致"}</p>)}</details>}
      <details><summary className="cursor-pointer font-medium">缺失关系与待核对项</summary>{data.unresolved.map(item => <p className="mt-2" key={item.kind}>{item.message}{item.count !== null && `（项目内 ${item.count} 条记录）`}</p>)}{data.gaps.map((gap, index) => <p className="mt-2 text-primary" key={`${gap.node}:${index}`}>{nodeMap.get(gap.node)?.label ?? "未读取的引用对象"}：{gap.message}</p>)}</details>
    </>}
  </div></details>;
}
