"use client";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { caseLinkRequest } from "@/components/cases/case-requirements";
import { field, obj, rows, text, type Row } from "@/components/quality/fmea-sources";
export function PortfolioSourcePicker({project,kind,value,onChange}:{project:string;kind:"schedule"|"cost"|"evidence";value:string;onChange:(v:string)=>void}) {
 const [items,setItems]=useState<Row[]>([]),[next,setNext]=useState(""),[busy,setBusy]=useState(false),[error,setError]=useState("");
 const label={schedule:"资源日期方案",cost:"成本计算（可留空）",evidence:"质量依据原件"}[kind];
 async function load(more=false){setBusy(true);setError("");try{const q=new URLSearchParams({project_id:project,kind});if(more)q.set("before",next);const data=await caseLinkRequest<Row>(`planning/portfolio-options?${q}`);setItems(old=>more?[...old,...rows(data.items)]:rows(data.items));setNext(text(data.next));}catch(e){setError(e instanceof Error?e.message:"来源读取未完成");}finally{setBusy(false);}}
 const selected=items.find(v=>v.id===value),d=obj(selected?.details);
 return <div className="space-y-1"><label className="block text-sm">{label}<select required={kind==="schedule"||kind==="evidence"} className={field} value={value} onChange={e=>onChange(e.target.value)}><option value="">{kind==="cost"?"未知 / 暂不采用":"请选择实际来源"}</option>{value&&!selected&&<option value={value}>所选记录 {value}</option>}{items.map(v=><option key={text(v.id)} value={text(v.id)}>{text(v.title)} · {text(v.created_at)} · {text(obj(v.details).status||obj(v.details).stage||obj(v.details).classification)}</option>)}</select></label><div className="flex gap-2"><Button type="button" size="sm" variant="outline" disabled={busy} onClick={()=>void load()}>读取来源</Button>{next&&<Button type="button" size="sm" variant="outline" disabled={busy} onClick={()=>void load(true)}>更早记录</Button>}</div>{selected&&<p className="text-xs text-muted-foreground">{kind==="schedule"?`结束 ${text(d.finish)||"未知"}；计算于 ${text(d.as_of)}`:kind==="cost"?`${text(d.currency)}；数量 ${text(d.quantity)}；单位 ${text(d.unit_total)||"未知"}；NRE ${text(d.nre_total)||"未知"}；计价日 ${text(d.as_of)}`:text(d.classification)}</p>}{error&&<p role="alert" className="text-xs text-destructive">{error}</p>}</div>;
}
