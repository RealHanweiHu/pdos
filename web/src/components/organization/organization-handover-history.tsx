"use client";

import { useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";
import { HANDOVER_COUNT_LABELS } from "./organization-types";

type Row = Record<string, unknown>;
const rows = (v: unknown): Row[] => Array.isArray(v) ? v.filter(isRecord) : [];
const row = (v: unknown): Row => isRecord(v) ? v : {};
const text = (v: unknown) => v == null ? "" : String(v);
const safeLink = (v: unknown): v is string => typeof v === "string" && /^\/(projects\?project=[0-9a-f-]+(?:&tab=overview&id_handoff=[0-9a-f-]+&id_freeze=[0-9a-f-]+|&tab=overview&id_freeze_request=[0-9a-f-]+&id_revision=[0-9a-f-]+|&tab=overview&schedule_responsibility_node=[0-9a-f-]+|&tab=overview&approval_request_kind=(?:execution|baseline)&approval_request_id=[0-9a-f-]+|&tab=overview&approval_policy_kind=(?:execution|baseline|commitment)&approval_policy_id=[0-9a-f-]+|&tab=overview&id_owner_revision=[0-9a-f-]+|&tab=overview&input_wait_id=[0-9a-f-]+|&tab=decisions&meeting_recurrence=[0-9a-f-]+|&tab=decisions&meeting=[0-9a-f-]+&meeting_roster_user=[0-9a-f-]+|&tab=decisions&meeting=[0-9a-f-]+&agenda_owner_id=[0-9a-f-]+|&tab=decisions&decision_owner_id=[0-9a-f-]+|&tab=overview&specification_owner_id=[0-9a-f-]+|&tab=overview&resource_allocation_id=[0-9a-f-]+|&tab=overview&resource_reservation_id=[0-9a-f-]+|&tab=overview&reservation_owner_id=[0-9a-f-]+|&tab=quality&quality_owner_kind=(?:complaint|ncr|capa|certification)&quality_owner_id=[0-9a-f-]+|&tab=overview&completion_item=(?:configuration|bom|manufacturing|test_certification|training|residuals|quality_follow_up)|&tab=gates&gate=[0-9a-f-]+&gate_round=[0-9a-f-]+&gate_signer=[0-9a-f-]+|&tab=work-items&entity_id=[0-9a-f-]+|&tab=engineering&change_ecr_id=[0-9a-f-]+&change_task_id=[0-9a-f-]+)?|product-work(?:\?space=[0-9a-f-]+&responsibility_kind=(?:research|work|definition|package|strategy|experiment|opportunity|space|node|subscription)&responsibility_id=[0-9a-f-]+)?|knowledge\?source_owner_id=[0-9a-f-]+|initial-plans\/[0-9a-f-]+(?:\?node=[a-zA-Z0-9_.:-]{1,128})?|cases(?:\/[0-9a-f-]+\/reviews\?(?:policy|review)=[0-9a-f-]+)?|governance\/organization)$/.test(v);

export function OrganizationHandoverHistory({ sourceId, targetId }: { sourceId: string; targetId: string }) {
  const [items, setItems] = useState<Row[]>([]), [next, setNext] = useState<number | null>(null);
  const [scope, setScope] = useState({ sourceId: "", targetId: "" });
  const [loaded, setLoaded] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState("");
  async function load(more = false) {
    if (busy || more && next === null) return;
    setBusy(true); setError("");
    const applied = more ? scope : { sourceId, targetId };
    try {
      const query = new URLSearchParams();
      if (applied.sourceId) query.set("from_user_id", applied.sourceId);
      if (applied.targetId) query.set("to_user_id", applied.targetId);
      if (more) query.set("before_id", String(next));
      const response = await fetch(`/api/admin/organization/handover/history?${query}`, { cache: "no-store" });
      const value = await responseBody(response);
      if (!response.ok || !isRecord(value) || !Array.isArray(value.items) || !value.items.every(item => isRecord(item) && typeof item.id === "number" && Number.isSafeInteger(item.id) && typeof item.created_at === "string" && typeof item.from_user_id === "string" && isRecord(item.after_snapshot)) || !(value.next_before_id === null || typeof value.next_before_id === "number" && Number.isSafeInteger(value.next_before_id) && value.next_before_id > 0)) throw new Error("移交历史暂不可读取，请重试");
      const received = rows(value.items);
      setItems(previous => more ? [...previous, ...received] : received); setNext(value.next_before_id); setScope(applied); setLoaded(true);
    } catch (e) { setError(e instanceof Error ? e.message : "读取失败"); }
    finally { setBusy(false); }
  }
  function groups(value: unknown) {
    return rows(value).map(group => <details key={text(group.key)} className="rounded-md border p-2"><summary className="cursor-pointer">{text(group.label)} · 当时 {text(group.count)} 项</summary>{rows(group.items).map(item => <p key={text(item.id)} className="mt-1 break-words">{safeLink(item.href) ? <Link className="text-primary underline" href={item.href}>{text(item.title)}</Link> : text(item.title) || text(item.id)}</p>)}{Array.isArray(group.reasons) ? group.reasons.map((reason, i) => <p key={i} className="mt-1 text-muted-foreground">{text(reason)}</p>) : null}</details>);
  }
  return <details className="mt-4 rounded-lg border p-3 text-xs"><summary className="cursor-pointer font-medium">人员移交历史与当时遗留清单</summary><div className="mt-3 space-y-3"><p className="text-muted-foreground">按上方选定的原负责人和接手人查询，未选成员时不限。回执记录当时的转移结果；当前是否已补齐，需重新准备移交清单核对。</p><Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void load()}>按当前成员读取／刷新历史</Button>{loaded && (scope.sourceId !== sourceId || scope.targetId !== targetId) ? <p>成员选择已变化，下方保留上次查询结果；刷新后使用新选择。</p> : null}{error ? <p role="alert" className="text-destructive">{error}</p> : null}
    {items.map(item => { const after = row(item.after_snapshot); return <article className="space-y-2 rounded-md border p-3" key={text(item.id)}><h3 className="font-medium">{text(after.from_name) || text(item.from_name) || text(item.from_user_id)} → {text(after.to_name) || text(item.to_name) || text(after.to_user_id)}</h3><p>{text(item.created_at)} · 办理人 {text(item.actor_name) || text(item.actor_user_id)} · 回执 {text(item.id)}</p>{!after.from_name ? <p className="text-muted-foreground">旧回执未固定姓名，以上姓名取当前成员记录；原成员编号保留。</p> : null}<p>当时账号：{after.deactivated === true ? "已停用" : "保留"}</p><p>{Object.entries(row(after.transferred_counts)).map(([key, count]) => `${HANDOVER_COUNT_LABELS[key] ?? key} ${text(count)}`).join(" · ")}</p>
      {Array.isArray(after.transferred_items) ? <><h4 className="font-medium">本批实际转移</h4>{groups(after.transferred_items)}</> : <details><summary className="cursor-pointer">旧回执对象编号</summary>{rows(after.objects).map(group => <p className="break-all" key={text(group.responsibility)}>{HANDOVER_COUNT_LABELS[text(group.responsibility)] ?? text(group.responsibility)}：{Array.isArray(group.object_ids) ? group.object_ids.map(text).join("、") : "未记录"}</p>)}</details>}
      <h4 className="font-medium">当时原流程遗留 {text(after.remaining_manual_count) || "0"} 项</h4>{Array.isArray(after.remaining_items) ? groups(after.remaining_items) : <p className="text-muted-foreground">旧回执仅记录当时数量，未保存逐项清单。</p>}
    </article>; })}{loaded && !items.length ? <p>此查询范围内没有移交回执。</p> : null}{next !== null ? <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void load(true)}>加载更早移交回执</Button> : null}</div></details>;
}
