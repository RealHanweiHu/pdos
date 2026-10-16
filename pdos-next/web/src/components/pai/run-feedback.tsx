"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { feedbackReasons, restoreFeedback, sameFeedback } from "@/lib/run-feedback";
import { usedSkillName } from "@/lib/run-process";
import type { FeedbackReading, FeedbackRecord, FeedbackReason, PendingFeedback } from "@/lib/run-feedback";

type Api = <T>(path: string, body?: unknown) => Promise<T>;

export function FeedbackHistory({ items }: {items:FeedbackRecord[]}) {
  return <div className="space-y-3">{items.map(item=><article key={item.id} className="rounded-lg border p-3 space-y-2 text-sm">
    <p className="font-medium">{item.request.categories.map(key=>feedbackReasons[key]).join("、")}</p>
    {item.request.comment && <p className="whitespace-pre-wrap break-words">{item.request.comment}</p>}
    <p className="subtle">{new Date(item.recorded_at).toLocaleString()} · {item.versions.model_version ? `模型版本 ${item.versions.model_version}` : "本次尚无模型执行版本"}</p>
    <details><summary className="cursor-pointer">所针对的方法与记录</summary><div className="mt-2 space-y-1 break-all subtle"><p>反馈记录 {item.id}</p>{item.versions.skills.length ? item.versions.skills.map(skill=><p key={skill.load_event_id}>{usedSkillName(skill.key)} · {skill.version} · {skill.isolation}</p>) : <p>本次尚无实际加载的方法。</p>}</div></details>
  </article>)}</div>;
}

export function RunFeedback({api,root,runId}:{api:Api;root:string;runId:string}) {
  const [reading,setReading]=useState<FeedbackReading|null>(null);
  const [categories,setCategories]=useState<FeedbackReason[]>([]);
  const [comment,setComment]=useState("");
  const [skill,setSkill]=useState("");
  const [pending,setPending]=useState<PendingFeedback|null>(null);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const [denied,setDenied]=useState(false);
  const lock=useRef(false), generation=useRef(0), storage=useRef<string|null>(null);
  const original=useRef<PendingFeedback|null>(null);
  const endpoint=`${root}/${runId}/feedback`;
  useEffect(()=>{const current=generation;return ()=>{current.current++;};},[]);
  const remember=(value:PendingFeedback|null)=>{
    original.current=value;setPending(value);
    if (!storage.current) return;
    try {if(value)localStorage.setItem(storage.current,JSON.stringify(value));else localStorage.removeItem(storage.current);} catch {/* Exact original request remains in memory. */}
  };
  const validate=(value:FeedbackReading)=>{
    if(value.run_id!==runId || reading && value.owner_id!==reading.owner_id) throw new Error("反馈记录与当前工作不一致。");
    return value;
  };
  const load=async()=>{
    if(lock.current)return;lock.current=true;setBusy(true);setError("");
    const own=generation.current;
    try {
      const value=validate(await api<FeedbackReading>(endpoint));
      if(own!==generation.current)return;
      storage.current=`pdos:run-feedback:${value.owner_id}:${root}:${runId}`;
      setReading(value);setDenied(false);
      let request=original.current;
      if(!request)try{request=restoreFeedback(JSON.parse(localStorage.getItem(storage.current)??"null"),runId,value.owner_id,root);}catch{/* Server history remains readable. */}
      if(request){
        remember(request);setCategories(request.request.categories);setComment(request.request.comment);setSkill(request.request.skill_load_event_id??"");
        const originalPage=validate(await api<FeedbackReading>(`${endpoint}?request_key=${request.request.idempotency_key}`));
        if(own!==generation.current)return;
        const accepted=originalPage.items[0];
        if(accepted){
          if(!sameFeedback(request.request,accepted.request))throw new Error("原请求对应不同反馈，请核对原记录后再处理本地草稿。");
          remember(null);setCategories([]);setComment("");setSkill("");setNotice(`已读回原反馈，记录 ${accepted.id}。`);
          setReading({...value,items:[accepted,...value.items.filter(row=>row.id!==accepted.id)]});
        }
      }
    }catch(failure){if(own===generation.current){setError(failure instanceof Error?failure.message:"反馈暂不可读。");if((failure as {status?:number}).status===403){setDenied(true);setReading(null);}}}
    finally{if(own===generation.current){lock.current=false;setBusy(false);}}
  };
  const send=async()=>{
    if(lock.current||!reading)return;lock.current=true;setBusy(true);setError("");setNotice("");
    const own=generation.current;
    try{
      const request=original.current??{root,run_id:runId,owner_id:reading.owner_id,request:{idempotency_key:crypto.randomUUID(),categories:[...categories].sort(),comment:comment.trim(),skill_load_event_id:skill||null}};
      if(original.current){
        const found=validate(await api<FeedbackReading>(`${endpoint}?request_key=${request.request.idempotency_key}`));
        if(own!==generation.current)return;
        if(found.items[0]){
          if(!sameFeedback(request.request,found.items[0].request))throw new Error("原请求对应不同反馈，请核对原记录。");
          remember(null);setCategories([]);setComment("");setSkill("");setReading({...found,items:[found.items[0],...reading.items.filter(row=>row.id!==found.items[0].id)]});setNotice(`已读回原反馈，记录 ${found.items[0].id}。`);return;
        }
      }
      remember(request);
      const result=await api<{run_id:string;feedback:FeedbackRecord}>(endpoint,request.request);
      if(own!==generation.current)return;
      if(result.run_id!==runId||!result.feedback||!sameFeedback(request.request,result.feedback.request))throw new Error("反馈保存结果尚未核对，请保留同一请求。");
      remember(null);setCategories([]);setComment("");setSkill("");setReading({...reading,items:[result.feedback,...reading.items.filter(row=>row.id!==result.feedback.id)]});setNotice(`反馈已保存，记录 ${result.feedback.id}。`);
    }catch(failure){if(own===generation.current){setError(failure instanceof Error?failure.message:"保存结果待核对，请保留原请求。");if((failure as {status?:number}).status===403){setDenied(true);setReading(null);}}}
    finally{if(own===generation.current){lock.current=false;setBusy(false);}}
  };
  const more=async()=>{
    if(lock.current||!reading?.next_before)return;lock.current=true;setBusy(true);setError("");const own=generation.current;
    try{const value=validate(await api<FeedbackReading>(`${endpoint}?before=${reading.next_before}`));if(own!==generation.current)return;setReading({...value,items:[...reading.items,...value.items.filter(row=>!reading.items.some(prior=>prior.id===row.id))]});}
    catch(failure){if(own===generation.current){setError(failure instanceof Error?failure.message:"反馈暂不可读。");if((failure as {status?:number}).status===403){setDenied(true);setReading(null);}}}
    finally{if(own===generation.current){lock.current=false;setBusy(false);}}
  };
  return <details className="run-feedback rounded-lg border p-3" onToggle={event=>{if(event.currentTarget.open&&!reading&&!lock.current)void load();}}><summary className="cursor-pointer text-sm font-medium">反馈这次工作</summary>
    <div className="mt-3 space-y-3 text-sm">
      <p className="subtle">反馈只保存在本次工作中，关联原方法和模型版本。若要立即停止后续执行，请使用取消。</p>
      {error&&<p role="alert" className="break-words">{error}</p>}{notice&&<p role="status" className="break-words">{notice}</p>}
      <Button size="sm" variant="outline" disabled={busy} onClick={()=>void load()}>读取原反馈记录</Button>
      {denied?<p className="subtle">当前无法读取本次反馈，核对权限后可重试读取。</p>:reading?<>
        {pending&&<div className="space-y-2"><p>原保存结果待核对。重开只读取原记录，不自动再次提交。</p><Button variant="outline" disabled={busy} onClick={()=>void send()}>核对并重试原反馈</Button></div>}
        <form onSubmit={event=>{event.preventDefault();if(categories.length&&!pending)void send();}}><fieldset className="space-y-3" disabled={busy||!!pending}>
          <fieldset className="space-y-2"><legend className="mb-2 font-medium">哪里需要改进？（可多选）</legend>{Object.entries(feedbackReasons).map(([key,label])=><label key={key} className="feedback-choice"><input type="checkbox" checked={categories.includes(key as FeedbackReason)} onChange={event=>setCategories(old=>event.target.checked?[...old,key as FeedbackReason]:old.filter(value=>value!==key))}/><span>{label}</span></label>)}</fieldset>
          <label className="block">针对哪种方法<select value={skill} onChange={event=>setSkill(event.target.value)}><option value="">本次工作整体</option>{reading.current_versions.skills.map(value=><option key={value.load_event_id} value={value.load_event_id}>{usedSkillName(value.key)} · {value.version} · {value.isolation}</option>)}</select></label>
          <label className="block">补充说明（可选）<textarea rows={3} maxLength={2000} value={comment} onChange={event=>setComment(event.target.value)} placeholder="例如：哪一项数值或对象不对、缺少什么来源。"/></label>
          <Button disabled={busy||!!pending||!categories.length}>保存本次反馈</Button>
        </fieldset></form>
        <p className="subtle">{reading.current_versions.model_version?`本次模型版本：${reading.current_versions.model_version}`:"本次尚无模型执行版本。"}反馈不改变业务决定或资格。</p>
        <FeedbackHistory items={reading.items}/>{!reading.items.length&&<p className="subtle">本次还没有已保存反馈。</p>}
        {reading.next_before&&<Button size="sm" variant="outline" disabled={busy} onClick={()=>void more()}>更早反馈</Button>}
      </>:!error&&<p className="subtle">正在读取本次工作与原反馈…</p>}
    </div>
  </details>;
}
