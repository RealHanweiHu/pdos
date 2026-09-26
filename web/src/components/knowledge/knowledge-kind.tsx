"use client";

export const KNOWLEDGE_KINDS = {
  design_rule: "设计规则",
  failure_case: "失败案例",
  supplier_experience: "供应商经验",
  benchmark: "对标资料",
} as const;
export type KnowledgeKind = keyof typeof KNOWLEDGE_KINDS;
const descriptions: Record<KnowledgeKind, string> = {
  design_rule: "可复用的设计约束或方法，需说明适用边界；不会自动修改项目规格或规则。",
  failure_case: "已经发生的问题、原因和处理经验，需区分观察事实与待验证推测。",
  supplier_experience: "供应商、物料或合作过程中的经验，需说明具体对象与适用范围。",
  benchmark: "用于对照的产品、方案或指标资料，需保留对比口径和来源版本。",
};
export function parseKnowledgeKind(value: unknown): KnowledgeKind | null {
  if (value === undefined || value === null) return null;
  if (typeof value !== "string" || !Object.hasOwn(KNOWLEDGE_KINDS, value)) throw new Error("知识分类不完整，请刷新核对");
  return value as KnowledgeKind;
}
export function knowledgeKindLabel(value: KnowledgeKind | null | undefined): string {
  return value ? KNOWLEDGE_KINDS[value] : "未分类";
}
export function KnowledgeKindSelect({ value, onChange }: { value: KnowledgeKind | null | undefined; onChange: (value: KnowledgeKind | null) => void }) {
  return <label className="block text-xs">知识分类<select className="mt-1 block w-full rounded-md border bg-background p-2 text-sm" value={value ?? ""} onChange={event => onChange(parseKnowledgeKind(event.target.value || null))}>
    <option value="">待分类（可保存草稿）</option>{Object.entries(KNOWLEDGE_KINDS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
  </select><span className="mt-1 block text-muted-foreground">{value ? descriptions[value] : "候选可先保存，审核前须由人员确认分类。"}</span></label>;
}
