"use client";

import { useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";
import { MeetingReviewCandidates, type ReviewCandidate } from "./meeting-review-candidates";

const input = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
const statusLabels: Record<string,string> = {forecast_historical:"已存在新版",forecast_stale:"依据需更新",forecast_unknown:"仍有待定项",forecast_current:"依据一致",todo:"待办",in_progress:"进行中",blocked:"受阻",pending_approval:"待批准",done:"完成",skipped:"不适用",open:"待处理",analysis:"分析中",action:"改善中",verification:"待验证",closed:"已关闭",preparing:"准备中",reviewing:"审阅中",approved:"已批准",conditional:"附条件批准",hold:"暂缓",rejected:"未通过"};
const kinds: Record<string, string> = { material:"物料异常原问题",task:"逾期任务/行动",issue:"未关闭问题",gate:"待处理关卡",forecast:"正式排程预测" };
type Source = { summary: string[]; priority: string; expertise: string[]; kind: string; id: string; title: string; status: string; digest: string; href: string; owner_user_id: string | null };
type Agenda = { key: string; id: string | null; title: string; item_kind: string; detail: string; owner_user_id: string | null;
  source_kind: string | null; source_entity_id: string | null; source_digest: string | null; carried_from_item_id: string | null;
  source: Source | null; source_current: boolean | null };
type Member = { id: string; display_name: string; role: string };
type Preparation = { digest: string; organizer: string; editable: boolean; members: Member[]; agenda: Agenda[];
  participants: Record<string, "required" | "optional">; template: { label: string; topics: string[]; disciplines: string[] };
  sources: { kind: string; items: Source[]; has_more: boolean }[]; unavailable: string[] };
function text(value: unknown): string { if (typeof value !== "string") throw new Error("会前资料不完整"); return value; }
function uuid(value: unknown): string { const result = text(value); if (!/^[0-9a-f-]{36}$/.test(result)) throw new Error("会议对象标识不完整"); return result; }
function nullable(value: unknown): string | null { return value === null ? null : text(value); }
function strings(value: unknown): string[] { if (!Array.isArray(value)) throw new Error("会议模板不完整"); return value.map(text); }
function source(value: unknown, projectId: string): Source {
  if (!isRecord(value)) throw new Error("议题来源不完整");
  const href = text(value.href);
  if (!href.startsWith(`/projects?project=${projectId}&`)) throw new Error("议题来源超出当前项目");
  return { summary:value.summary === undefined ? [] : strings(value.summary),priority:text(value.priority),expertise:strings(value.expertise),kind:text(value.kind),id:uuid(value.id),title:text(value.title),status:text(value.status),digest:text(value.digest),href,owner_user_id:nullable(value.owner_user_id) };
}
function parse(value: unknown, projectId: string): Preparation {
  if (!isRecord(value) || !isRecord(value.meeting) || !isRecord(value.template) || !Array.isArray(value.members)
    || !Array.isArray(value.agenda) || !Array.isArray(value.sources) || !Array.isArray(value.participants)) throw new Error("会前资料不完整");
  const participants: Preparation["participants"] = {};
  for (const item of value.participants) {
    if (!isRecord(item)) throw new Error("参会名单不完整");
    if (item.participation === "required" || item.participation === "optional") participants[uuid(item.user_id)] = item.participation;
    else if (item.participation !== "organizer") throw new Error("参会身份不完整");
  }
  return { digest:text(value.digest),organizer:uuid(value.meeting.organizer_user_id),
    editable:["scheduled","in_progress"].includes(String(value.meeting.status)) && value.meeting.archived_at === null && value.meeting.deleted_at === null,
    members:value.members.map(item => { if (!isRecord(item)) throw new Error("项目成员不完整"); return {id:uuid(item.id),display_name:text(item.display_name),role:text(item.role)}; }),
    participants, template:{label:text(value.template.label),topics:strings(value.template.topics),disciplines:strings(value.template.disciplines)},
    agenda:value.agenda.map(item => { if (!isRecord(item)) throw new Error("议程不完整"); return {key:uuid(item.id),id:uuid(item.id),title:text(item.title),item_kind:text(item.item_kind),detail:nullable(item.detail) ?? "",owner_user_id:nullable(item.owner_user_id),source_kind:nullable(item.source_kind),source_entity_id:nullable(item.source_entity_id),source_digest:nullable(item.source_digest),carried_from_item_id:nullable(item.carried_from_item_id),source:item.source === null ? null : source(item.source,projectId),source_current:item.source_current === null ? null : item.source_current === true}; }),
    sources:value.sources.map(group => { if (!isRecord(group) || !Array.isArray(group.items)) throw new Error("例外资料不完整"); return {kind:text(group.kind),items:group.items.map(item => source(item,projectId)),has_more:group.has_more === true}; }),unavailable:strings(value.unavailable) };
}
async function request(path: string, body?: object): Promise<unknown> {
  const response = await fetch(path,{method:body ? "POST" : "GET",cache:"no-store",headers:body ? {"Content-Type":"application/json"} : undefined,body:body ? JSON.stringify(body) : undefined});
  const value: unknown = await responseBody(response).catch(() => null);
  if (!response.ok) throw new Error(isRecord(value) && isRecord(value.detail) && typeof value.detail.message === "string" ? value.detail.message : "会议资料暂不可用，请刷新核对结果");
  return value;
}
function newItem(title: string, origin?: Source): Agenda {
  return {key:crypto.randomUUID(),id:null,title:title.slice(0,256),item_kind:origin ? "exception" : "topic",detail:"",owner_user_id:origin?.owner_user_id ?? null,source_kind:origin?.kind ?? null,source_entity_id:origin?.id ?? null,source_digest:origin?.digest ?? null,carried_from_item_id:null,source:origin ?? null,source_current:origin ? true : null};
}

export function MeetingPreparation({ projectId, meetingId, canManage, isActive, onChanged }: { projectId: string; meetingId: string; canManage: boolean; isActive: boolean; onChanged: () => Promise<void> }) {
  const search = useSearchParams();
  const focusUser = search.get("meeting") === meetingId ? search.get("meeting_roster_user") : null;
  const focused = !!focusUser && /^[0-9a-f-]{36}$/.test(focusUser);
  const [rosterPreview, setRosterPreview] = useState<Preparation | null>(null);
  const [data,setData] = useState<Preparation | null>(null);
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState<string | null>(null);
  const [notice,setNotice] = useState<string | null>(null);
  const [dirty,setDirty] = useState(false);
  const [reviewRevision,setReviewRevision] = useState(0);
  const previous = useRef<{signature:string;id:string} | null>(null);
  const path = `/api/projects/${projectId}/meetings/${meetingId}/preparation`;
  async function load() { const current = parse(await request(path),projectId);setData(current);setRosterPreview(current);setDirty(false);setReviewRevision(current => current + 1); }
  async function act(work: () => Promise<void>) { setBusy(true);setError(null);try {await work();} catch(error) {setError(error instanceof Error ? error.message : "办理未完成");} finally {setBusy(false);} }
  function change(next: Preparation) {setData(next);setDirty(true);setNotice(null);}
  function patch(key: string, fields: Partial<Agenda>) { if (data) change({...data,agenda:data.agenda.map(item => item.key === key ? {...item,...fields} : item)}); }
  async function save() {
    if (!data) return;
    const body = {expected_digest:data.digest,organizer_id:data.organizer,participants:Object.entries(data.participants).filter(([id]) => id !== data.organizer).map(([user_id,participation]) => ({user_id,participation})),items:data.agenda.map(({key,source,source_current,...item}) => {void key;void source;void source_current;return {...item,detail:item.detail || null};})};
    const signature = JSON.stringify(body);if(previous.current?.signature !== signature) previous.current = {signature,id:crypto.randomUUID()};
    await request(path,{...body,request_id:previous.current.id});setNotice("议程与参会名单已保存，未发送外部邀请。");await load();await onChanged();
  }
  async function carry(entry: ReviewCandidate, reason: string, requestId: string) {
    if (dirty || busy || !canManage || !isActive || !data?.editable) throw new Error("请先保存当前议程修改，并核对会议仍可编辑");
    setBusy(true); setError(null); setNotice(null);
    try {
      await request(`/api/projects/${projectId}/meetings/${entry.meetingId}/agenda/${entry.id}/followup`, {
        action: "carry", expected_basis: entry.basis, reason, request_id: requestId, target_meeting_id: meetingId,
      });
      setNotice("已承接到本次复查议程，沿用原行动任务。请核对负责人和最新业务来源。");
      await load(); await onChanged();
    } finally { setBusy(false); }
  }
  const suggestedOwners = data ? [...new Set(data.agenda.flatMap(item => [item.owner_user_id,item.source?.owner_user_id]).filter((id): id is string => !!id && id!==data.organizer && data.members.some(member => member.id===id)))] : [];
  const editable = canManage && isActive && data?.editable && !busy;
  return <details open={focused || undefined} className="rounded-lg border p-3" onToggle={event => {if(event.currentTarget.open && !data && !busy) void act(load);}}>
    <summary className="cursor-pointer text-sm font-medium">会前资料、参会人与议程</summary>
    <div className="mt-3 space-y-4"><Button size="sm" variant="outline" disabled={busy} onClick={() => void act(load)}>{dirty ? "放弃未保存修改并刷新" : "刷新当前资料"}</Button>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}{notice && <p role="status" className="text-sm">{notice}</p>}
      {data && <>
        <MeetingReviewCandidates key={`${data.digest}:${reviewRevision}`} projectId={projectId} meetingId={meetingId} editable={!!editable} dirty={dirty} locked={busy} onCarry={carry} />
        <section className="space-y-2"><h4 className="text-sm font-medium">{data.template.label}模板</h4><p className="text-xs text-muted-foreground">建议结合议题邀请：{data.template.disciplines.join("、")}。这是专业职责提示，权限角色不能代替专业资格。</p><ol className="list-decimal pl-5 text-sm">{data.template.topics.map(topic => <li key={topic}>{topic}</li>)}</ol>{editable && <Button size="sm" variant="outline" onClick={() => change({...data,agenda:[...data.agenda,...data.template.topics.filter(topic => !data.agenda.some(item => item.title === topic)).map(topic => newItem(topic))]})}>将未列入的模板议题加入议程</Button>}</section>
        <section className="space-y-2"><h4 className="text-sm font-medium">具名组织者与参会人</h4>{focused && <p className="text-sm">本次移交人员：{data.members.find(member => member.id === focusUser)?.display_name ?? "原成员当前不在可选名单"} · {data.organizer === focusUser ? "当前组织者" : data.participants[focusUser!] === "required" ? "当前必需参会" : data.participants[focusUser!] === "optional" ? "当前可选参会" : "已不在当前名单"}。议题及行动任务责任另行办理。</p>}<label className="block text-xs">组织者<select className={input} disabled={!editable} value={data.organizer} onChange={event => change({...data,organizer:event.target.value})}>{!data.members.some(member => member.id === data.organizer) && <option value={data.organizer}>原组织者已不在当前可选成员中</option>}{data.members.map(member => <option key={member.id} value={member.id}>{member.display_name}</option>)}</select></label>
          {data.members.filter(member => member.id !== data.organizer).map(member => <label key={member.id} className={`flex items-center justify-between gap-2 text-sm ${member.id === focusUser ? "rounded-md border border-primary p-2" : ""}`}>{member.display_name}<select disabled={!editable} className="rounded-md border bg-background p-1 text-xs" value={data.participants[member.id] ?? ""} onChange={event => {const participants={...data.participants};if(event.target.value) participants[member.id]=event.target.value as "required"|"optional";else delete participants[member.id];change({...data,participants});}}><option value="">不列入</option><option value="required">必需参会</option><option value="optional">可选参会</option></select></label>)}
          {Object.keys(data.participants).filter(id => !data.members.some(member => member.id === id)).map(id => <p key={id} className="text-xs text-destructive">原参会人已不在当前项目可选名单中。{editable && <Button size="sm" variant="outline" onClick={() => {const participants={...data.participants};delete participants[id];change({...data,participants});}}>移出名单</Button>}</p>)}
        </section>
        {data && suggestedOwners.length>0 && <div className="space-y-2"><p className="text-xs">所选议题相关负责人：{suggestedOwners.map(id => data.members.find(member => member.id===id)?.display_name).join("、")}</p>{editable && <Button size="sm" variant="outline" onClick={() => {const participants={...data.participants};suggestedOwners.forEach(id => {participants[id]="required";});change({...data,participants});}}>将所选议题负责人列为必需参会</Button>}</div>}
        <section className="space-y-2"><h4 className="text-sm font-medium">当前会前资料与例外</h4><p className="text-xs text-muted-foreground">按当前项目权限读取；每类最多50项，完整记录在对应业务页面。逾期按当前UTC日期计算；排程预测另列实际版本、依据与待定项。</p>{data.sources.map(group => <details key={group.kind} className="rounded-md border p-2"><summary className="cursor-pointer text-sm">{kinds[group.kind] ?? group.kind} · {group.items.length} 项{group.has_more ? "（还有更多）" : ""}</summary><ul className="mt-2 space-y-2">{group.items.map(origin => <li key={origin.id} className="flex flex-wrap items-center gap-2 text-sm"><a className="text-primary underline" href={origin.href}>{origin.title}</a><span className="text-xs text-muted-foreground">当前状态：{statusLabels[origin.status] ?? origin.status}{origin.priority === "high" ? " · 高优先级" : origin.priority === "critical" ? " · 关键问题" : ""}{origin.expertise.length ? ` · 建议核对专业：${origin.expertise.join("、")}` : ""}</span>{origin.summary.length > 0 && <ul className="w-full space-y-1 text-xs text-muted-foreground">{origin.summary.map((line, index) => <li key={index}>{line}</li>)}</ul>}{editable && <Button size="sm" variant="outline" disabled={data.agenda.some(item => item.source_kind===origin.kind && item.source_entity_id===origin.id)} onClick={() => change({...data,agenda:[...data.agenda,newItem(origin.title,origin)]})}>列入议程</Button>}</li>)}</ul></details>)}{data.unavailable.map(message => <p key={message} className="text-xs text-muted-foreground">{message}</p>)}</section>
        <section className="space-y-3"><h4 className="text-sm font-medium">本次议程 · {data.agenda.length} 项</h4>{data.agenda.map((item,index) => <div key={item.key} className="space-y-2 rounded-lg border p-3"><label className="block text-xs">{index+1}. 议题<input maxLength={256} className={input} disabled={!editable} value={item.title} onChange={event => patch(item.key,{title:event.target.value})}/></label><label className="block text-xs">讨论目的与待核对事项<textarea maxLength={3000} className={input} disabled={!editable} value={item.detail} onChange={event => patch(item.key,{detail:event.target.value})}/></label>
          <label className="block text-xs">议题负责人<select className={input} disabled={!editable} value={item.owner_user_id ?? ""} onChange={event => patch(item.key,{owner_user_id:event.target.value || null})}><option value="">尚未指定</option>{item.owner_user_id && !data.members.some(member => member.id===item.owner_user_id) && <option value={item.owner_user_id}>原负责人已不在可选名单中</option>}{data.members.map(member => <option key={member.id} value={member.id}>{member.display_name}</option>)}</select></label>
          {item.source && <p className="text-xs"><a className="text-primary underline" href={item.source.href}>查看来源：{item.source.title}</a> · 当前状态：{statusLabels[item.source.status] ?? item.source.status}</p>}
          {item.source && item.source.summary.length > 0 && <ul className="space-y-1 text-xs text-muted-foreground">{item.source.summary.map((line, index) => <li key={index}>{line}</li>)}</ul>}
          {item.source_kind && !item.source_current && <p className="text-xs text-destructive">{item.source ? "来源已变化或尚未核对版本，保存前请复查。" : "原来源已不可用或此类型尚未接入。"}{editable && item.source && <Button size="sm" variant="outline" onClick={() => patch(item.key,{source_digest:item.source!.digest,source_current:true})}>已核对当前来源</Button>}</p>}
          {editable && <div className="flex gap-2"><Button size="sm" variant="outline" disabled={index===0} onClick={() => {const agenda=[...data.agenda];[agenda[index-1],agenda[index]]=[agenda[index],agenda[index-1]];change({...data,agenda});}}>上移</Button><Button size="sm" variant="outline" onClick={() => change({...data,agenda:data.agenda.filter(row => row.key!==item.key)})}>移出本次议程</Button></div>}
        </div>)}{editable && <Button size="sm" variant="outline" disabled={data.agenda.length>=100} onClick={() => change({...data,agenda:[...data.agenda,newItem("")]})}>添加手工议题</Button>}</section>
        {dirty && rosterPreview && <section className="space-y-2 rounded-md border p-3 text-sm"><h4 className="font-medium">本次名单变更</h4>{[...new Set([rosterPreview.organizer, data.organizer, ...Object.keys(rosterPreview.participants), ...Object.keys(data.participants)])].map(id => {
          const before = id === rosterPreview.organizer ? "组织者" : rosterPreview.participants[id] === "required" ? "必需参会" : rosterPreview.participants[id] === "optional" ? "可选参会" : "不列入";
          const after = id === data.organizer ? "组织者" : data.participants[id] === "required" ? "必需参会" : data.participants[id] === "optional" ? "可选参会" : "不列入";
          return before === after ? null : <p key={id}>{data.members.find(member => member.id === id)?.display_name ?? `原成员 ${id}`}：{before} → {after}</p>;
        })}<p className="text-xs text-muted-foreground">与本次议程一并保存；保留原名单审计，不发送外部邀请。原议题负责人不会自动改派。</p></section>}
        {canManage && isActive && data.editable && <Button disabled={busy || !dirty || data.agenda.length>100 || data.agenda.some(item => !item.title.trim() || (item.source_kind && !item.source_current))} onClick={() => void act(save)}>保存议程与参会名单</Button>}
      </>}
    </div>
  </details>;
}
