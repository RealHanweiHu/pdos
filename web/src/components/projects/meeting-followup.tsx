"use client";

import { useRef, useState, useSyncExternalStore } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";

import { MeetingAgendaHistory } from "./meeting-agenda-history";

const input = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
const states: Record<string,string> = {todo:"待办",in_progress:"进行中",blocked:"受阻",done:"已完成",skipped:"已跳过",pending_approval:"待批准"};
const actions = {create_action:"创建已确认行动",link_action:"关联已有任务",close:"确认议题闭环",reopen:"重新打开议题",carry:"转入后续会议复查",reassign:"调整议题负责人"};
type Action = keyof typeof actions;
function text(value: unknown): string {if(typeof value!=="string") throw new Error("会后记录不完整");return value;}
function id(value: unknown): string {const result=text(value);if(!/^[0-9a-f-]{36}$/.test(result)) throw new Error("会后对象标识不完整");return result;}
function list(value: unknown): unknown[] {if(!Array.isArray(value)) throw new Error("会后清单不完整");return value;}
function option(value: unknown) {if(!isRecord(value)) throw new Error("办理选项不完整");return {id:id(value.id),title:text(value.title ?? value.display_name)};}
function item(value: unknown, projectId: string) {
  if(!isRecord(value)||!isRecord(value.agenda)||typeof value.closure_current!=="boolean"||typeof value.source_ready!=="boolean") throw new Error("议题办理依据不完整");
  if(isRecord(value.source) && !text(value.source.href).startsWith(`/projects?project=${projectId}&`)) throw new Error("业务来源超出当前项目");
  return {owner:typeof value.agenda.owner_user_id === "string" ? id(value.agenda.owner_user_id) : null,ownerName:typeof value.owner_name === "string" ? value.owner_name : "尚未指定",id:id(value.agenda.id),title:text(value.agenda.title),status:text(value.agenda.resolution_status),basis:text(value.basis_digest),closed:value.closure_current,sourceReady:value.source_ready,
    carriedFrom:isRecord(value.carried_from) && text(value.carried_from.href).startsWith(`/projects?project=${projectId}&`) ? text(value.carried_from.href) : null,
    reason:isRecord(value.review) ? `${text(value.review.confirmed_by)} · ${text(value.review.reason)}` : null,
    incomplete:list(value.incomplete_action_ids).map(id),
    tasks:list(value.actions).map(task => {if(!isRecord(task)) throw new Error("行动记录不完整");const taskId=id(task.id);return {findingId: typeof task.source_finding_id === "string" ? id(task.source_finding_id) : null, id:taskId,title:text(task.title),status:text(task.status),owner:task.assignee_user_id===null ? null : id(task.assignee_user_id),date:task.due_date===null ? null : text(task.due_date),standard:task.expected_output===null ? null : text(task.expected_output),evidence:task.completion_evidence_ref===null ? null : text(task.completion_evidence_ref),href:`/projects?project=${projectId}&tab=work-items&entity_id=${taskId}`};}),
    source:isRecord(value.source) ? {kind:text(value.source.kind),summary:Array.isArray(value.source.summary) ? value.source.summary.map(text) : [],title:text(value.source.title),href:text(value.source.href)} : null};
}
type Item = ReturnType<typeof item>;
function parse(value: unknown, projectId: string) {
  if(!isRecord(value)||typeof value.editable!=="boolean") throw new Error("会后办理记录不完整");
  return {editable:value.editable,items:list(value.items).map(row => item(row,projectId)),members:list(value.members).map(option),responsibilityMembers:list(value.responsibility_members).map(option),tasks:list(value.tasks).map(option),targets:list(value.targets).map(option),orphans:list(value.unassigned_actions).map(option)};
}
type Data = ReturnType<typeof parse>;
class FollowupError extends Error { constructor(message: string, readonly definite: boolean) { super(message); } }
async function request(path: string, body?: object): Promise<unknown> {
  const response=await fetch(path,{method:body?"POST":"GET",cache:"no-store",headers:body?{"Content-Type":"application/json"}:undefined,body:body?JSON.stringify(body):undefined});
  const value:unknown=await responseBody(response).catch(()=>null);
  if(!response.ok) throw new FollowupError(isRecord(value)&&isRecord(value.detail)&&typeof value.detail.message==="string"?value.detail.message:"会后办理暂不可用，请刷新核对结果",response.status >= 400 && response.status < 500);
  return value;
}
function FollowupItem({entry,data,projectId,meetingId,editable,refresh,onLock}:{entry:Item;data:Data;projectId:string;meetingId:string;editable:boolean;refresh:()=>Promise<void>;onLock:(locked:boolean)=>void}) {
  const [action,setAction]=useState<Action>(entry.closed ? "reopen" : "create_action");
  const [owner,setOwner]=useState("");
  const [pending,setPending]=useState(false);
  const [title,setTitle]=useState(entry.title);
  const [assignee,setAssignee]=useState("");const [due,setDue]=useState("");const [standard,setStandard]=useState("");
  const [taskId,setTaskId]=useState("");const [target,setTarget]=useState("");const [reason,setReason]=useState("");const [noAction,setNoAction]=useState(false);
  const [busy,setBusy]=useState(false);const [error,setError]=useState<string|null>(null);const [notice,setNotice]=useState<string|null>(null);
  const retry=useRef<{body:object;id:string}|null>(null);
  async function save() {
    const body={action,expected_basis:entry.basis,reason,no_action_required:action==="close"&&noAction,
      ...(action==="create_action"?{title,assignee_id:assignee,due_date:due,expected_output:standard}:{}),
      ...(action==="reassign"?{owner_user_id:owner}:{}),
      ...(action==="link_action"?{task_id:taskId}:{}),...(action==="carry"?{target_meeting_id:target}:{})};
    if(!retry.current) retry.current={body,id:crypto.randomUUID()};
    setPending(true);onLock(true);
    setBusy(true);setError(null);setNotice(null);
    try {
      await request(`/api/projects/${projectId}/meetings/${meetingId}/agenda/${entry.id}/followup`,{...retry.current.body,request_id:retry.current.id});
      retry.current=null;setPending(false);onLock(false);
      setNotice("办理已记录，请查看更新后的执行状态。");await refresh();
    } catch(error) {if(error instanceof FollowupError && error.definite){retry.current=null;setPending(false);onLock(false);}setError(error instanceof Error?error.message:"本次办理未完成");} finally {setBusy(false);}
  }
  const canSave=!busy&&(pending || (editable&&reason.trim()&&(action!=="reassign"||(entry.status==="open"&&owner&&owner!==entry.owner))&&(action!=="create_action"||(title.trim()&&assignee&&due&&standard.trim()))&&(action!=="link_action"||taskId)&&(action!=="carry"||target)&&(action!=="close"||(!entry.incomplete.length&&entry.sourceReady&&(entry.tasks.length>0||noAction)))));
  return <article id={`meeting-agenda-${entry.id}`} className="space-y-3 rounded-lg border p-3"><div className="flex flex-wrap justify-between gap-2"><h4 className="text-sm font-medium">{entry.title}</h4><span className="text-xs">{entry.closed?"已复核闭环":entry.status==="closed"?"闭环依据已变化，需复查":entry.status==="carried_over"?"已转后续会议，仍需跟踪":"待复查"}</span></div>
    <p className="text-xs">议题负责人：{entry.ownerName}</p>
    <MeetingAgendaHistory path={`/api/projects/${projectId}/meetings/${meetingId}/agenda/${entry.id}/responsibility-history`} />
    {entry.carriedFrom&&<a className="text-xs text-primary underline" href={entry.carriedFrom}>查看原会议与继承议题</a>}
    {entry.source && entry.source.summary.length > 0 && <ul className="space-y-1 text-xs text-muted-foreground">{entry.source.summary.map((line, index) => <li key={index}>{line}</li>)}</ul>}
    {entry.source&&<p className="text-xs"><a className="text-primary underline" href={entry.source.href}>原业务来源：{entry.source.title}</a>{!entry.sourceReady&&" · 仍有待办事项或完成条件尚不能确认"}</p>}
    {entry.tasks.length===0&&<p className="text-xs text-muted-foreground">尚未关联实际行动。</p>}
    <ul className="space-y-2">{entry.tasks.map(task=><li key={task.id} className="rounded-md bg-muted/40 p-2 text-xs"><a className="font-medium text-primary underline" href={task.href}>{task.title}</a>{task.findingId && <a className="ml-3 text-xs text-primary underline" href={`/ai-review?finding=${task.findingId}`}>查看行动建议与人审回执</a>}<p className="mt-1">{states[task.status]??task.status} · {data.members.find(member=>member.id===task.owner)?.title??"历史负责人或尚未指定"} · 截止 {task.date??"未指定"}</p>{task.standard&&<p className="mt-1 whitespace-pre-wrap">完成标准：{task.standard}</p>}{task.evidence&&<p className="mt-1 break-words">完成依据：{task.evidence}</p>}</li>)}</ul>
    {entry.reason&&<p className="whitespace-pre-wrap text-xs text-muted-foreground">上次复查：{entry.reason}</p>}
    {(editable||pending)&&<form className="space-y-3 border-t pt-3" onSubmit={event=>{event.preventDefault();void save();}}><fieldset disabled={busy||pending} className="space-y-3"><label className="block text-xs">办理方式<select className={input} value={action} disabled={busy} onChange={event=>setAction(event.target.value as Action)}>{Object.entries(actions).map(([key,label])=><option key={key} value={key} disabled={key==="reassign"&&entry.status!=="open"}>{label}</option>)}</select></label>
      {action==="reassign"&&<><p className="text-xs text-muted-foreground">请核对当前议题、原业务与关联行动，再指定后续跟进人。行动任务负责人及原会议纪要、确认记录保留；任务调整请打开对应任务办理。</p><label className="block text-xs">接手负责人<select required className={input} value={owner} onChange={event=>setOwner(event.target.value)}><option value="">选择当前项目成员</option>{data.responsibilityMembers.filter(m=>m.id!==entry.owner).map(m=><option key={m.id} value={m.id}>{m.title}</option>)}</select></label></>}
      {action==="create_action"&&<><p className="text-xs text-muted-foreground">这里只录入人员已确认的行动；模型建议仍应通过原建议审核和应用入口办理。</p><label className="block text-xs">行动标题<input required maxLength={512} className={input} value={title} onChange={event=>setTitle(event.target.value)}/></label><div className="grid gap-2 sm:grid-cols-2"><label className="block text-xs">具名负责人<select required className={input} value={assignee} onChange={event=>setAssignee(event.target.value)}><option value="">选择当前项目成员</option>{data.members.map(member=><option key={member.id} value={member.id}>{member.title}</option>)}</select></label><label className="block text-xs">截止日期<input required type="date" className={input} value={due} onChange={event=>setDue(event.target.value)}/></label></div><label className="block text-xs">预期结果与完成标准<textarea required maxLength={20000} className={input} value={standard} onChange={event=>setStandard(event.target.value)}/></label></>}
      {action==="link_action"&&<label className="block text-xs">现有项目任务（最近更新200条）<select required className={input} value={taskId} onChange={event=>setTaskId(event.target.value)}><option value="">选择实际任务</option>{data.tasks.map(task=><option key={task.id} value={task.id}>{task.title}</option>)}</select></label>}
      {action==="carry"&&<label className="block text-xs">承接会议<select required className={input} value={target} onChange={event=>setTarget(event.target.value)}><option value="">选择尚可准备的会议</option>{data.targets.map(meeting=><option key={meeting.id} value={meeting.id}>{meeting.title}</option>)}</select><span className="mt-1 block text-muted-foreground">保留原议题出处，继续关联同一实际任务。<a className="text-primary underline" href={`/projects?project=${projectId}&tab=decisions&meeting=${target}`}>{target?"打开承接会议":"可先登记后续会议"}</a></span></label>}
      {action==="close"&&<><p className="text-xs">{entry.source?.kind === "forecast" ? "请核对原预测版本、当前变化及相关行动后具名确认讨论结论；预测本身不表示业务已完成。" : "仅在关联行动和业务来源的当前完成条件成立时确认；本次确认不代办原业务操作。"}</p>{entry.tasks.length===0&&<label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={noAction} onChange={event=>setNoAction(event.target.checked)}/>已核对，本议题无需新增行动（请填写依据）</label>}{(entry.incomplete.length>0||!entry.sourceReady)&&<p className="text-xs text-destructive">尚有未完成条件，先处理实际任务或原业务，再刷新复查。</p>}</>}
      <label className="block text-xs">确认依据或办理理由<textarea required maxLength={3000} className={input} value={reason} onChange={event=>setReason(event.target.value)}/></label></fieldset>{pending&&!busy&&<p className="text-xs">结果尚未确认，请用原请求重试核对。</p>}<Button size="sm" disabled={!canSave}>{busy?"正在记录…":pending?"重试原请求":"确认办理"}</Button>
    </form>}{error&&<p role="alert" className="text-sm text-destructive">{error}</p>}{notice&&<p role="status" className="text-sm">{notice}</p>}
  </article>;
}

function subscribeLocation(callback:()=>void) { window.addEventListener("popstate",callback);return ()=>window.removeEventListener("popstate",callback); }
function agendaFocus() { const p=new URLSearchParams(window.location.search);return `${p.get("meeting")??""}:${p.get("agenda_owner_id")??""}`; }

export function MeetingFollowup({projectId,meetingId,canManage,isAvailable}:{projectId:string;meetingId:string;canManage:boolean;isAvailable:boolean}) {
  const focus=useSyncExternalStore(subscribeLocation,agendaFocus,()=>"");
  const focused=focus.startsWith(`${meetingId}:`) ? focus.slice(meetingId.length+1) : "";
  const [locked,setLocked]=useState(false);
  const [data,setData]=useState<Data|null>(null);const [busy,setBusy]=useState(false);const [error,setError]=useState<string|null>(null);
  async function load(){setData(parse(await request(`/api/projects/${projectId}/meetings/${meetingId}/followup`),projectId));}
  async function refresh(){setBusy(true);setError(null);try{await load();}catch(error){setError(error instanceof Error?error.message:"执行记录暂不可用");}finally{setBusy(false);}}
  return <details open={focused ? true : undefined} className="rounded-lg border p-3" onToggle={event=>{if(event.currentTarget.open&&!data&&!busy)void refresh();}}><summary className="cursor-pointer text-sm font-medium">会后执行与下次会复查</summary><div className="mt-3 space-y-3"><Button size="sm" variant="outline" disabled={busy||locked} onClick={()=>void refresh()}>刷新实际执行</Button>{error&&<p role="alert" className="text-sm text-destructive">{error}</p>}{data?.orphans.length ? <p className="text-xs text-muted-foreground">另有 {data.orphans.length} 个会议行动尚未归入议题，可用“关联已有任务”补齐：{data.orphans.map(task=>task.title).join("、")}</p>:null}{data&&focused&&!isAvailable&&<p className="text-xs">会议尚未开始时，请在本会议“会前准备”中调整议题负责人；已归档会议保留历史。</p>}{data&&focused&&!data.items.some(e=>e.id===focused)&&<p role="alert" className="text-sm">指定议题已变化或不可访问，请核对当前会议。</p>}{data?.items.length===0&&<p className="text-sm text-muted-foreground">当前没有会议议题，请先准备议程。</p>}{data?.items.slice().sort((a,b)=>Number(b.id===focused)-Number(a.id===focused)).map(entry=><FollowupItem key={`${entry.id}:${entry.basis}:${entry.status}`} entry={entry} data={data} projectId={projectId} meetingId={meetingId} editable={canManage&&isAvailable&&data.editable&&!busy&&!locked} refresh={load} onLock={setLocked}/>)}</div></details>;
}
