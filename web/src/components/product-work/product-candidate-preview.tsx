"use client";

import { useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { SourceCitations } from "./source-citations";
import type { Evidence, SourceRef } from "./product-work-api";

const labels: Record<string, string> = {
  title: "名称", hypothesis: "待验证假设", brand: "品牌", model: "型号", variant: "版本 / 配置",
  region: "地域", channel: "渠道", configuration: "配置", notes: "观察说明", observed_on: "观察日期",
  metrics: "指标", label: "指标名称", number: "数值", text: "描述 / 依据", unit: "单位", nature: "数据性质",
  conditions: "适用条件", method: "方法", missing_reason: "未知原因", price_quote: "价格记录", amount: "金额",
  currency: "币种", as_of: "记录时间", quantity: "数量口径", basis: "口径", tax_included: "含税",
  shipping_included: "含运费", certifications: "认证", name: "名称", status: "状态", scope: "覆盖范围",
  valid_until: "有效期", document_number: "证书编号", revision_reason: "决定与原因",
  job_to_be_done: "用户任务", target_users: "目标用户", customer_problems: "用户问题", use_environments: "使用环境",
  buying_criteria: "购买判据", unmet_needs: "未满足需求", outcome: "目标结果", statement: "目标描述",
  baseline_value: "当前值", target_value: "目标值", measurement_method: "测量方法", window: "时间范围",
  importance: "重要度（百分制）", satisfaction: "满意度（百分制）", importance_basis: "重要度依据",
  satisfaction_basis: "满意度依据", solutions: "候选方案", approach: "方案路径", rationale: "依据与取舍",
  constraints: "约束", unknowns: "未解决问题", dimension: "验证维度", success_criterion: "成功判据",
  failure_criterion: "证伪判据", falsification_criterion: "证伪判据", sample: "样本建议", sample_plan: "样本计划",
  sample_method: "样本方法", success_threshold: "成功阈值", falsification_threshold: "证伪阈值",
  content: "草案正文", scenarios: "使用场景", included_features: "包含功能", excluded_features: "排除功能",
  target_cost: "目标成本", price_position: "价格定位", launch_window: "上市窗口", items: "规格条目",
  region_constraints: "地区与合规约束", service_requirements: "服务要求", success_criteria: "成功指标",
  target_text: "目标描述", tolerance: "容差", priority: "优先级", required_for_release: "发布前必须确认",
  verification_method: "验证方法", acceptance_criterion: "通过判据", verification_stage: "验证阶段",
  state: "确认状态", disposition_reason: "处置原因", change_reason: "变更原因",
  market_boundary: "市场边界", problem: "问题", value_proposition: "价值主张", positioning: "产品定位",
  differentiators: "差异化", channels: "渠道", risks: "风险", assumptions: "假设", non_goals: "排除范围",
  vision: "愿景", segment_jtbd: "细分与用户任务", relative_cost: "相对成本", trade_offs: "取舍", success_metrics: "成功指标", growth_path: "增长路径", capabilities_partners: "能力与伙伴", defensibility: "可持续优势", competitor_kind: "竞品类型", lifecycle: "生命周期",
  canvas: "策略 Canvas", route_comparisons: "方案对照", professional_constraints: "专业约束", discipline: "专业", decision_reason: "取舍原因", price_target: "价格目标", nre_budget: "开发投入", id_cycle_days: "设计周期（天）", modules: "成本模块", target: "目标", quality: "质量", supply: "供应", manufacturing: "制造", resources: "资源", trade_off: "取舍", fact_kind: "证据性质", sample_basis: "样本依据", due_at: "目标时间",
  sizing_inputs: "市场规模参数", potential_customers: "潜在客户数", annual_units_per_customer: "年均采购量",
  unit_price: "单价", serviceable_share: "可服务份额", obtainable_share: "可获得份额", lower: "下界", upper: "上界",
  horizon_year: "目标年份", population_unit: "客户数量单位", boundary: "边界",
};
const values: Record<string, string> = {
  unknown: "未知", claimed: "来源标称", measured: "实测", inferred: "推断", observed: "来源观察",
  hypothesis: "待验证假设", derived: "有依据的推导", documented: "有证书记录", reported: "来源声明",
  proposed: "拟议", needs_confirmation: "待专业确认", confirmed: "已确认", not_applicable: "不适用",
  new_development: "新开发", platform_reuse: "平台复用", upgrade: "升级", other: "其他",
  value: "价值", usability: "可用性", viability: "商业可持续性", feasibility: "技术可行性",
  must: "必须", should: "应当", could: "可选",
};

function describe(value: unknown, depth = 0): ReactNode {
  if (value === null || value === undefined || value === "") return <span className="text-muted-foreground">待确认</span>;
  if (typeof value === "boolean") return value ? "是" : "否";
  if (typeof value === "string" || typeof value === "number") return values[String(value)] ?? String(value);
  if (depth > 8) return "请在完整核对视图查阅";
  if (Array.isArray(value)) return value.length ? <ul className="space-y-2">{value.map((entry, index) => <li key={index} className={typeof entry === "object" && entry !== null ? "rounded-md border p-3" : ""}>{describe(entry, depth + 1)}</li>)}</ul> : <span className="text-muted-foreground">未列出</span>;
  if (typeof value === "object") {
    const entries = Object.entries(value).filter(([key]) => labels[key]);
    return <dl className="space-y-3">{entries.map(([key, entry]) => <div key={key}><dt className="text-xs text-muted-foreground">{labels[key]}</dt><dd className="mt-1 whitespace-pre-wrap break-words text-sm leading-6">{describe(["importance", "satisfaction"].includes(key) && typeof entry === "number" ? `${Math.round(entry * 10000) / 100} / 100` : entry, depth + 1)}</dd></div>)}</dl>;
  }
  return null;
}
function evidenceRefs(value: unknown, refs = new Map<string, SourceRef>()): SourceRef[] {
  if (Array.isArray(value)) value.forEach(item => evidenceRefs(item, refs));
  else if (value && typeof value === "object") {
    const item = value as Record<string, unknown>;
    if (item.kind === "evidence_snapshot" && typeof item.ref_id === "string" && typeof item.digest === "string") refs.set(JSON.stringify(item), item as SourceRef);
    else Object.values(item).forEach(entry => evidenceRefs(entry, refs));
  }
  return [...refs.values()];
}
export function ProductCandidatePreview({ value, base, evidence, onAccessDenied }: { value: Record<string, unknown>; base: string; evidence: Evidence[]; onAccessDenied?: (message: string) => void }) {
  const [showSources, setShowSources] = useState(false);
  const refs = evidenceRefs(value);
  return <div className="space-y-4 rounded-md bg-muted/30 p-4">{describe(value)}{refs.length > 0 && <section className="space-y-2 border-t pt-3"><h5 className="text-xs font-medium">来源依据</h5>{showSources ? <SourceCitations base={base} references={refs} evidence={evidence} onAuthorityLost={onAccessDenied}/> : <ul className="space-y-1 text-xs text-muted-foreground">{refs.map(ref => <li key={ref.ref_id + ref.digest}>{evidence.find(item => item.id === ref.ref_id && item.reference.digest === ref.digest)?.name ?? "原来源快照"} · {new Date(ref.as_of).toLocaleDateString()}</li>)}</ul>}<Button variant="ghost" size="sm" onClick={() => setShowSources(!showSources)}>{showSources ? "收起来源核对" : "核对来源与原文"}</Button></section>}</div>;
}
