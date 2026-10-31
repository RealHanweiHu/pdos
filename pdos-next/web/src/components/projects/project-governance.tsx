"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowClockwise, Check, CaretRight } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { DetailSheet } from "@/components/ui/detail-sheet";
import { categoryTransport } from "@/lib/category-transport";
import { utcText, type ProjectApi } from "@/lib/project-plan-view";
import { gateStateNames, type Governance, type GateFact, type GateCheck } from "@/lib/project-governance";
import styles from "./project-governance.module.css";

type Command={command_id:string;idempotency_key:string;operation:string;product_id:string;expected_revision:number;source_read_set:{artifact_id:string;expected_revision:number}[];payload:Record<string,unknown>};
type Prepared={command:Command;review:{operation:string;name:string;reason:string;effect:string;stage_name?:string;outcome?:string;gate?:GateFact;template?:{name:string;stages:{name:string}[]};plan?:{revision:number};task_title?:string};confirmation_token?:string};
type Pending={stage:"preview"|"execute";command:Command};
const actions:Record<string,string>={"work.stage.adopt":"采用阶段模板","work.baseline.approve":"批准当前计划基线","work.stage.review.submit":"提交阶段评审","work.stage.decide":"办理阶段决定","work.stage.milestone.bind":"关联门禁里程碑"};

function Checks({value}:{value:GateFact}) {return <div className={styles.checks}>{value.checks.map(c=><details key={c.key}><summary><span>{c.label}</span><span data-state={c.state}>{gateStateNames[c.state]}</span></summary><p>{c.detail}</p>{c.assessment&&<ul>{[...c.assessment.blocked,...c.assessment.unknown].map((v,i)=><li key={i}>{v}</li>)}</ul>}{c.scope&&<p>{c.purpose} · {c.scope.quantity??"数量未知"} {c.scope.unit} · {c.scope.site??c.scope.regions?.join("、")??"地点未知"}</p>}</details>)}</div>;}
function Maturity({name,value}:{name:string;value:GateCheck}) {return <section><h3>{name}</h3><p data-state={value.state}>{gateStateNames[value.state]}</p><span>{value.detail}</span>{!!value.decisions?.length&&<small>{value.decisions.length} 项当前专业签核</small>}</section>;}

export function ProjectGovernance({api,categoryId,productId,projectId,principalId,onSaved,readVersion=0}:{api:ProjectApi;categoryId:string;productId:string;projectId:string;principalId:string;onSaved?:()=>void;readVersion?:number}) {
 const scoped=useMemo(()=>categoryTransport(categoryId,api),[api,categoryId]);
 const storageKey=`pdos:governance:${principalId}:${categoryId}:${productId}:${projectId}`;
 const [data,setData]=useState<Governance|null>(null),[error,setError]=useState(""),[notice,setNotice]=useState(""),[busy,setBusy]=useState(false),[attempt,setAttempt]=useState(0);
 const [template,setTemplate]=useState("standard@1"),[packageId,setPackageId]=useState(""),[taskKey,setTaskKey]=useState(""),[reason,setReason]=useState("");
 const [prepared,setPrepared]=useState<Prepared|null>(null),[pending,setPending]=useState<Pending|null>(null),[rejected,setRejected]=useState(false);
 const lock=useRef(false),alive=useRef(true);
 useEffect(()=>{alive.current=true;void Promise.resolve().then(()=>{if(!alive.current)return;try {const saved=JSON.parse(localStorage.getItem(storageKey)??"null");if(saved?.pending?.command?.product_id===productId&&saved.pending.command.payload.project_id===projectId)setPending(saved.pending);if(typeof saved?.reason==="string")setReason(saved.reason);}catch{}});return()=>{alive.current=false;};},[storageKey,productId,projectId]);
 useEffect(()=>{let active=true;void scoped<Governance>(`v1/products/${productId}/projects/${projectId}/governance`).then(v=>{if(v.project_id!==projectId)throw new Error("项目范围不一致，请刷新。");if(active){setData(v);setError("");}}).catch(e=>{if(active){setData(null);setError(e.message);}});return()=>{active=false;};},[scoped,productId,projectId,attempt,readVersion]);
 function remember(value:Pending|null,text=reason,required=false){try{localStorage.setItem(storageKey,JSON.stringify({pending:value,reason:text}));}catch{if(required)throw new Error("无法保留原请求，尚未提交。请恢复浏览器本地存储后重试。");}setPending(value);}
 async function run(value:Pending){
  if(lock.current)return;lock.current=true;setBusy(true);setError("");setRejected(false);
  let committed=false;
  try{
   remember(value,reason,true);
   if(value.stage==="preview"){
    const result=await scoped<Prepared>("v1/commands/preview",value.command);
    if(result.command.command_id!==value.command.command_id||result.command.product_id!==productId||result.command.payload.project_id!==projectId||result.review.operation!==value.command.operation)throw new Error("确认材料不完整，请按原请求重试。");
    if(!alive.current)return;remember(null);setPrepared(result);
   }else{
    const receipt=await scoped<{id:string;subject_type:string}>("v1/commands",value.command);
    if(!receipt.id||receipt.subject_type!=="project_governance")throw new Error("保存结果尚未确认，请按原请求核对。");
    committed=true;if(!alive.current)return;remember(null);setPrepared(null);setNotice(`${actions[value.command.operation]}已完成。`);setAttempt(v=>v+1);onSaved?.();
   }
  }catch(e){if(!alive.current)return;const failure=e as Error&{status?:number};setError(failure.message);if(value.stage==="execute")setPrepared(null);setRejected(!committed&&[400,401,403,404,409,422].includes(failure.status??0));if(failure.status===403||failure.status===401)setData(null);}
  finally{lock.current=false;if(alive.current)setBusy(false);}
 }
 async function prepare(operation:string,fields:Record<string,unknown>){
  if(!data||lock.current)return;
  if(reason.trim().length<3){setError("请先填写至少 3 字的本次办理说明。");return;}
  lock.current=true;setBusy(true);setError("");
  try{
   const evidence=operation==="work.stage.review.submit"?await scoped<GateFact>(`v1/products/${productId}/projects/${projectId}/governance/review-inputs${packageId?`?package_id=${packageId}`:""}`):data.gate;
   const command:Command={command_id:crypto.randomUUID(),idempotency_key:crypto.randomUUID(),operation,product_id:productId,expected_revision:data.product_revision,source_read_set:evidence.required_source_read_set,payload:{project_id:projectId,expected_project_revision:data.project_revision,expected_governance_revision:data.revision,reason:reason.trim(),...fields}};
   lock.current=false;setBusy(false);await run({stage:"preview",command});
  }catch(e){setError((e as Error).message);lock.current=false;setBusy(false);}
 }
 async function morePackages(){
  if(!data?.release_packages_cursor||lock.current)return;
  lock.current=true;setBusy(true);setError("");
  try{const page=await scoped<{items:Governance["release_packages"];next_cursor:string|null}>(`v1/products/${productId}/release-packages?project_id=${projectId}&history_cursor=${data.release_packages_cursor}`);if(alive.current)setData(current=>current?{...current,release_packages:[...new Map([...current.release_packages,...page.items].map(p=>[p.id,p])).values()],release_packages_cursor:page.next_cursor}:null);}catch(e){setError((e as Error).message);}finally{lock.current=false;if(alive.current)setBusy(false);}
 }
 const disabled=busy||!!pending||!!prepared;
 return <div className={styles.page}><header className={styles.heading}><div><h2>阶段与门禁</h2><p>{data?.template?`${data.template.name} · ${data.template.id}`:"采用适用路径，再核对各阶段出口。"}</p></div><Button size="xs" variant="ghost" disabled={busy||!!prepared} onClick={()=>setAttempt(v=>v+1)}><ArrowClockwise/>刷新</Button></header>
 {error&&<p role="alert" className={styles.error}>{error}</p>}{notice&&<p role="status">{notice}</p>}
 {pending&&<div className={styles.recovery}><p>原请求已保留，可核对同一次办理结果。</p><Button size="sm" disabled={busy} onClick={()=>void run(pending)}>按原请求重试</Button>{(pending.stage==="preview"||rejected)&&<Button size="sm" variant="ghost" disabled={busy} onClick={()=>{remember(null);setPrepared(null);}}>保留说明，重新核对</Button>}</div>}
 {!data&&!error&&<p role="status">正在读取实际阶段与门禁依据…</p>}
 {data&&<><ol className={styles.stages} aria-label="项目阶段位置">{data.stages.map(stage=><li key={stage.id} data-state={stage.status}><span>{stage.status==="passed"?<Check size={12}/>:stage.status==="current"?<CaretRight size={12}/>:null}</span><span>{stage.name}{stage.actual&&<small className={styles.stageActual}>{utcText(stage.actual)}</small>}</span></li>)}</ol>
 <div className={styles.titleRow}><h3>{data.current_stage?`${data.current_stage.name} · 出口条件`:data.completed?"全部阶段已完成":"尚未采用阶段模板"}</h3><span title={data.health.reason}>{data.health.label}</span></div>
 {data.current_stage&&<Checks value={data.gate}/>}
 <div className={styles.maturity}><Maturity name="产品与验证" value={data.gate.maturity.engineering}/><Maturity name="制造" value={data.gate.maturity.manufacturing}/><Maturity name="交付适用性" value={data.gate.maturity.delivery}/></div>
 <div className={styles.columns}><section><h3>下一阶段进入条件</h3>{data.next_gate?<><p className={styles.muted}>下一阶段的进入条件提前显示，便于准备；不计入当前阶段出口阻塞。</p><Checks value={data.next_gate}/></>:<p className={styles.muted}>当前路径没有下一阶段。</p>}</section><section><h3>门禁四时间</h3><dl className={styles.times}><dt>基线</dt><dd>{utcText(data.timeline.baseline?.latest_finish??null)}</dd><dt>预测</dt><dd>{utcText(data.timeline.forecast?.latest_finish??null)}</dd><dt>承诺</dt><dd>{data.timeline.commitments.length?data.timeline.commitments.map(c=><p key={c.id}>{utcText(c.promised_at)} · {c.fulfilled?"已履行":"原承诺保留"}</p>):"尚无对应承诺"}</dd><dt>实际</dt><dd>{utcText(data.timeline.actual)}</dd></dl><p className={styles.muted}>{data.timeline.task_key?`关联计划任务：${data.timeline.task_key}`:"关联真实计划任务后显示门禁日期。"}</p></section></div>
 {data.can_manage&&<details className={styles.manage}><summary>办理阶段与计划基线</summary><fieldset disabled={disabled}><label>本次办理说明<textarea maxLength={2000} value={reason} onChange={e=>{setReason(e.target.value);remember(pending,e.target.value);}} placeholder="说明范围、依据及需要接续的事项"/></label>{!data.template&&<div className={styles.formRow}><label>阶段路径<select value={template} onChange={e=>setTemplate(e.target.value)}>{data.templates.map(t=><option key={t.id} value={t.id}>{t.name} · {t.stages.map(v=>v.name).join(" → ")}</option>)}</select></label><Button size="sm" onClick={()=>void prepare("work.stage.adopt",{template})}>核对并采用模板</Button></div>}{data.plan&&<div className={styles.formRow}><p>当前计划 v{data.plan.revision} · {data.baseline?.plan.id===data.plan.id?"已具名批准基线":"尚未批准为基线"}</p><Button size="sm" variant="outline" disabled={data.baseline?.plan.id===data.plan.id} onClick={()=>void prepare("work.baseline.approve",{plan:data.plan})}>具名批准基线</Button></div>}
 {data.current_stage&&<><div className={styles.formRow}><label>门禁里程碑<select value={taskKey} onChange={e=>setTaskKey(e.target.value)}><option value="">选择当前计划任务</option>{data.plan_tasks.map(t=><option key={t.key} value={t.key}>{t.title}</option>)}</select></label><Button size="sm" variant="outline" disabled={!taskKey} onClick={()=>void prepare("work.stage.milestone.bind",{stage_id:data.current_stage!.id,task_key:taskKey})}>关联里程碑</Button></div><div className={styles.formRow}><label>本阶段适用的发布包<select value={packageId} onChange={e=>setPackageId(e.target.value)}><option value="">未选择 · 概念 / 计划阶段可留空</option>{data.release_packages.map(p=><option key={p.id} value={p.id}>{p.purpose} · v{p.revision}{p.current?.version.id!==p.id?" · 历史":""}</option>)}</select>{data.release_packages_cursor&&<Button type="button" size="xs" variant="ghost" onClick={()=>void morePackages()}>加载更多发布包</Button>}</label><Button size="sm" onClick={()=>void prepare("work.stage.review.submit",{stage_id:data.current_stage!.id,release_package:packageId?{id:packageId,revision:data.release_packages.find(p=>p.id===packageId)!.revision}:null})}>核对并提交评审</Button></div>{data.review&&<div className={styles.formRow}><p>{data.gate.review_current?"评审材料已固定，等待本人决定。":"评审依据已变化，请重新提交。"}</p><div><Button size="sm" variant="outline" disabled={!data.gate.review_current} onClick={()=>void prepare("work.stage.decide",{review:{id:data.review!.id,revision:data.review!.revision},outcome:"returned"})}>具名退回</Button><Button size="sm" disabled={!data.gate.review_current||!["READY","READY_WITH_CONDITIONS"].includes(data.gate.state)} onClick={()=>void prepare("work.stage.decide",{review:{id:data.review!.id,revision:data.review!.revision},outcome:"approved"})}>具名批准推进</Button></div></div>}</>}
 </fieldset></details>}
 <section className={styles.history}><h3>冻结点与阶段历史</h3>{!data.history.length?<p className={styles.muted}>尚无阶段决定或批准基线。</p>:data.history.slice().reverse().map(h=><details key={h.id}><summary><span>{actions[h.operation]}{h.stage_name?` · ${h.stage_name}`:""}{h.outcome?` · ${h.outcome==="approved"?"已批准":"已退回"}`:""}</span><time>{utcText(h.at)}</time></summary><p>{h.reason}</p><small>{h.actor_id===principalId?"本人办理":`具名人 ${h.actor_id}`} · 回执 {h.receipt_id}</small></details>)}</section></>}
 {prepared && <DetailSheet onClose={()=>{if(!busy&&!pending)setPrepared(null);}} title={prepared?actions[prepared.command.operation]:"核对办理"}>{prepared&&<div className={styles.review}><p>{prepared.review.name}</p><p>{prepared.review.reason}</p>{prepared.review.template&&<p>{prepared.review.template.name}：{prepared.review.template.stages.map(s=>s.name).join(" → ")}</p>}{prepared.review.plan&&<p>批准当前计划 v{prepared.review.plan.revision} 为基线</p>}{prepared.review.task_title&&<p>关联里程碑：{prepared.review.task_title}</p>}{prepared.review.gate&&<Checks value={prepared.review.gate}/>}<p className={styles.muted}>{prepared.review.effect}</p>{error&&<p role="alert" className={styles.error}>{error}</p>}<div className={styles.actions}><Button variant="outline" disabled={busy||!!pending} onClick={()=>setPrepared(null)}>返回</Button><Button disabled={busy||!!pending} onClick={()=>void run({stage:"execute",command:prepared.command})}>{prepared.command.operation==="work.stage.decide"?(prepared.review.outcome==="approved"?"本人批准推进":"本人退回") : prepared.command.operation==="work.baseline.approve"?"本人批准此基线":"确认办理"}</Button></div></div>}</DetailSheet>}
 </div>;
}
