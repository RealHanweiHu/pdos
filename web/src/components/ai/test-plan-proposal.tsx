"use client";

import { TestExecutionProposal, validExecutionProposal, executionProposalReady, type ExecutionProposal } from "./test-execution-proposal";
import { sourceDescription, type TestPlanSource } from "@/components/projects/project-test-sources";

type Item = {
  title: string; category: string; method: string; acceptance_criteria: string;
  applicability: string; evidence_requirements: string; required: boolean; execution_preparation?: ExecutionProposal | null;
};
type Change = {
  operation: "add" | "modify" | "exclude"; target_key: string | null; reason: string;
  after: Item | null; references: { reference_id: string; quote: string }[]; unresolved: string[];
};
export type TestPlanProposal = {
  summary: string; base_plan_id: string; base_digest: string; messages: string[];
  base_items: (Partial<Item> & { key: string; applicable: boolean; exclusion_reason: string | null })[];
  changes: Change[]; questions: string[];
  source_snapshots?: TestPlanSource[];
};

const fields = { title: "测试项", category: "类别", method: "测试方法", acceptance_criteria: "判定依据", applicability: "适用条件", evidence_requirements: "证据要求" } as const;
const operations = { add: "新增", modify: "修改", exclude: "不适用" } as const;
const categoryLabels: Record<string, string> = { whole_unit: "整机", reliability: "可靠性" };
function displayField(key: string, value: unknown, fallback: string) {
  if (!value) return fallback;
  return key === "category" ? categoryLabels[String(value)] ?? String(value) : String(value);
}
const inputClass = "min-h-20 w-full rounded-lg border bg-background p-2 text-sm";

export function parseTestPlanProposal(raw: Record<string, unknown>): TestPlanProposal | null {
  if (typeof raw.base_plan_id !== "string" || typeof raw.base_digest !== "string" || typeof raw.summary !== "string") return null;
  if (!Array.isArray(raw.messages) || !raw.messages.every((m) => typeof m === "string")) return null;
  if (!Array.isArray(raw.questions) || !raw.questions.every((q) => typeof q === "string")) return null;
  if (!Array.isArray(raw.base_items) || !raw.base_items.every((i) => i && typeof i.key === "string" && typeof i.title === "string")) return null;
  if (!Array.isArray(raw.changes) || !raw.changes.every((c) => c && Object.hasOwn(operations, c.operation) &&
    typeof c.reason === "string" && (c.target_key === null || typeof c.target_key === "string") &&
    (c.after === null || (c.after && Object.keys(fields).every((key) => typeof c.after[key] === "string") && typeof c.after.required === "boolean" && (c.after.execution_preparation == null || validExecutionProposal(c.after.execution_preparation)))) &&
    Array.isArray(c.unresolved) && c.unresolved.every((v: unknown) => typeof v === "string") &&
    Array.isArray(c.references) && c.references.every((r: { reference_id?: unknown; quote?: unknown }) => r && typeof r.reference_id === "string" && typeof r.quote === "string"))) return null;
  return raw as TestPlanProposal;
}

export function testPlanProposalReady(raw: Record<string, unknown>): boolean {
  const p = parseTestPlanProposal(raw);
  return !!p && p.changes.every(c => !c.after?.execution_preparation || executionProposalReady(c.after.execution_preparation)) && p.questions.length === 0 && p.changes.length > 0 && p.changes.every((c) => c.unresolved.length === 0 &&
    (c.operation === "exclude" || (c.after && Object.keys(fields).every((key) => String(c.after?.[key as keyof Item] ?? "").trim()))));
}

export function TestPlanProposalView({ payload, onChange }: {
  payload: Record<string, unknown>; onChange?: (payload: Record<string, unknown>) => void;
}) {
  const proposal = parseTestPlanProposal(payload);
  if (!proposal) return <p role="alert">测试计划建议内容不完整，请重新生成。</p>;
  function edit(index: number, value: Partial<Change>) {
    onChange?.({ ...payload, changes: proposal!.changes.map((c, i) => i === index ? { ...c, ...value } : c) });
  }
  return <div className="space-y-4 p-4 text-sm">
    <p className="whitespace-pre-wrap">{proposal.summary}</p>
    <p className="text-muted-foreground">应用后生成计划新修订，原报告与结果保留。建议文本不计入测试完成证据。</p>
    <details><summary className="cursor-pointer py-2 font-medium">查看需求对话（{proposal.messages.length} 条）</summary>
      <ol className="list-decimal space-y-2 pl-5">{proposal.messages.map((m, i) => <li className="whitespace-pre-wrap" key={i}>{m}</li>)}</ol>
    </details>
    {onChange ? <label className="grid gap-1">尚待确认的问题（解决后移除，每行一条）<textarea className={inputClass} value={proposal.questions.join("\n")} onChange={(e) => onChange({ ...payload, questions: e.target.value.split("\n").filter((s) => s.trim()) })} /></label> : proposal.questions.length > 0 ? <div className="border-l-2 border-pending pl-3"><p className="font-medium">需要补充</p><ul className="list-disc pl-5">{proposal.questions.map((q, i) => <li key={i}>{q}</li>)}</ul></div> : null}
    <p>拟变更 {proposal.changes.length} 项 · 原计划 {proposal.base_items.length} 项</p>
    {proposal.changes.map((change, index) => {
      const before = proposal.base_items.find((item) => item.key === change.target_key);
      return <section aria-label={`变更 ${index + 1}`} className="space-y-3 border-t pt-3" key={`${change.target_key ?? "new"}:${index}`}>
        <div className="flex items-center justify-between gap-2"><h4 className="font-semibold">{operations[change.operation]} · {change.after?.title ?? before?.title ?? change.target_key}</h4>
          {onChange ? <button className="min-h-11 text-destructive" type="button" onClick={() => onChange({ ...payload, changes: proposal.changes.filter((_, i) => i !== index) })}>取消此项</button> : null}</div>
        {onChange ? <label className="grid gap-1">调整原因<textarea className={inputClass} value={change.reason} onChange={(e) => edit(index, { reason: e.target.value })} /></label> : <p>{change.reason}</p>}
        {change.after ? <dl className="space-y-2">{Object.entries(fields).map(([key, label]) => <div className="grid gap-2 sm:grid-cols-2" key={key}>
          <div><dt className="text-xs text-muted-foreground">{label} · 原值</dt><dd className="whitespace-pre-wrap">{displayField(key, before?.[key as keyof Item], "无")}</dd></div>
          <div>{onChange ? <label className="grid gap-1">{label} · 建议值<textarea className={inputClass} value={String(change.after?.[key as keyof Item] ?? "")} onChange={(e) => edit(index, { after: { ...change.after!, [key]: e.target.value } })} /></label> : <><dt className="text-xs text-muted-foreground">{label} · 建议值</dt><dd className="whitespace-pre-wrap">{displayField(key, change.after?.[key as keyof Item], "待补")}</dd></>}</div>
        </div>)}</dl> : null}
        {before?.execution_preparation && <details><summary className="cursor-pointer text-xs">核对原执行准备</summary><TestExecutionProposal value={before.execution_preparation} />{onChange && change.after && <button type="button" className="min-h-11 text-primary underline" onClick={() => edit(index, { after: { ...change.after!, execution_preparation: before.execution_preparation } })}>本次沿用已核对的原执行准备</button>}{change.after && !change.after.execution_preparation && <p className="text-xs text-pending">本次尚未纳入原执行准备；应用后需在新计划中补齐，请核对这一差异。</p>}</details>}
        {change.after && <TestExecutionProposal value={change.after.execution_preparation} onChange={onChange ? value => edit(index, { after: { ...change.after!, execution_preparation: value } }) : undefined} />}
        {change.after ? <p>测试范围：{change.after.required ? "必测" : "选测"}</p> : <p>原测试记录保留；不适用原因将进入新版本。</p>}
        {onChange ? <label className="grid gap-1">本项待补条件（补齐后移除，每行一条）<textarea className={inputClass} value={change.unresolved.join("\n")} onChange={(e) => edit(index, { unresolved: e.target.value.split("\n").filter((s) => s.trim()) })} /></label> : change.unresolved.length > 0 ? <p className="text-pending">待补：{change.unresolved.join("；")}</p> : null}
        <details><summary className="cursor-pointer py-2">查看依据（{change.references.length}）</summary><ul className="space-y-2">{change.references.map((ref, i) => {
          const source = proposal.source_snapshots?.find((s) => s.reference_id === ref.reference_id);
          return <li key={i}><span className="text-xs text-muted-foreground">{source ? sourceDescription(source) : ref.reference_id.startsWith("message:") ? `用户要求 ${ref.reference_id.slice(8)}` : `原测试项 ${ref.reference_id.slice(5)}`}</span><blockquote className="whitespace-pre-wrap border-l pl-3">{ref.quote}</blockquote></li>;
        })}</ul></details>
      </section>;
    })}
  </div>;
}
