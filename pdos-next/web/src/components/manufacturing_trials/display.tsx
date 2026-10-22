import type { ReactNode } from "react";
import { WarningCircle } from "@phosphor-icons/react";
import { refText, sourceText, type FixedRef, type MissingItem, type Parameter, type ResourceUse, type ServerContext, type SharedAction } from "./contracts";

export const controlClass = "mt-1 w-full min-w-0 rounded-lg border border-input bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/50 disabled:opacity-50";
export function FixedReading({ label, reference }: { label: string; reference: FixedRef | null }) {
  return <div className="min-w-0"><dt className="text-sm opacity-70">{label}</dt><dd className="mt-1 break-words text-sm">{refText(reference)}</dd><dd className="mt-1 break-words text-xs opacity-70">{sourceText(reference?.source ?? null)}</dd></div>;
}
export function FixedList({ label, references }: { label: string; references: FixedRef[] }) {
  return <section className="min-w-0"><h3 className="text-sm font-medium">{label}</h3>{references.length ? <dl className="mt-2 grid min-w-0 gap-3 sm:grid-cols-2">{references.map(ref => <FixedReading key={`${ref.kind}:${ref.id}:${ref.revision}`} label="固定版本" reference={ref} />)}</dl> : <p className="mt-1 text-sm opacity-70">尚未记录固定引用</p>}</section>;
}
export function ParameterReading({ parameters }: { parameters: Parameter[] }) {
  return <section className="min-w-0"><h3 className="text-sm font-medium">固定工艺参数</h3>{parameters.length ? <div className="mt-2 space-y-2">{parameters.map(parameter => <p key={parameter.key} className="break-words text-sm">{parameter.key}：<span className="font-mono">{parameter.value ?? "未知"} {parameter.unit ?? "单位未知"}</span><span className="mt-1 block text-xs opacity-70">{sourceText(parameter.source)}</span></p>)}</div> : <p className="mt-1 text-sm opacity-70">参数未知，未补造实际值。</p>}</section>;
}
export function ResourceReading({ resources }: { resources: ResourceUse[] }) {
  const names = { ready: "当前适用", unknown: "资格 / 时段未知", blocked: "阻塞", withdrawn: "资格已撤回" };
  return <section className="min-w-0"><h3 className="text-sm font-medium">资源准备固定引用</h3>{resources.length ? <ul className="mt-2 space-y-2">{resources.map(resource => <li key={`${resource.resource.kind}:${resource.resource.id}`} className="break-words text-sm">{refText(resource.resource)} · {names[resource.state]}<span className="mt-1 block text-xs opacity-70">准备度依据：{resource.readinessRef ? `${resource.readinessRef.id} · v${resource.readinessRef.revision}` : "待资源准备模块接入"}。预约与资格由资源模块核对。</span></li>)}</ul> : <p className="mt-1 text-sm opacity-70">设备、治具及人员条件未知。</p>}</section>;
}
export function MissingReading({ items }: { items: MissingItem[] }) {
  return items.length ? <section className="min-w-0 rounded-lg border border-border p-3" aria-label="准备缺项"><h3 className="flex items-center gap-2 text-sm font-medium"><WarningCircle aria-hidden />准备缺项</h3><ul className="mt-2 space-y-2">{items.map((item, index) => <li key={`${item.kind}:${index}`} className="break-words text-sm">{item.label} · {item.blocking ? "阻断相关正式活动" : "可并行补充"}<span className="mt-1 block text-xs opacity-70">下一步：{item.recovery}</span></li>)}</ul></section> : <p className="text-sm opacity-70">此候选未列出缺项；是否允许执行仍须服务器和具名所有者核对。</p>;
}
export function SharedSlots({ action }: { action: SharedAction }) {
  return <div className="min-w-0 space-y-3">{action.unresolved && <p role="status" className="rounded-lg border border-border p-3 text-sm">本次预览、确认或回执尚待共同办理流程处理。结果未知时先查询同一回执，不重复提交。</p>}{action.previewSlot}{action.receiptSlot}</div>;
}
export function PreparationFrame({ title, context, children }: { title: string; context: ServerContext; children: ReactNode }) {
  return <section className="min-w-0 space-y-4 rounded-lg border border-border bg-[var(--surface)] p-4"><header><h2 className="text-lg font-semibold">{title}</h2><p className="mt-1 text-sm opacity-70">写入方式：一次确认。输入进入共同实质预览，服务器复核当前事实、权限与固定版本。</p></header>{!context.portReady && <p role="status" className="rounded-lg border border-border p-3 text-sm">待接入：{context.unavailableReason || "服务器事实与共同办理端口尚未齐备。"}</p>}{children}<div className="space-y-1 border-t border-border pt-3 text-sm opacity-70"><p>工装验收：{context.namedOwners.toolingAcceptance || "具名所有者待接入"}。</p><p>正式制造放行：{context.namedOwners.manufacturingRelease || "具名所有者待接入"}。具名决定由对应所有者办理，AI 不代签。</p></div></section>;
}
