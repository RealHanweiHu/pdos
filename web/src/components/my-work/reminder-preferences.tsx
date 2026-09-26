"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { caseLinkRequest } from "@/components/cases/case-requirements";

type Preference = { version: number; daily_cap: number | null; quiet_hours: string | null; created_at: string | null };
type Snapshot = {
  preference: Preference;
  effective: { daily_cap: number; quiet_hours: string[]; quiet_now: boolean; timezone: string };
  system: { daily_cap: number; quiet_hours: string };
  delivery_enabled: boolean; local_day: string;
  reserved_today: number; remaining_today: number;
  enqueued_today: number; enqueue_remaining_today: number;
  history: Preference[]; next_before_version: number | null;
};
const path = "me/reminder-preferences";
function describe(value: Preference) {
  return `每日额度：${value.daily_cap === null ? "跟随系统" : value.daily_cap === 0 ? "暂停提醒私信" : `${value.daily_cap} 条`}；额外静默：${value.quiet_hours ?? "无"}`;
}

export function ReminderPreferences() {
  const [open, setOpen] = useState(false), [data, setData] = useState<Snapshot | null>(null);
  const [cap, setCap] = useState(""), [quiet, setQuiet] = useState(false);
  const [start, setStart] = useState("18:00"), [end, setEnd] = useState("09:00");
  const [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null), [stale, setStale] = useState(false);
  function adopt(value: Snapshot) {
    setData(value); setCap(value.preference.daily_cap?.toString() ?? "");
    setQuiet(value.preference.quiet_hours !== null);
    if (value.preference.quiet_hours) { const [from, to] = value.preference.quiet_hours.split("-"); setStart(from); setEnd(to); }
  }
  async function load(keepDraft = false, before?: number) {
    if (busy) return;
    setBusy(true); setError(null);
    try {
      const result = await caseLinkRequest<Snapshot>(`${path}${before ? `?before_version=${before}` : ""}`);
      if (before) setData(current => current ? { ...current, history: [...current.history, ...result.history], next_before_version: result.next_before_version } : result);
      else if (keepDraft) { setData(result); setStale(false); setNotice("已读取当前设置，未保存输入保留；请核对下方差异后保存。"); }
      else { adopt(result); setStale(false); }
    } catch (failure) { setError(failure instanceof Error ? failure.message : "提醒设置读取失败"); }
    finally { setBusy(false); }
  }
  const proposed: Preference = { version: data?.preference.version ?? 0, daily_cap: cap === "" ? null : Number(cap), quiet_hours: quiet ? `${start}-${end}` : null, created_at: null };
  const valid = (cap === "" || /^\d+$/.test(cap) && Number(cap) <= 1000) && (!quiet || !!start && !!end && start !== end);
  const changed = !!data && (proposed.daily_cap !== data.preference.daily_cap || proposed.quiet_hours !== data.preference.quiet_hours);
  async function save() {
    if (!data || !valid || stale || busy) return;
    setBusy(true); setError(null); setNotice(null);
    try {
      const result = await caseLinkRequest<Snapshot>(path, { expected_version: data.preference.version, daily_cap: proposed.daily_cap, quiet_hours: proposed.quiet_hours });
      adopt(result); setNotice(`已保存提醒设置 v${result.preference.version}。未领取发送的提醒会按新设置处理。`);
    } catch (failure) { setStale(true); setError(failure instanceof Error ? failure.message : "保存结果未确认，请先刷新当前设置。"); }
    finally { setBusy(false); }
  }
  return <section aria-label="提醒设置" className="mt-4 rounded-lg border bg-card p-3 text-sm">
    <Button variant="ghost" size="sm" aria-expanded={open} onClick={() => { setOpen(value => !value); if (!open && !data) void load(); }}>{open ? "收起提醒设置" : "提醒时段与每日额度"}</Button>
    {open && <div className="mt-3 space-y-3">
      <p className="text-muted-foreground">调整本人钉钉提醒私信。站内待办、业务期限和升级责任继续保留；设置适用于尚未领取发送的提醒，已在途消息无法撤回。会议邀请、审批及其他消息沿用各自流程。</p>
      {error && <p role="alert" className="text-destructive">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      {!data ? <Button variant="outline" disabled={busy} onClick={() => void load()}>{busy ? "正在读取…" : "重新读取设置"}</Button> : <>
        <div className="rounded-md bg-muted/30 p-3 text-xs leading-6">
          <p>按 {data.effective.timezone} 计时 · {data.local_day} · 外发开关：{data.delivery_enabled ? "已开启" : "关闭（保存个人设置不会开启外发）"}</p>
          <p>系统上限 {data.system.daily_cap} 条/日；系统静默 {data.system.quiet_hours}。个人额度只能收紧系统上限，个人静默与系统时段合并。</p>
          <p>当前生效上限 {data.effective.daily_cap} 条/日；{data.effective.quiet_now ? "当前在静默时段" : "当前不在静默时段"}；静默时段：{data.effective.quiet_hours.join("、")}。</p>
          <p>今日入队 {data.enqueued_today} 条，入队剩余额度 {data.enqueue_remaining_today} 条；发送占用 {data.reserved_today} 条，发送剩余额度 {data.remaining_today} 条。</p>
          <p>发送占用包含已领取、失败或结果未知的消息，不代表已送达；同一消息当天重试复用占用。静默或额度不足会暂缓，通常在后续扫描或发送检查中继续，已有队列约每5分钟重查。</p>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <label className="space-y-1"><span className="block">本人每日上限</span><input className="rounded-md border bg-background p-2" type="number" min="0" max="1000" step="1" value={cap} placeholder="留空跟随系统" onChange={event => setCap(event.target.value)}/><span className="block text-xs text-muted-foreground">0 暂停私信；留空跟随系统。</span></label>
          <label className="flex min-h-11 items-center gap-2"><input type="checkbox" checked={quiet} onChange={event => setQuiet(event.target.checked)}/>增加本人静默时段</label>
          {quiet && <><label>开始<input aria-label="额外静默开始时间" type="time" value={start} onChange={event => setStart(event.target.value)} className="ml-2 rounded-md border bg-background p-2"/></label><label>结束<input aria-label="额外静默结束时间" type="time" value={end} onChange={event => setEnd(event.target.value)} className="ml-2 rounded-md border bg-background p-2"/></label></>}
        </div>
        {quiet && start === end && <p className="text-destructive">请选择不同的开始和结束时间；全天暂停请将每日上限设为0。</p>}
        {changed && <div className="rounded-md border p-2 text-xs"><p>当前 v{data.preference.version}：{describe(data.preference)}</p><p>准备保存：{describe(proposed)}</p></div>}
        <div className="flex flex-wrap gap-2"><Button disabled={busy || stale || !valid || !changed} onClick={() => void save()}>保存提醒设置</Button><Button variant="outline" disabled={busy} onClick={() => void load(true)}>刷新当前设置</Button><Button variant="ghost" disabled={busy} onClick={() => { setCap(""); setQuiet(false); setNotice("已填入跟随系统的设置，请核对后保存。"); }}>填入系统默认</Button></div>
        {stale && <p className="text-xs text-muted-foreground">保存结果未确认，先刷新当前设置再继续；输入会保留。</p>}
        <details><summary className="cursor-pointer">本人设置历史（{data.history.length} 条已加载）</summary><ol className="mt-2 space-y-2">{data.history.map(value => <li className="rounded-md border p-2 text-xs" key={value.version}>v{value.version} · {value.created_at ? new Date(value.created_at).toLocaleString("zh-CN") : "系统默认"} · {describe(value)}</li>)}</ol>{data.next_before_version !== null && <Button variant="ghost" size="sm" disabled={busy} onClick={() => void load(true, data.next_before_version!)}>继续读取历史</Button>}</details>
      </>}
    </div>}
  </section>;
}
