"use client";
import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { caseLinkRequest } from "@/components/cases/case-requirements";
import { field, obj, rows, text, type Row } from "@/components/quality/fmea-sources";

const when = (v: unknown) => v ? new Date(text(v)).toLocaleString() : "未知";
export function MilestoneDesignationHistory({projectId,nodeId}:{projectId:string;nodeId:string}) {
  const [data,setData]=useState<Row|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState("");
  async function load(more=false) {
    setBusy(true);setError("");
    try {const result=await caseLinkRequest<Row>("planning/milestone-designation-history",{
      project_id:projectId,node_id:nodeId,before_version:more?data?.next_before_version:null,
    });setData(old=>more?{...result,items:[...rows(old?.items),...rows(result.items)]}:result);}
    catch(e){setError(e instanceof Error?e.message:"标记历史读取未完成");}finally{setBusy(false);}
  }
  return <details className="border-t pt-2"><summary className="cursor-pointer text-xs">业务重要性历史</summary><div className="mt-2 space-y-2 text-xs">
    <Button type="button" size="sm" variant="outline" disabled={busy} onClick={()=>void load()}>读取／刷新历史</Button>
    {error&&<p role="alert" className="text-destructive">{error}</p>}
    {data&&rows(data.items).length===0&&<p>尚无具名标记。</p>}
    {rows(data?.items).map(v=><article key={text(v.id)} className="space-y-1 border-l pl-2">
      <p>v{text(v.version)} · {v.is_key===true?"业务关键里程碑":"普通里程碑"} · {text(v.actor_name)} · {when(v.created_at)}</p>
      <p className="whitespace-pre-wrap">{text(v.reason)}</p>
      <p className="text-muted-foreground">当时节点：{text(obj(v.snapshot).title)}；完成判据：{text(obj(v.snapshot).completion_criteria)}</p>
      <p className="break-all text-muted-foreground">原基线 {text(v.baseline_id)}</p>
    </article>)}
    {data?.next_before_version!=null&&<Button type="button" size="sm" variant="outline" disabled={busy} onClick={()=>void load(true)}>更早标记</Button>}
  </div></details>;
}

export function MilestoneDesignationForm({projectId,nodeId,baselineId,current,sourceCurrent,canManage,onSaved}:{
  projectId:string;nodeId:string;baselineId:string;current:Row|null;sourceCurrent:boolean|null;canManage:boolean;onSaved:()=>Promise<void>;
}) {
  const [choice,setChoice]=useState(current?.is_key===false?"routine":"key");
  const [reason,setReason]=useState(""),[busy,setBusy]=useState(false),[error,setError]=useState(""),[notice,setNotice]=useState("");
  const requests=useRef(new Map<string,string>());
  async function save() {
    const body={project_id:projectId,node_id:nodeId,expected_baseline_id:baselineId,
      expected_version:current?.version??0,is_key:choice==="key",reason};
    const signature=JSON.stringify(body);let id=requests.current.get(signature);
    if(!id){id=crypto.randomUUID();requests.current.set(signature,id);}
    setBusy(true);setError("");setNotice("");
    try {await caseLinkRequest("planning/milestone-designations",{...body,request_id:id});
      setNotice("业务重要性已保存，历史版本保留。");await onSaved();}
    catch(e){setError(e instanceof Error?e.message:"业务标记保存未完成");}finally{setBusy(false);}
  }
  return <div className="space-y-2 rounded-md border p-3 text-xs">
    <p className="font-medium">业务重要性：{current?(current.is_key===true?"关键里程碑":"普通里程碑"):"尚未标记"}</p>
    {current&&<p>{text(current.actor_name)} · v{text(current.version)} · {when(current.created_at)}<br/>{text(current.reason)}</p>}
    {sourceCurrent===false&&<p className="text-primary">名称、完成判据或责任安排已变化，请按当前正式计划重核。原标记仍保留。</p>}
    <p className="text-muted-foreground">由项目管理人员明确业务重要性，与计算出的关键路径分别记录。新标记从保存时生效，不回填过去时间，也不改变完成、排程或批准。</p>
    {canManage&&<form className="space-y-2" onSubmit={e=>{e.preventDefault();void save();}}>
      <fieldset disabled={busy} className="space-y-2"><label className="block">本次标记<select className={field} value={choice} onChange={e=>setChoice(e.target.value)}><option value="key">业务关键里程碑</option><option value="routine">普通里程碑</option></select></label>
      <label className="block">选择或修订依据<textarea className={field} required maxLength={2048} value={reason} onChange={e=>setReason(e.target.value)}/></label></fieldset>
      <Button type="submit" size="sm" disabled={busy||!reason.trim()}>具名保存业务重要性</Button>
    </form>}
    {error&&<p role="alert" className="text-destructive">{error}</p>}{notice&&<p role="status">{notice}</p>}
    <MilestoneDesignationHistory key={text(current?.id)} projectId={projectId} nodeId={nodeId}/>
  </div>;
}
