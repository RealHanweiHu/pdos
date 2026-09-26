"use client";

import { DecisionIntakeBatchProgress } from "@/components/projects/decision-intake-batch-progress";
import { useRef, useState } from "react";
import { DecisionIntakeTarget, type IntakeTargetChoice } from "@/components/ai/decision-intake-targets";
import { Button } from "@/components/ui/button";
import { isRecord } from "@/components/workspace-api";

type Row = Record<string, unknown>;
const field = "w-full rounded-md border bg-background p-2 text-sm";
const labels: Record<string, string> = { created: "已登记历史决策", linked: "已关联已有决策", reused: "复用原登记", error: "本行未登记" };
function list(value: unknown): Row[] { return Array.isArray(value) ? value.filter(isRecord) : []; }
function text(value: unknown): string { return value == null ? "" : String(value); }
function Receipt({ receipt }: { receipt: Row }) {
  const [page, setPage] = useState(0), items = list(receipt.results), counts = isRecord(receipt.counts) ? receipt.counts : {};
  const states = isRecord(receipt.current_sources) ? receipt.current_sources : {};
  return <details className="rounded-md border p-3"><summary className="cursor-pointer">{text(receipt.created_at)} · 登记 {text(counts.created)} · 关联 {text(counts.linked ?? 0)} · 复用 {text(counts.reused)} · 未登记 {text(counts.error)}</summary>
    {typeof receipt.project_id === "string" && typeof receipt.id === "string" && <DecisionIntakeBatchProgress projectId={receipt.project_id} batchId={receipt.id}/>}
    <p className="my-2 whitespace-pre-wrap">核对说明：{text(receipt.review_note)}</p>
    {items.slice(page * 20, page * 20 + 20).map(row => <div key={text(row.row)} className="my-2 space-y-1 border-t pt-2"><p>第 {text(row.row)} 行 · {labels[text(row.status)] ?? text(row.status)} · {text(row.locator)}</p>{isRecord(states[String(row.row)]) && Number((states[String(row.row)] as Row).revision) > 0 && <p className="text-destructive">当前来源已修订：版本 {text((states[String(row.row)] as Row).revision)} · {(states[String(row.row)] as Row).state === "withdrawn" ? "已撤回；原批次回执保留" : "按当前关联继续办理，原批次回执保留"}</p>}{isRecord(states[String(row.row)]) && <div className="flex gap-3">{["current_decision_href", "current_issue_href"].map(key => typeof (states[String(row.row)] as Row)[key] === "string" && <a key={key} className="text-primary underline" href={String((states[String(row.row)] as Row)[key])}>{key === "current_decision_href" ? "当前关联决策" : "当前关联问题"}</a>)}</div>}{Array.isArray(row.errors) && row.errors.map((error, index) => <p key={index} className="text-destructive">{text(error)}</p>)}<div className="flex gap-3">{typeof row.decision_href === "string" && <a className="text-primary underline" href={row.decision_href}>查看项目决策</a>}{typeof row.issue_href === "string" && <a className="text-primary underline" href={row.issue_href}>查看关联问题</a>}{typeof row.document_href === "string" && <a className="text-primary underline" href={row.document_href}>查看已保存原件</a>}</div></div>)}
    {items.length > 20 && <div className="flex items-center gap-2"><Button type="button" size="sm" variant="outline" disabled={!page} onClick={() => setPage(p => p - 1)}>上一页回执</Button><span>{page + 1} / {Math.ceil(items.length / 20)}</span><Button type="button" size="sm" variant="outline" disabled={(page + 1) * 20 >= items.length} onClick={() => setPage(p => p + 1)}>下一页回执</Button></div>}
  </details>;
}
export function DecisionIntakeConfirmation({ preview, disabled, readOnly, act, request, reload }: {
  preview: Row; disabled: boolean; readOnly: boolean; act: (work: () => Promise<void>) => Promise<void>;
  request: (path: string, body?: object) => Promise<Row>; reload: () => Promise<void>;
}) {
  const [selected, setSelected] = useState<number[]>([]), [page, setPage] = useState(0), [note, setNote] = useState(""), [shared, setShared] = useState(false), [reviewed, setReviewed] = useState(false);
  const [latest, setLatest] = useState<Row | null>(null);
  const [reuse, setReuse] = useState<Record<number, IntakeTargetChoice | undefined>>({}), [issueLinks, setIssueLinks] = useState<Record<number, IntakeTargetChoice | undefined>>({}), [reading, setReading] = useState<Record<string, boolean>>({});
  const pending = useRef<{ signature: string; id: string } | null>(null);
  const entries = list(preview.rows), eligible = entries.filter(row => Array.isArray(row.errors) && row.errors.length === 0).map(row => Number(row.row));
  const receipts = list(preview.receipts), allReceipts = latest && !receipts.some(row => row.id === latest.id) ? [latest, ...receipts] : receipts;
  const blocked = disabled || readOnly || preview.source_current !== true;
  const targetsReady = selected.every(number => [reuse[number], issueLinks[number]].every(value => !value || !!value.target && !!value.reason.trim()));
  const working = blocked || Object.values(reading).some(Boolean);
  function changeRows(value: number[]) { setSelected(value); setReviewed(false); }
  async function confirm() {
    if (working || !targetsReady || !shared || !reviewed || !note.trim() || !selected.length) return;
    const body = { expected_digest: preview.request_digest, rows: [...selected].sort((a, b) => a - b), review_note: note.trim(), publish_to_project: true, reviewed: true, reuse: selected.filter(n => reuse[n]?.target).map(n => ({ row: n, id: reuse[n]!.target!.id, expected_digest: reuse[n]!.target!.digest, reason: reuse[n]!.reason.trim() })), issue_links: selected.filter(n => issueLinks[n]?.target).map(n => ({ row: n, id: issueLinks[n]!.target!.id, expected_digest: issueLinks[n]!.target!.digest, reason: issueLinks[n]!.reason.trim() })) }, signature = JSON.stringify(body);
    if (pending.current?.signature !== signature) pending.current = { signature, id: crypto.randomUUID() };
    const receipt = await request(`/decision-intake-previews/${text(preview.id)}/confirm`, { ...body, request_id: pending.current.id });
    setLatest(receipt); setReviewed(false); setSelected([]); pending.current = null; await reload();
  }
  return <section className="space-y-3 border-t pt-3">
    <h4 className="font-medium">确认登记历史决策</h4>
    <p>核对后新建历史决策，或为所选已有决策增加原文来源；所选实际问题一并建立关联。历史日期、人员、状态和缺项分别保留；本次登记不代表重新批准、关卡放行或执行完成。</p>
    <fieldset disabled={working} className="space-y-3">
      <div className="flex items-center gap-2"><Button type="button" size="sm" variant="outline" onClick={() => changeRows(eligible)}>选择全部可登记行</Button><Button type="button" size="sm" variant="outline" onClick={() => changeRows([])}>清空选择</Button><span>已选 {selected.length} / {eligible.length} 行</span></div>
      {entries.slice(page * 20, page * 20 + 20).map(row => { const values = isRecord(row.values) ? row.values : {}, number = Number(row.row), valid = eligible.includes(number); return <div key={number} className="space-y-2 border-t pt-2"><label className="flex items-start gap-2"><input type="checkbox" disabled={!valid} checked={selected.includes(number)} onChange={e => changeRows(e.target.checked ? [...selected, number] : selected.filter(n => n !== number))}/><span>第 {number} 行 · {text(values.title)}{!valid ? "（原值有误，请调整映射）" : ""}</span></label>
        {selected.includes(number) && <details><summary className="cursor-pointer">复用决策或关联问题（可选）</summary><div className="mt-2 space-y-2">{(["decision", "issue"] as const).map(kind => <DecisionIntakeTarget key={kind} base={`/api/conversations/${text(preview.conversation_id)}/decision-intake-previews/${text(preview.id)}`} kind={kind} original={values} value={kind === "decision" ? reuse[number] : issueLinks[number]} disabled={blocked} onBusyChange={value => setReading(old => ({ ...old, [`${number}-${kind}`]: value }))} onChange={value => { (kind === "decision" ? setReuse : setIssueLinks)(old => ({ ...old, [number]: value })); setReviewed(false); }}/>)}</div></details>}
      </div>; })}
      {entries.length > 20 && <div className="flex items-center gap-2"><Button type="button" size="sm" variant="outline" disabled={!page} onClick={() => setPage(p => p - 1)}>上一页选择</Button><span>{page + 1} / {Math.ceil(entries.length / 20)}</span><Button type="button" size="sm" variant="outline" disabled={(page + 1) * 20 >= entries.length} onClick={() => setPage(p => p + 1)}>下一页选择</Button></div>}
      <label className="block">具名核对说明<textarea className={field} maxLength={4000} value={note} onChange={e => { setNote(e.target.value); setReviewed(false); }}/></label>
      <label className="flex items-start gap-2"><input type="checkbox" checked={shared} onChange={e => setShared(e.target.checked)}/><span>我同意将整份原件及所选行的原文、映射、许可依据和核对说明保存为项目资料，供有相应项目权限的成员读取。</span></label>
      <label className="flex items-start gap-2"><input type="checkbox" checked={reviewed} onChange={e => setReviewed(e.target.checked)}/><span>我已核对所选行的原文、日期、人员和缺项。所选复用决策及关联问题已有明确对应依据；未选择实际问题的原编号保留为原文说明。</span></label>
      <Button type="button" disabled={!targetsReady || !selected.length || !shared || !reviewed || !note.trim()} onClick={() => void act(confirm)}>确认所选登记与关联</Button>
    </fieldset>
    <Button type="button" size="sm" variant="outline" disabled={disabled} onClick={() => void act(reload)}>读取已保存回执</Button>
    {allReceipts.length > 0 && <div className="space-y-2"><p>最近100次登记回执。同原件同一来源位置相同映射会复用原记录。</p>{allReceipts.map(receipt => <Receipt key={text(receipt.id)} receipt={receipt}/>)}</div>}
  </section>;
}
