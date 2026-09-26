"use client";

import { useState } from "react";
import { ChangeDiscussionRuns } from "./change-discussion-runs";
import { ChangeAnalysisRuns } from "./change-analysis-runs";
import { Button } from "@/components/ui/button";
import { obj, rows, text, type Row } from "@/components/quality/fmea-sources";
import { noticeCall } from "./supplier-notice-applications";
import { ProfessionalProjection } from "./change-professional-projection";

const labels: Record<string, string> = { manufacturer: "厂商", manufacturer_part_number: "完整厂商料号", notice_type: "通告类型", notice_identifier: "通告标识", review_version: "人审版本", identity_basis: "厂商真实性依据", applicable_scope: "适用范围", impact: "具名人审影响判断", follow_up: "后续要求", human_review_reason: "人审依据", application_reason: "关联本变更的依据", latest_snapshot_basis: "新旧原文核对", url: "原采集网址", matched_part: "原文命中的料号", matched_marker: "邻近通告词", coverage: "覆盖限制", code: "编号", name: "名称", title: "标题", version: "版本", part_number: "BOM内部料号", description: "原说明", quantity: "数量", unit: "单位", bom_type: "BOM类型", material: "物料", specification: "规格", manufacturer_part_key: "厂商料号映射" };
const dates: Record<string, string> = { announced: "发布", effective: "生效", last_order: "最后下单", last_delivery: "最后交付" };
export function SupplierNoticeAnalysis({ projectId, ecrId, depth }: { projectId: string; ecrId: string; depth: number }) {
  const [data, setData] = useState<Row | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState(""), [seat, setSeat] = useState("all"), [visible, setVisible] = useState(20);
  async function read() { setBusy(true); setError(""); try { setData(await noticeCall(`/api/projects/${projectId}/npi/supplier-notices/ecrs/${ecrId}/analysis-context?depth=${depth}`)); setVisible(20); } catch (e) { setData(null); setError(e instanceof Error ? e.message : "通告分析资料暂不可读"); } finally { setBusy(false); } }
  const context = obj(data?.model_context), coverage = obj(context.coverage), projection = rows(context.professional_projections).find(s => s.key===seat), refs = rows(context.references);
  const selected = new Set([...(Array.isArray(projection?.reference_ids) ? projection.reference_ids : []), ...(Array.isArray(projection?.shared_reference_ids) ? projection.shared_reference_ids : [])]);
  const candidates = refs.filter(ref => text(ref.reference_id).startsWith("supplier-notice") || text(ref.label).startsWith("通告显式关联"));
  const shown = candidates.filter(ref => seat==="all" || selected.has(ref.reference_id));
  return <details className="space-y-3 rounded-md border p-3" onToggle={e => { if (e.currentTarget.open && !data && !busy) void read(); }}><summary className="cursor-pointer font-medium">含厂商通告的新版分析资料准备</summary>
    <p className="text-xs text-muted-foreground">合并已关联通告原文、人审、实际BOM及原工程资料。新版运行保持阶段评测状态；原运行继续使用各自固定的资料合同。</p><Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void read()}>{busy ? "正在读取…" : "读取当前通告及工程资料"}</Button>{error && <p role="alert" className="text-destructive">{error}</p>}
    {data && <><ChangeDiscussionRuns projectId={projectId} ecrId={ecrId} source={data}/><ChangeAnalysisRuns projectId={projectId} ecrId={ecrId} sourceDigest={text(data.digest)} depth={depth} includeSupplierNotices/><p>已关联 {text(coverage.supplier_notice_count)} 条通告，{text(coverage.supplier_notice_ready_count)} 条来源及人审就绪；合并工程引用 {refs.length} 份。</p><p className="text-xs">原文命中、人审判断和实际可变更对象分别保留。通告不能替代正式影响判断、验证或批准。</p>
      {Number(coverage.omitted_reference_count)>0 && <p>本次容量省略 {text(coverage.omitted_reference_count)} 份引用；{text(coverage.partial_reference_count)} 份引用有字段省略，不能据此认定全量覆盖。</p>}
      {rows(coverage.gaps).filter(g => g.kind==="supplier_notice").map((g,i) => <p key={i}>{text(g.message)}</p>)}
      <ProfessionalProjection values={context.professional_projections} selected={seat} choose={s => { setSeat(s); setVisible(20); }}/>
      <p className="text-xs text-muted-foreground">以下列出通告新增资料；其余工程依据仍在上方原资料清单中核对，合并后的省略以本次提示为准。</p>
      {shown.slice(0,visible).map(ref => { const fields = obj(ref.fields); return <details className="space-y-2 rounded-md border p-2" key={text(ref.reference_id)}><summary className="cursor-pointer">{text(ref.label)} · {ref.category==="supplier_notice_text" ? "原文片段" : ref.category==="supplier_notice" ? "具名人审" : ref.category==="object" ? "实际业务对象" : "显式对应关系"}</summary>{Object.entries(fields).filter(([key]) => labels[key]).map(([key,value]) => <p className="whitespace-pre-wrap break-words text-xs" key={key}>{labels[key]}：{typeof value==="object" ? JSON.stringify(value) : text(value)}</p>)}{rows(fields.dates).map(d => <p key={text(d.kind)}>{dates[text(d.kind)]}：{text(d.value) || "未知／不适用"}；{text(d.basis)}</p>)}{rows(fields.quotes).map((q,i) => <blockquote className="rounded-md bg-muted/40 p-2 text-xs" key={i}><p>原文字符 {Number(q.start)+1}—{text(q.end)}</p><p className="whitespace-pre-wrap break-words">{text(q.text)}</p></blockquote>)}{ref.category==="relationship" && <p>{text(fields.label)}；{text(fields.evidence)}</p>}{fields.revised_since_application===true && <p>本次已使用原应用之后的新接受人审版本。</p>}{Array.isArray(ref.omitted_fields) && ref.omitted_fields.length>0 && <p>字段省略：{ref.omitted_fields.map(k => labels[String(k)] || String(k)).join("、")}</p>}</details>; })}
      {shown.length>visible && <Button type="button" size="sm" variant="outline" onClick={() => setVisible(v => v+20)}>再显示20份通告引用</Button>}
      <details><summary className="cursor-pointer">合并资料的省略记录</summary>{rows(data.omissions).map((o,i) => <p key={i}>{text(o.label)}：{text(o.reason)}</p>)}</details>
    </>}
  </details>;
}
