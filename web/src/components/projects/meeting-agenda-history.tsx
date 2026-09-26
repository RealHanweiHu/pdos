"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";

type Receipt = { id: number; time: string; actor: string; previous: string; next: string; reason: string };
function parse(value: unknown) {
  if (!isRecord(value) || !Array.isArray(value.items) || (value.next_before_id !== null && typeof value.next_before_id !== "number")) throw new Error("责任历史不完整");
  const items: Receipt[] = value.items.map(row => {
    if (!isRecord(row) || typeof row.id !== "number" || typeof row.timestamp !== "string" || !isRecord(row.context)) throw new Error("责任回执不完整");
    const c = row.context;
    if (!isRecord(c.people) || !isRecord(c.before_agenda) || !isRecord(c.after_agenda) || typeof c.reason !== "string") throw new Error("具名责任记录不完整");
    const people = c.people;
    const name = (id: unknown) => typeof id === "string" && typeof people[id] === "string" ? people[id] : "未指定";
    return { id: row.id, time: row.timestamp, actor: name(c.actor_user_id), previous: name(c.before_agenda.owner_user_id), next: name(c.after_agenda.owner_user_id), reason: c.reason };
  });
  return { items, next: value.next_before_id as number | null };
}

export function MeetingAgendaHistory({ path }: { path: string }) {
  const [items, setItems] = useState<Receipt[] | null>(null);
  const [next, setNext] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function load(more = false) {
    setBusy(true); setError(null);
    try {
      const response = await fetch(`${path}${more && next ? `?before_id=${next}` : ""}`, { cache: "no-store" });
      if (!response.ok) throw new Error("责任历史暂不可用，请重试");
      const data = parse(await responseBody(response));
      setItems(old => more ? [...(old ?? []), ...data.items] : data.items); setNext(data.next);
    } catch (e) { setError(e instanceof Error ? e.message : "读取失败"); }
    finally { setBusy(false); }
  }
  return <details className="rounded-md border p-2" onToggle={e => { if (e.currentTarget.open && !items && !busy) void load(); }}>
    <summary className="cursor-pointer text-xs">议题负责人调整历史</summary>
    <div className="mt-2 space-y-2 text-xs">
      <Button size="sm" variant="outline" disabled={busy} onClick={() => void load()}>刷新责任历史</Button>
      {items?.length === 0 && <p>尚无单独调整记录，原会议准备与复查记录保留。</p>}
      {items?.map(r => <div key={r.id} className="rounded border p-2"><p>{r.previous} → {r.next} · {r.actor} · {new Date(r.time).toLocaleString()}</p><p className="mt-1 whitespace-pre-wrap">{r.reason}</p></div>)}
      {next !== null && <Button size="sm" variant="outline" disabled={busy} onClick={() => void load(true)}>更早责任记录</Button>}
      {error && <p role="alert" className="text-destructive">{error}</p>}
    </div>
  </details>;
}
