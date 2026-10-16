"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { g0ProjectHref, isG0Handoff, type G0Decision, type G0Handoff } from "@/lib/proposal-handoff";

const variantNames: Record<string, string> = { customer: "客户变体", region: "地区变体", configuration: "配置变体" };
const itemStatuses: Record<string, string> = { open: "待办理", assigned: "已分派", done: "已完成", closed: "已关闭", cancelled: "已取消" };

export function ProposalHandoff(props: { categoryId: string; proposalId: string; decision: G0Decision }) {
  return <Handoff key={`${props.categoryId}:${props.proposalId}:${props.decision.id}`} {...props} />;
}
function Handoff({ categoryId, proposalId, decision }: { categoryId: string; proposalId: string; decision: G0Decision }) {
  const [data, setData] = useState<G0Handoff | null>(null), [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    void fetch(`/api/v1/categories/${categoryId}/proposals/${proposalId}/handoff`, { cache: "no-store", signal: controller.signal })
      .then(async response => { const value = await response.json(); if (!response.ok) throw new Error(value.message ?? "立项结果暂不可读。"); return value; })
      .then(value => {
        if (controller.signal.aborted) return;
        if (!isG0Handoff(value, categoryId, proposalId, decision)) throw new Error("立项结果与当前决定不一致，请刷新后核对。");
        setData(value); setError("");
      }).catch(failure => {
        if (!controller.signal.aborted) { setData(null); setError(/^(Failed to fetch|Load failed)$/.test(failure.message) ? "连接中断，请重新读取立项结果。" : failure.message); }
      });
    return () => controller.abort();
  }, [categoryId, proposalId, decision, attempt]);
  return <section className="panel space-y-3" aria-label="G0立项结果">
    <h2 className="font-semibold">立项结果与项目承接</h2>
    {error ? <><p role="alert" className="break-words text-sm">{error}</p><Button variant="outline" onClick={() => { setError(""); setData(null); setAttempt(value => value + 1); }}>重新读取立项结果</Button></>
      : !data ? <p className="subtle" role="status">正在核对实际项目、立项定义和带入事项…</p> : <>
        <p className="text-sm">{data.identity.variant ? `${variantNames[data.identity.variant.kind]}：${data.identity.variant.name}` : `新型号：${data.identity.product.name}`}</p>
        {data.identity.variant && <p className="subtle">所属型号：{data.identity.product.name}</p>}
        <p className="text-sm">立项定义 v{data.definition.revision} · 已封存立项副本</p>
        <p className="subtle">立项保留未知与草稿状态，后续规格冻结在项目内办理。</p>
        <div className="space-y-1 text-sm"><p>项目：{data.project.name}</p><p>负责人：{data.project.owner.name ?? "具名负责人"}</p></div>
        <Link className="inline-block text-sm font-medium underline" href={g0ProjectHref(categoryId, data.project.id)}>进入项目驾驶舱</Link>
        <div className="space-y-2 border-t pt-3"><h3 className="text-sm font-medium">带入项目的任务与风险 · {data.open_items.length} 项</h3>
          {data.open_items.length === 0 && <p className="subtle">本次没有需要带入的待决事项。</p>}
          {data.open_items.map(item => <div key={item.id} className="space-y-1 text-sm"><p className="break-words">{item.kind === "risk" ? "风险" : "任务"} · {item.title}</p><p className="subtle">{item.owner.name ?? "具名负责人"} · {item.due_date} · {itemStatuses[item.status] ?? item.status}</p></div>)}
        </div>
        <details className="text-sm"><summary className="cursor-pointer">具名决定与回执</summary><p className="mt-2">{data.decision.signer.name ?? "具名评审人"} · <time dateTime={data.decision.decided_at}>{new Date(data.decision.decided_at).toLocaleString()}</time></p><p className="mt-2 break-all text-xs text-muted-foreground">{data.decision.receipt_id}</p></details>
      </>}
  </section>;
}
