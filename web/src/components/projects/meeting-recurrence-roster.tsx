"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { MeetingAutoGeneration } from "./meeting-auto-generation";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";

type Participant = { user_id: string; participation: "required" | "optional" };
type Recurrence = { id: string; title: string; cadence: string; timezone: string; status: "active" | "paused"; day_of_week: number | null; day_of_month: number | null; start_minute_of_day: number; duration_minutes: number; default_participants: Participant[]; agenda_template: { title: string; owner_user_id?: string | null; detail?: string | null }[] };
type History = { id: number; created_at: string; actor_user_id: string; before_snapshot: Recurrence; after_snapshot: Recurrence; context: { reason: string; people: Record<string, string> } };
type Data = { record: Recurrence; digest: string; members: { id: string; display_name: string }[]; can_manage: boolean; history: History[]; next_before_id: number | null };
type Command = { request_id: string; expected_digest: string; participants: Participant[]; agenda_owners: (string | null)[]; status: "active" | "paused"; reason: string };
const field = "mt-1 w-full rounded-md border bg-background p-2";
const role = { required: "必需参会", optional: "可选参会" };
const state = { active: "启用", paused: "暂停" };
function message(value: unknown) { return isRecord(value) && isRecord(value.detail) && typeof value.detail.message === "string" ? value.detail.message : "周期会议办理结果待确认，请重试原请求"; }
export function MeetingRecurrenceRosterLanding({ projectId }: { projectId: string }) {
  const id = useSearchParams().get("meeting_recurrence");
  if (!id || !/^[0-9a-f-]{36}$/i.test(id)) return null;
  return <><Roster key={`${projectId}:${id}`} projectId={projectId} id={id}/><MeetingAutoGeneration key={`automatic:${projectId}:${id}`} projectId={projectId} recurrenceId={id}/></>;
}
function Roster({ projectId, id }: { projectId: string; id: string }) {
  const path = `/api/projects/${projectId}/meetings/recurrences/${id}/roster`;
  const [data, setData] = useState<Data | null>(null), [draft, setDraft] = useState<Command | null>(null);
  const [preview, setPreview] = useState(false), [pending, setPending] = useState(false), [busy, setBusy] = useState(false);
  const [error, setError] = useState(""), [notice, setNotice] = useState("");
  useEffect(() => {
    let active = true;
    void fetch(path, { cache: "no-store" }).then(async response => {
      const value = await responseBody(response);
      if (!response.ok) throw new Error(message(value));
      if (!isRecord(value) || !isRecord(value.record) || value.record.id !== id || !Array.isArray(value.members) || !Array.isArray(value.history)) throw new Error("周期会议回执不完整");
      if (active) setData(value as Data);
    }).catch(e => { if (active) setError(e instanceof Error ? e.message : "读取失败"); });
    return () => { active = false; };
  }, [id, path]);
  async function load(before?: number) {
    const response = await fetch(`${path}${before ? `?before_id=${before}` : ""}`, { cache: "no-store" });
    const value = await responseBody(response);
    if (!response.ok) throw new Error(message(value));
    if (!isRecord(value) || !isRecord(value.record) || value.record.id !== id || !Array.isArray(value.history)) throw new Error("周期会议回执不完整");
    const result = value as Data;
    setData(old => before && old ? { ...old, history: [...old.history, ...result.history.filter(row => !old.history.some(prior => prior.id === row.id))], next_before_id: result.next_before_id } : result);
  }
  async function refresh(before?: number) { setBusy(true); setError(""); try { await load(before); } catch (e) { setError(e instanceof Error ? e.message : "读取失败"); } finally { setBusy(false); } }
  async function save() {
    if (!draft) return;
    setBusy(true); setError(""); setPending(true);
    try {
      const response = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(draft) });
      const value = await responseBody(response);
      if (!response.ok) { if ([400, 401, 403, 404, 409, 422].includes(response.status)) { setPending(false); setPreview(false); } throw new Error(message(value)); }
      if (!isRecord(value) || value.request_id !== draft.request_id || typeof value.audit_id !== "number") throw new Error("保存回执不完整，请按原请求重试");
      setNotice(`后续会议配置已保存，回执 ${value.audit_id}；已生成会议保留原名单。`); setPending(false); setPreview(false); setDraft(null); await load();
    } catch (e) { setError(e instanceof Error ? e.message : "保存结果待确认"); }
    finally { setBusy(false); }
  }
  const name = (person: string | null | undefined) => data?.members.find(m => m.id === person)?.display_name ?? (person ? `原成员 ${person}` : "未指定");
  function rosterSummary(record: Recurrence, people: Record<string, string> = {}) {
    const who = (person: string | null | undefined) => person ? people[person] ?? name(person) : "未指定";
    return <div className="space-y-1"><p>{state[record.status]}</p><p>默认名单：{record.default_participants.map(p => `${who(p.user_id)}（${role[p.participation] ?? p.participation}）`).join("、") || "无"}</p>{record.agenda_template.map((item, index) => <p key={index}>议题 {index + 1}：{item.title} · {who(item.owner_user_id)}</p>)}</div>;
  }
  return <section className="mb-4 space-y-3 rounded-md border p-4 text-sm"><h3 className="font-medium">周期会议默认人员接续</h3>{error && <p role="alert" className="text-destructive">{error}</p>}{notice && <p role="status">{notice}</p>}
    <Button size="sm" variant="outline" disabled={busy || !!draft} onClick={() => void refresh()}>刷新原配置</Button>
    {data && <><p>{data.record.title} · {({ weekly: "每周", biweekly: "每两周", monthly: "每月" } as Record<string, string>)[data.record.cadence]} · {data.record.timezone}</p>{rosterSummary(data.record)}<p>默认人员用于后续生成；组织者仍为实际发起生成的人。单场已生成会议、议题及行动任务仍分别办理。</p>
      {!draft && data.can_manage && <Button size="sm" disabled={busy} onClick={() => { setNotice(""); setDraft({ request_id: crypto.randomUUID(), expected_digest: data.digest, participants: data.record.default_participants.map(p => ({ ...p })), agenda_owners: data.record.agenda_template.map(item => item.owner_user_id ?? null), status: data.record.status, reason: "" }); }}>调整默认人员或暂停</Button>}
      {draft && <fieldset disabled={busy || preview || pending} className="space-y-3 rounded-md border p-3"><label className="block">后续生成<select className={field} value={draft.status} onChange={e => setDraft({ ...draft, status: e.target.value as Command["status"] })}><option value="active">启用</option><option value="paused">暂停</option></select></label><p className="text-xs">暂停保留默认名单；重新启用须核对默认人员和议题负责人仍为有效项目成员。</p>
        {data.members.map(member => <label key={member.id} className="flex items-center justify-between gap-2">{member.display_name}<select className="rounded-md border bg-background p-1" value={draft.participants.find(p => p.user_id === member.id)?.participation ?? ""} onChange={e => setDraft({ ...draft, participants: [...draft.participants.filter(p => p.user_id !== member.id), ...(e.target.value ? [{ user_id: member.id, participation: e.target.value as Participant["participation"] }] : [])] })}><option value="">不列入</option><option value="required">必需</option><option value="optional">可选</option></select></label>)}
        {draft.participants.filter(p => !data.members.some(m => m.id === p.user_id)).map(p => <div key={p.user_id}>{name(p.user_id)} 已不在可选成员中。<Button size="sm" variant="outline" onClick={() => setDraft({ ...draft, participants: draft.participants.filter(value => value.user_id !== p.user_id) })}>移出默认名单</Button></div>)}
        {data.record.agenda_template.map((item, index) => <label className="block" key={index}>议题 {index + 1}：{item.title}<select className={field} value={draft.agenda_owners[index] ?? ""} onChange={e => setDraft({ ...draft, agenda_owners: draft.agenda_owners.map((person, at) => at === index ? e.target.value || null : person) })}><option value="">未指定</option>{draft.agenda_owners[index] && !data.members.some(m => m.id === draft.agenda_owners[index]) && <option value={draft.agenda_owners[index]!}>原负责人当前不可用</option>}{data.members.map(member => <option key={member.id} value={member.id}>{member.display_name}</option>)}</select></label>)}
        <label className="block">调整依据<textarea className={field} maxLength={2048} value={draft.reason} onChange={e => setDraft({ ...draft, reason: e.target.value })}/></label><Button size="sm" disabled={!draft.reason.trim()} onClick={() => setPreview(true)}>预览本次调整</Button><Button size="sm" variant="ghost" onClick={() => setDraft(null)}>放弃编辑</Button>
      </fieldset>}
      {preview && draft && !pending && <div className="space-y-2 rounded-md border p-3"><h4 className="font-medium">保存后的默认配置</h4>{rosterSummary({ ...data.record, status: draft.status, default_participants: draft.participants, agenda_template: data.record.agenda_template.map((item, index) => ({ ...item, owner_user_id: draft.agenda_owners[index] })) })}<p className="whitespace-pre-wrap">{draft.reason}</p><Button size="sm" disabled={busy} onClick={() => void save()}>确认保存后续配置</Button><Button size="sm" variant="ghost" disabled={busy} onClick={() => setPreview(false)}>返回修改</Button></div>}
      {pending && <Button size="sm" disabled={busy} onClick={() => void save()}>按原请求重试</Button>}
      <details><summary className="cursor-pointer">历次默认人员调整</summary>{data.history.map(row => <article key={row.id} className="my-2 space-y-2 rounded-md border p-2"><p>{new Date(row.created_at).toLocaleString()} · {row.context.people[row.actor_user_id] ?? row.actor_user_id}</p><p className="whitespace-pre-wrap">{row.context.reason}</p><details><summary>调整前</summary>{rosterSummary(row.before_snapshot, row.context.people)}</details><details><summary>调整后</summary>{rosterSummary(row.after_snapshot, row.context.people)}</details></article>)}{!data.history.length && <p>尚无人员调整记录。</p>}{data.next_before_id && <Button size="sm" variant="outline" disabled={busy || !!draft} onClick={() => void refresh(data.next_before_id ?? undefined)}>加载更早记录</Button>}</details>
    </>}
  </section>;
}
