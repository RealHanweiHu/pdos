"use client";

import { useEffect, useRef, useState } from "react";
import { SupplierNoticeAnalysis } from "./supplier-notice-analysis";
import { ProfessionalEvidence, ProfessionalProjection } from "./change-professional-projection";
import { ChangeScheduleSource } from "./change-schedule-source";
import { ChangeDiscussionRuns } from "./change-discussion-runs";
import { ChangeAnalysisRuns } from "./change-analysis-runs";
import { Button } from "@/components/ui/button";
import { isRecord } from "@/components/workspace-api";

type Row = Record<string, unknown>;
const obj = (v: unknown): Row => isRecord(v) ? v : {};
const rows = (v: unknown): Row[] => Array.isArray(v) ? v.filter(isRecord) : [];
const text = (v: unknown) => v == null ? "未记录" : typeof v === "object" ? JSON.stringify(v, null, 2) : String(v);
const categories: Record<string, string> = { supplier_notice: "厂商通告人审核对", supplier_notice_text: "通告原文片段", professional_evidence: "ID与品质实际来源", change: "原工程变更", schedule: "正式排程与资源", professional: "专业资料与逐项评审", comparison: "当前与已分析版本比较", object: "实际业务对象", scope: "人工核对范围", scope_item: "范围条目", execution: "执行结果与缺口", relationship: "实际引用关系" };
const labels: Record<string, string> = {
  manufacturer: "厂商", manufacturer_part_number: "完整厂商料号", notice_type: "通告类型", notice_identifier: "通告标识", review_version: "人审版本", identity_basis: "厂商真实性依据", applicable_scope: "适用范围", impact: "具名人审影响判断", follow_up: "后续要求", human_review_reason: "人审依据", application_reason: "关联本变更的依据", latest_snapshot_basis: "新旧原文核对", dates: "逐项日期及依据", quotes: "原快照精确摘录及字符位置", url: "原采集网址", matched_part: "原文命中的料号", matched_marker: "邻近通告词",

  analysis_state: "原分析状态", scope_revision: "当前范围版本", analyzed_scope_revision: "已分析范围版本", scope_comparisons: "范围来源比较", professional_comparisons: "专业资料比较", routing_reason: "转入依据", scope: "专业范围", parameter: "参数", original_value: "原值", proposed_value: "拟议值", verdict: "专业判断", verification_criteria: "验证要求", change_notes: "变更说明", observations: "观察", hypotheses: "未证实假设", unknowns: "未知项", git_reference: "Git引用",
  code: "编号", title: "标题", name: "名称", description: "说明", reason: "依据", version: "版本", revision: "范围版本", revision_number: "资料版本", status: "状态",
  coverage: "覆盖范围", exclusions: "排除范围", ready: "保存时引用仍一致", source_comparisons: "来源版本比较", basis: "判断依据", next_action: "后续要求", action: "执行类别", conclusion: "影响判断",
  part_number: "料号", material_reference: "物料引用", quantity: "数量", unit: "单位", bom_type: "BOM类型", verification_method: "验证方法", acceptance_criteria: "验收判据", criticality: "关键程度", content: "原规格内容", attributes: "原物料属性",
  serial_number: "样机编号", fw_version: "固件版本", pcb_version: "PCB版本", structure_version: "结构版本", run_number: "测试序次", conditions: "测试条件", metrics: "实测数据", result_notes: "结果说明", executed_at: "实际测试时间",
  execution_time_precision: "实际时间精度", execution_time_source: "时间来源", snapshot: "当次配置", certificate_type: "认证类别", certificate_number: "证书编号", issuing_body: "发证机构", valid_from: "有效期始", valid_until: "有效期至", completed_at: "实际完成时间", evidence_reference: "证据出处", root_cause: "原因分析", resolution: "处理结论", severity: "严重度", currency: "币种", amount: "金额", unit_cost: "单位成本", filename: "文件名", size_bytes: "文件大小", mime_type: "文件类型", approved_at: "批准时间", updated_at: "原记录更新时间",
  required: "要求执行", completion_criteria: "完成判据", result_scope: "实际结果范围", gaps: "当前缺口", follow_up_count: "后续补齐任务数", result_version: "结果版本", confirmation: "原确认回执", task: "原任务计划与办理", label: "关系名称", evidence: "关系依据",
};

export function ChangeAnalysisPreparation({ projectId, ecrId, showRuns = true, includeSupplierNotices = false, onPrepared }: { projectId: string; ecrId: string; showRuns?: boolean; includeSupplierNotices?: boolean; onPrepared?: (value: Row | null) => void }) {
  const [data, setData] = useState<Row | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null);
  const [openDiscussion, setOpenDiscussion] = useState(false);
  const panel = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const open = (event: Event) => {
      if (!(event instanceof CustomEvent) || obj(event.detail).ecrId !== ecrId) return;
      setOpenDiscussion(true);
      if (panel.current) { panel.current.open = true; panel.current.scrollIntoView({ behavior: "smooth", block: "start" }); }
    };
    window.addEventListener("pdos-open-change-discussion", open);
    return () => window.removeEventListener("pdos-open-change-discussion", open);
  }, [ecrId]);
  const [seat, setSeat] = useState("all");
  const [depth, setDepth] = useState(3), [category, setCategory] = useState("all"), [visible, setVisible] = useState(30);
  async function read() {
    setBusy(true); setError(null);
    try {
      const response = await fetch(includeSupplierNotices ? `/api/projects/${projectId}/npi/supplier-notices/ecrs/${ecrId}/analysis-context?depth=${depth}` : `/api/projects/${projectId}/changes/ecrs/${ecrId}/analysis-context?depth=${depth}`, { cache: "no-store" });
      const value: unknown = await response.json();
      if (!response.ok || !isRecord(value) || !isRecord(value.model_context)) throw new Error(isRecord(value) && isRecord(value.detail) && typeof value.detail.message === "string" ? value.detail.message : "分析资料暂不可读，请重试");
      setData(value); onPrepared?.(value); setVisible(30);
    } catch (error) { setData(null); onPrepared?.(null); setError(error instanceof Error ? error.message : "读取失败"); }
    finally { setBusy(false); }
  }
  const context = obj(data?.model_context), coverage = obj(context.coverage);
  const selectedSeat = rows(context.professional_projections).find(s => s.key === seat);
  const selectedIds = new Set([...(Array.isArray(selectedSeat?.reference_ids) ? selectedSeat.reference_ids : []), ...(Array.isArray(selectedSeat?.shared_reference_ids) ? selectedSeat.shared_reference_ids : [])]);
  const references = rows(context.references), filtered = references.filter(r => (category === "all" || r.category === category) && (seat === "all" || selectedIds.has(r.reference_id)));
  const omissions = rows(data?.omissions);
  return <details ref={panel} className="rounded-md border p-3" onToggle={e => { if (e.currentTarget.open && !data && !busy) void read(); }}>
    <summary className="cursor-pointer text-sm font-medium">{includeSupplierNotices ? "含厂商通告的 AI 影响分析资料准备" : "AI 影响分析资料准备"}</summary>
    <div className="mt-3 space-y-3 text-xs">
      <p className="text-muted-foreground">核对实际变更、范围、引用关系、执行缺口及相关正式排程，作为后续分析依据。可查看本次准备资料及分析运行记录。</p>
      <div className="flex flex-wrap items-center gap-3"><label>准备关联层数<select disabled={busy} className="ml-2 rounded-md border bg-background p-2" value={depth} onChange={e => { setDepth(Number(e.target.value)); setData(null); onPrepared?.(null); }}>{[1, 2, 3, 4, 5].map(v => <option key={v} value={v}>{v} 层</option>)}</select></label><Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void read()}>{busy ? "正在读取实际资料…" : "重新读取当前资料"}</Button></div>
      {showRuns && !includeSupplierNotices && <SupplierNoticeAnalysis key={`${ecrId}:${depth}`} projectId={projectId} ecrId={ecrId} depth={depth}/>}
      {error && <p role="alert" className="text-destructive">{error}</p>}
      {data && <>
        {showRuns && <ChangeDiscussionRuns projectId={projectId} ecrId={ecrId} source={data} requestedOpen={openDiscussion}/>}
        {showRuns && <ChangeAnalysisRuns projectId={projectId} ecrId={ecrId} sourceDigest={text(data.digest)} depth={Number(coverage.depth)} includeSupplierNotices={includeSupplierNotices} />}
        {includeSupplierNotices && <p>已关联 {text(coverage.supplier_notice_count)} 条通告，其中 {text(coverage.supplier_notice_ready_count)} 条来源及人审就绪。人审与原文分列，未知日期和覆盖缺项保留；可按本次原文和人审资料发起独立分析或专业讨论。</p>}
        <p>本次读取 {text(coverage.depth)} 层 · {text(data.read_at)} · {references.length} 份可核对资料。</p>
        {(Number(coverage.omitted_reference_count) > 0 || Number(coverage.partial_reference_count) > 0) && <p className="text-primary">本次有 {text(coverage.omitted_reference_count)} 份引用未纳入、{text(coverage.partial_reference_count)} 份资料省略了部分字段；需要缩小范围或补充分析，不能据此判断全量影响。</p>}
        <details><summary className="cursor-pointer font-medium">缺失关系与待补资料</summary><ul className="mt-2 space-y-1">{[...rows(coverage.unresolved), ...rows(coverage.gaps)].map((gap, i) => <li key={i}>{text(gap.message)}</li>)}{Array.isArray(coverage.scope_gaps) && coverage.scope_gaps.map((gap, i) => <li key={`scope-${i}`}>{text(gap)}</li>)}{Array.isArray(coverage.graph_limits) && coverage.graph_limits.map((gap, i) => <li key={`limit-${i}`}>{text(gap)}</li>)}</ul></details>
        <ProfessionalProjection values={context.professional_projections} selected={seat} choose={value => { setSeat(value); setCategory("all"); setVisible(30); }}/>
        <label className="block">资料类别<select className="ml-2 rounded-md border bg-background p-2" value={category} onChange={e => { setCategory(e.target.value); setVisible(30); }}><option value="all">全部资料</option>{Object.entries(categories).map(([key, label]) => <option key={key} value={key}>{label}（{references.filter(r => r.category === key).length}）</option>)}</select></label>
        <div className="space-y-2">{filtered.slice(0, visible).map(ref => <details className="rounded-md border p-2" key={text(ref.reference_id)}><summary className="cursor-pointer">{categories[text(ref.category)]} · {text(ref.label)}</summary>{ref.category === "schedule" ? <ChangeScheduleSource fields={obj(ref.fields)}/> : ref.category === "professional_evidence" ? <ProfessionalEvidence fields={obj(ref.fields)}/> : <dl className="mt-2 space-y-2">{Object.entries(obj(ref.fields)).filter(([key]) => labels[key]).map(([key, value]) => <div key={key}><dt className="text-muted-foreground">{labels[key]}</dt><dd className="max-h-80 overflow-auto whitespace-pre-wrap break-words">{text(value)}</dd></div>)}</dl>}{Array.isArray(ref.omitted_fields) && ref.omitted_fields.length > 0 && <p className="mt-2 text-primary">本次省略：{ref.omitted_fields.map(key => labels[String(key)] ?? "部分原资料").join("、")}</p>}</details>)}</div>
        {visible < filtered.length && <Button type="button" size="sm" variant="outline" onClick={() => setVisible(v => v + 30)}>更多准备资料</Button>}
        {omissions.length > 0 && <details><summary className="cursor-pointer">未纳入本次分析的资料（{omissions.length}）</summary>{omissions.slice(0, 100).map(o => <p className="mt-1" key={text(o.reference_id)}>{text(o.label)} · {text(o.reason)}</p>)}{omissions.length > 100 && <p>其余省略项请缩小关联层数后继续核对。</p>}</details>}
      </>}
    </div>
  </details>;
}
