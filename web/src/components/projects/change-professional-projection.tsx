"use client";

import { Button } from "@/components/ui/button";
import { obj, rows, text, type Row } from "@/components/quality/fmea-sources";

const strings = (v: unknown): string[] => Array.isArray(v) ? v.map(String) : [];
const labels: Record<string, string> = {
  title: "标题", name: "名称", code: "编号", version: "版本", revision_number: "资料版本", status: "实际状态",
  source_kind: "来源类别", freeze_is_current: "原冻结当前仍启用", routing_reason: "转入变更的理由", created_at: "记录时间", published_at: "发布时间", updated_at: "原更新时间",
  content: "原始内容", description: "说明", reason: "依据", assumptions: "假设", constraints: "约束", risks: "风险", tradeoffs: "取舍", alternatives: "备选", interfaces: "接口", materials: "材料", dimensions: "尺寸", surface_finish: "表面处理", color: "颜色", source_reference: "原出处",
  failure_mode: "失效模式", effect: "失效后果", possible_cause: "可能原因", cause_status: "原因证据状态", controls: "预防与检出措施", control_gaps: "控制缺口",
  severity: "严重度", occurrence: "发生度", detection: "检出度", scoring_method: "评分方法", scoring_basis: "评分依据", unknown_reason: "未知原因", next_action: "后续行动",
  sources_current: "发布版来源当前仍一致", source_gaps: "已变化的原引用", current: "当前仍一致", current_value: "当前来源原值", relationship: "关联说明", locator: "原文定位",
  brief: "设计简述", envelope: "外形与尺寸包络", cmf: "色彩 / 材料 / 表面工艺", layout: "布局", artifact_snapshot: "设计资料原快照", topic: "反馈主题", reported_at: "反馈时间",
  containment_action: "实际遏制措施", containment_completed_at: "遏制完成时间", preventive_not_applicable_reason: "预防措施不适用理由", preventive_disposition_approved_at: "不适用处置批准时间", effectiveness_criteria: "有效性判据", observation_due_at: "观察截止", superseded_at: "被替代时间", completion_summary: "措施完成说明", started_at: "实际开始", criteria: "核验判据", actual_result: "实际核验结果",
  nonconformity: "不符合事实", requirement_reference: "原要求出处", containment: "遏制措施", containment_actions: "遏制措施", affected_scope: "受影响范围", affected_quantity: "受影响数量", target_date: "目标日期", closed_at: "实际关闭时间",
  analysis: "分析记录", root_cause: "根因意见", method: "使用方法", evidence: "实际证据", evidence_refs: "原证据引用", evidence_reference: "原证据出处", approved_at: "实际批准时间", rejection_reason: "退回理由",
  action_type: "措施类别", action: "措施", action_description: "措施说明", completed_at: "实际完成时间", completion_evidence: "完成证据", due_date: "截止日期", verification_criteria: "验证判据", verification_method: "验证方法", outcome: "实际结论", review_number: "有效性轮次", reviewed_at: "实际复核时间", observation_start: "观察开始", observation_end: "观察结束", result: "结果", rationale: "结论依据", notes: "备注",
  approved_root_cause: "关联 NCR 最近获批根因", latest_effectiveness_review: "关联 NCR 最近独立有效性记录", kind: "类别", verification: "验证要求", baseline_value: "原值", proposed_value: "拟议值", unit: "单位", basis: "判断依据", verdict: "专业判断", body: "原内容",
};
const terms: Record<string, string> = { frozen_revision: "原冻结方案", feedback_revision: "反馈对应方案", feedback: "原反馈", hypothesis: "假设", evidence_supported: "有证据支持", unknown: "未知", draft: "草稿", approved: "已批准", rejected: "已退回", submitted: "已提交", planned: "计划中", in_progress: "执行中", completed: "已完成", open: "未关闭", containment: "遏制中", root_cause: "根因调查中", action: "措施执行中", verification: "有效性验证中", closed: "已关闭", corrective: "纠正", preventive: "预防", prevention: "预防", detection: "检出", effective: "有效", ineffective: "无效", inconclusive: "尚无结论" };
function valueText(value: unknown, depth = 0): string {
  if (value == null) return "未记录";
  if (typeof value === "boolean") return value ? "是" : "否";
  if (typeof value !== "object") return terms[String(value)] ?? String(value);
  if (depth >= 5) return "嵌套资料请查看原业务记录";
  if (Array.isArray(value)) return value.length ? value.map(v => valueText(v, depth + 1)).join("；\n") : "无记录";
  const entries = Object.entries(obj(value)).filter(([key]) => labels[key]);
  return entries.length ? entries.map(([key, v]) => `${labels[key]}：${valueText(v, depth + 1)}`).join("\n") : "原引用已保存；本处未展开其余字段";
}

export function ProfessionalEvidence({ fields }: { fields: Row }) {
  return <dl className="mt-2 space-y-2">{Object.entries(fields).filter(([key]) => labels[key]).map(([key, value]) => <div key={key}><dt className="text-muted-foreground">{labels[key]}</dt><dd className="max-h-80 overflow-auto whitespace-pre-wrap break-words">{valueText(value)}</dd></div>)}</dl>;
}

export function ProfessionalProjection({ values, selected, choose }: { values: unknown; selected: string; choose: (key: string) => void }) {
  const seats = rows(values);
  if (!seats.length) return <p className="text-muted-foreground">本版历史输入尚未记录专业资料归属。</p>;
  return <section className="space-y-2"><p className="font-medium">按专业核对实际资料</p><p className="text-muted-foreground">展示本次工程分析已纳入的来源及缺项。资料归属不表示该专业已经发言、评审或批准。</p>
    <Button type="button" size="sm" variant={selected === "all" ? "default" : "outline"} onClick={() => choose("all")}>查看全部资料</Button>
    <div className="grid gap-2 md:grid-cols-2">{seats.map(s => <div className="space-y-1 rounded-md border p-2" key={text(s.key)}><div className="flex items-center justify-between gap-2"><p className="font-medium">{text(s.label)}</p><Button type="button" size="sm" variant={selected === s.key ? "default" : "outline"} onClick={() => choose(text(s.key))}>查看来源</Button></div><p>{strings(s.reference_ids).length} 份专业资料 · {s.status === "missing_sources" ? "未纳入专业资料" : s.status === "partial" ? "有待补或省略项" : "已纳入关联资料"}</p>{strings(s.missing).map((m, i) => <p className="text-muted-foreground" key={i}>{m}</p>)}</div>)}</div>
  </section>;
}
