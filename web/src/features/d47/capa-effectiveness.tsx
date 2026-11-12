"use client";
// D307 (P96 第 1–4 项, F47): named quality decision on CAPA effectiveness. Effective closes
// the issue; ineffective returns it to actioning for a new round; or extend the observation.
import { useCallback, useEffect, useRef, useState } from "react";
import { ShieldCheck } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { NamedCommandReview } from "@/features/projects/named-command-review";
import { makeCommand } from "@/lib/named-command";
import type { ProjectApi } from "@/lib/project-plan-view";
import { isoFromLocal, outcomeNames, timeText } from "@/lib/d47-records";
import { useNamedAction } from "./use-named-action";

type Waiting = {
  issue_id: string; revision: number; title: string; capa_id: string; observation_until: string; executors: string[];
  reviews: { id: string; revision: number; reviewer_id: string; conclusion: string | null; current: boolean }[];
  observations: { id: string; revision: number; executor_id: string; observed_until: string }[];
};
type Props = { api: ProjectApi; product: { id: string; revision: number }; projectId: string; principalId: string; onSaved?: () => void | Promise<void> };
const conclusionNames: Record<string, string> = { applicable: "适用", not_applicable: "不适用", unknown: "未知" };

export function CapaEffectiveness({ api, product, projectId, principalId, onSaved }: Props) {
  const action = useNamedAction(api);
  const { setError } = action;
  const [items, setItems] = useState<Waiting[] | null>(null), [selected, setSelected] = useState("");
  const [outcome, setOutcome] = useState<"effective" | "ineffective" | "extend_observation">("extend_observation");
  const [until, setUntil] = useState(""), [text, setText] = useState(""), [chosen, setChosen] = useState<string[]>([]);
  const alive = useRef(true);
  const refresh = useCallback(async () => { const value = await api<{ items: Waiting[] }>(`v1/products/${product.id}/projects/${projectId}/capa-effectiveness`); if (alive.current) setItems(value.items); }, [api, product.id, projectId]);
  useEffect(() => { alive.current = true; void Promise.resolve().then(() => alive.current ? refresh() : undefined).catch(failure => setError((failure as Error).message)); return () => { alive.current = false; }; }, [refresh, setError]);
  const issue = items?.find(row => row.issue_id === selected) ?? null;
  const executor = issue ? issue.executors.includes(principalId) : false;
  function decide() {
    void action.start(() => {
      if (!issue) throw new Error("请选择待验证的问题。");
      const evidence = chosen.map(key => { const [kind, id, revision] = key.split(":"); return { kind, id, revision: Number(revision) }; });
      return makeCommand(product, "quality.capa.effectiveness.decide", {
        issue_id: issue.issue_id, expected_issue_revision: issue.revision, outcome, text: text.trim() || outcomeNames[outcome],
        evidence, ...(outcome === "extend_observation" ? { observation_until: isoFromLocal(until) } : {}),
      });
    }, "T2");
  }
  return <section className="panel min-w-0 space-y-3" aria-label="CAPA 有效性决定">
    <h2 className="flex items-center gap-2 font-semibold"><ShieldCheck aria-hidden size={18}/>CAPA 有效性决定</h2>
    <p className="subtle text-sm">品质具名办理；措施实施人不能判定自己措施的有效性。证据用已有的具名复核和观察记录。判有效即关闭问题，判无效回到根因与措施重新办理。</p>
    {action.error && <p role="alert" className="text-sm text-destructive [overflow-wrap:anywhere]">{action.error}</p>}
    {action.notice && <p role="status" className="text-sm">{action.notice}</p>}
    {items === null ? <p className="subtle text-sm">正在读取…</p> : items.length === 0 ? <p className="subtle text-sm">本项目没有待验证有效性的问题。</p> : <>
      <label className="block text-sm">待验证的问题<select value={selected} onChange={e => { setSelected(e.target.value); setChosen([]); }}><option value="">选择问题</option>{items.map(row => <option key={row.issue_id} value={row.issue_id}>{row.title} · v{row.revision} · 观察至 {timeText(row.observation_until)}</option>)}</select></label>
      {issue && <div className="space-y-2 text-sm">
        {executor && <p role="alert" className="text-destructive">你是本 CAPA 的措施实施人，不能判定有效性。</p>}
        <fieldset className="space-y-1"><legend className="font-medium">证据</legend>
          {issue.reviews.map(r => <label key={r.id} className="flex gap-2 text-xs"><input type="checkbox" checked={chosen.includes(`review:${r.id}:${r.revision}`)} onChange={e => setChosen(e.target.checked ? [...chosen, `review:${r.id}:${r.revision}`] : chosen.filter(k => k !== `review:${r.id}:${r.revision}`))}/>具名复核 {r.id.slice(0, 8)} · {conclusionNames[r.conclusion ?? "unknown"] ?? r.conclusion}{r.current ? "" : "（已过期）"}</label>)}
          {issue.observations.map(o => <label key={o.id} className="flex gap-2 text-xs"><input type="checkbox" checked={chosen.includes(`observation:${o.id}:${o.revision}`)} onChange={e => setChosen(e.target.checked ? [...chosen, `observation:${o.id}:${o.revision}`] : chosen.filter(k => k !== `observation:${o.id}:${o.revision}`))}/>观察记录 {o.id.slice(0, 8)} · 至 {timeText(o.observed_until)}</label>)}
          {issue.reviews.length + issue.observations.length === 0 && <p className="subtle text-xs">尚无具名复核或观察记录；只能延长观察。</p>}
        </fieldset>
        <label className="block">结论<select value={outcome} onChange={e => setOutcome(e.target.value as typeof outcome)}>{Object.entries(outcomeNames).map(([value, name]) => <option key={value} value={value}>{name}</option>)}</select></label>
        {outcome === "extend_observation" && <label className="block">新的观察截止<input type="datetime-local" value={until} onChange={e => setUntil(e.target.value)}/></label>}
        <label className="block">结论说明<textarea value={text} maxLength={4000} onChange={e => setText(e.target.value)}/></label>
        {!action.prepared && <Button size="sm" variant="outline" disabled={action.busy || executor} onClick={decide}>预览具名决定</Button>}
      </div>}
    </>}
    {action.prepared && <NamedCommandReview prepared={action.prepared} busy={action.busy} onCancel={action.cancel} onConfirm={() => void action.confirm("quality_issue", "有效性决定已保存。", async () => { await refresh(); await onSaved?.(); })}>
      <p className="text-xs">决定后问题状态：{String(action.prepared.review.status_after)} · 观察截止：{timeText((action.prepared.review.observation as { after?: string })?.after)}</p>
    </NamedCommandReview>}
  </section>;
}
