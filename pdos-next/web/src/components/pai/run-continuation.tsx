"use client";

import {useEffect,useRef,useState} from "react";
import {Button} from "@/components/ui/button";
import {matchesContinuation,restoreContinuation} from "@/lib/run-continuation";
import type {ContinuationReading,PendingContinuation} from "@/lib/run-continuation";

type Api=<T>(path:string,body?:unknown)=>Promise<T>;
type Run={run_id:string;goal?:string;status:string;reverted:boolean;conversation?:{previous_run_id:string|null;next_run_id:string|null}};
export function RunContinuation({api,root,run,onOpen}:{api:Api;root:string;run:Run;onOpen:(id:string)=>Promise<unknown>}) {
  const [reading,setReading]=useState<ContinuationReading|null>(null),[goal,setGoal]=useState("");
  const [pending,setPending]=useState<PendingContinuation|null>(null),[busy,setBusy]=useState(false);
  const [error,setError]=useState(""),[notice,setNotice]=useState("");
  const original=useRef<PendingContinuation|null>(null),storage=useRef<string|null>(null),lock=useRef(false),generation=useRef(0);
  useEffect(()=>{const counter=generation;return()=>{counter.current++;};},[]);
  const remember=(value:PendingContinuation|null)=>{original.current=value;setPending(value);if(storage.current)try{if(value)localStorage.setItem(storage.current,JSON.stringify(value));else localStorage.removeItem(storage.current);}catch{/* Keep exact original in memory. */}};
  const inspect=async()=>{
    const value=await api<ContinuationReading>(`${root}/${run.run_id}/continuation`);
    if(value.run_id!==run.run_id||reading&&reading.owner_id!==value.owner_id)throw new Error("后续工作与原运行不一致。");
    return value;
  };
  const load=async()=>{
    if(lock.current)return;lock.current=true;setBusy(true);setError("");const own=generation.current;
    try{
      const value=await inspect();if(own!==generation.current)return;
      storage.current=`pdos:continuation:${value.owner_id}:${root}:${run.run_id}`;
      setReading(value);
      let request=original.current;
      if(!request)try{request=restoreContinuation(JSON.parse(localStorage.getItem(storage.current)??"null"),root,value.owner_id,run.run_id);}catch{/* Original server record remains readable. */}
      if(request){
        remember(request);setGoal(request.request.goal);
        if(matchesContinuation(request.request,value)){remember(null);setGoal("");setNotice("已读回同一后续工作，未再次提交。");}
        else if(value.existing)throw new Error("原工作已有其他后续，请打开实际记录核对。");
      }
    }catch(failure){if(own===generation.current){setError(failure instanceof Error?failure.message:"原工作暂不可读。");if((failure as {status?:number}).status===403)setReading(null);}}
    finally{if(own===generation.current){lock.current=false;setBusy(false);}}
  };
  const send=async()=>{
    if(lock.current||!reading)return;lock.current=true;setBusy(true);setError("");setNotice("");const own=generation.current;
    try{
      const request=original.current??{root,owner_id:reading.owner_id,request:{goal:goal.trim(),idempotency_key:crypto.randomUUID(),continue_from_run_id:run.run_id}};
      const latest=await inspect();if(own!==generation.current)return;
      if(latest.existing){
        setReading(latest);
        if(!matchesContinuation(request.request,latest))throw new Error("原工作已有其他后续，请打开实际记录核对。");
        remember(null);setGoal("");setNotice("已读回同一后续工作，未再次提交。");return;
      }
      if(!latest.can_continue)throw new Error("原运行尚未结束或已撤回，请先核对当前状态。");
      remember(request);
      const result=await api<{run_id:string;continued_from_id:string|null;execution_state?:string}>(root,request.request);
      if(own!==generation.current)return;
      if(result.continued_from_id!==run.run_id||!result.run_id)throw new Error("后续受理结果待核对，请保留原请求。");
      remember(null);setGoal("");setReading({...latest,can_continue:false,existing:{run_id:result.run_id,goal:request.request.goal,idempotency_key:request.request.idempotency_key}});
      setNotice(result.execution_state==="durable_runtime_unavailable"?"后续工作已保存，执行服务恢复后继续。":"后续工作已保存，可打开查看实际结果。");
      await onOpen(result.run_id);
    }catch(failure){if(own===generation.current){setError(failure instanceof Error?failure.message:"保存结果待核对。");if((failure as {status?:number}).status===403)setReading(null);}}
    finally{if(own===generation.current){lock.current=false;setBusy(false);}}
  };
  const terminal=["completed","partial","failed","cancelled"].includes(run.status);
  return <div className="space-y-2 text-sm">
    {run.goal&&<p className="break-words font-medium">本次目标：{run.goal}</p>}
    {run.conversation?.previous_run_id&&<Button size="sm" variant="outline" disabled={busy} onClick={()=>void onOpen(run.conversation!.previous_run_id!).catch(failure=>setError(failure.message))}>查看前一次工作</Button>}
    {run.conversation?.next_run_id&&<Button size="sm" variant="outline" disabled={busy} onClick={()=>void onOpen(run.conversation!.next_run_id!).catch(failure=>setError(failure.message))}>打开后续工作</Button>}
    {terminal&&!run.reverted&&<details className="rounded-lg border p-3" onToggle={event=>{if(event.currentTarget.open&&!reading&&!lock.current)void load();}}><summary className="cursor-pointer font-medium">基于这次工作继续</summary><div className="mt-3 space-y-3">
      <p className="subtle">补充目标或继续追问，沿用本人的原会话、对象与来源。旧结果保留；事实与权限在继续前重新核对。</p>
      {error&&<p role="alert">{error}</p>}{notice&&<p role="status">{notice}</p>}
      <Button size="sm" variant="outline" disabled={busy} onClick={()=>void load()}>读取后续记录</Button>
      {reading?.existing?<Button disabled={busy} onClick={()=>void onOpen(reading.existing!.run_id).catch(failure=>setError(failure.message))}>打开已保存的后续工作</Button>:reading?.can_continue?<form className="space-y-3" onSubmit={event=>{event.preventDefault();if(!pending&&goal.trim().length>=3)void send();}}><label>接下来希望得到什么结果<textarea required minLength={3} maxLength={8000} rows={3} value={goal} disabled={busy||!!pending} onChange={event=>setGoal(event.target.value)} /></label><Button disabled={busy||!!pending||goal.trim().length<3}>保存并继续</Button></form>:reading&&<p>原工作当前不能继续，请核对运行状态。</p>}
      {pending&&!reading?.existing&&<div className="space-y-2"><p>原受理结果待核对。刷新只读取，不自动重新提交。</p><Button variant="outline" disabled={busy} onClick={()=>void send()}>核对并重试原请求</Button></div>}
    </div></details>}
  </div>;
}
